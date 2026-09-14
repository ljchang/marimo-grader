"""Roster import (preview → apply) and roster listing."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from grader.auth.deps import Membership, api_error, require_instructor, require_staff
from grader.db import get_db
from grader.models import Enrollment, EnrollmentStatus, Role, RosterUpload, User
from grader.services import audit, roster
from grader.services.artifacts import store

router = APIRouter(tags=["roster"])


@router.get("/offerings/{offering_id}/roster")
def list_roster(m: Membership = Depends(require_staff), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Enrollment)
        .join(User)
        .where(Enrollment.offering_id == m.offering.id)
        .order_by(User.netid)
    ).all()
    return [
        {
            "netid": e.user.netid,
            "display_name": e.user.name,
            "role": e.role.value,
            "status": e.status.value,
            "section": e.section.name if e.section else None,
            "ta_sections": e.ta_sections or [],
        }
        for e in rows
        if e.role != Role.student or m.can_see_section(e.section_id)
    ]


@router.post("/offerings/{offering_id}/roster/preview")
async def roster_preview(
    file: UploadFile = File(...),
    source: str = Form("canvas_csv"),
    m: Membership = Depends(require_instructor),
    db: Session = Depends(get_db),
):
    if source not in roster.PARSERS:
        raise api_error(422, "bad_source", f"source must be one of {list(roster.PARSERS)}")
    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise api_error(413, "too_large", "roster file too large")
    text = raw.decode("utf-8-sig", errors="replace")
    try:
        rows = roster.PARSERS[source](text)
    except Exception as e:  # noqa: BLE001
        raise api_error(422, "parse_failed", f"could not parse {source}: {e}") from e
    if source == "canvas_csv":
        # Keep the gradebook export: it is also the template for Canvas grade export.
        art = store().put(db, raw, kind="roster", content_type="text/csv")
        db.add(
            RosterUpload(
                offering_id=m.offering.id, source=source, artifact_id=art.id, uploaded_by=m.user.id
            )
        )
    plan = roster.preview(db, m.offering, rows)
    plan["source"] = source
    plan["parsed"] = len(rows)
    return plan


class RosterPlan(BaseModel):
    adds: list[dict[str, Any]] = Field(default_factory=list)
    drops: list[dict[str, Any]] = Field(default_factory=list)
    moves: list[dict[str, Any]] = Field(default_factory=list)
    reason: str | None = None


@router.post("/offerings/{offering_id}/roster/apply")
def roster_apply(
    plan: RosterPlan, m: Membership = Depends(require_instructor), db: Session = Depends(get_db)
):
    counts = roster.apply(db, m.offering, plan.model_dump())
    audit.record(
        db,
        actor_id=m.user.id,
        offering_id=m.offering.id,
        entity="roster",
        entity_id=m.offering.id,
        action="import",
        after={
            **counts,
            "adds": [r["netid"] for r in plan.adds],
            "drops": [r["netid"] for r in plan.drops],
        },
        reason=plan.reason,
    )
    return counts


class StaffIn(BaseModel):
    netid: str
    role: Role = Role.ta
    ta_sections: list[str] = Field(default_factory=list)
    display_name: str | None = None


@router.post("/offerings/{offering_id}/roster/staff", status_code=201)
def add_staff(
    body: StaffIn, m: Membership = Depends(require_instructor), db: Session = Depends(get_db)
):
    if body.role == Role.student:
        raise api_error(422, "bad_role", "use roster import for students")
    netid = body.netid.strip().lower()
    user = db.scalar(select(User).where(User.netid == netid))
    if user is None:
        user = User(netid=netid, display_name=body.display_name)
        db.add(user)
        db.flush()
    e = db.scalar(
        select(Enrollment).where(
            Enrollment.offering_id == m.offering.id, Enrollment.user_id == user.id
        )
    )
    before = {"role": e.role.value, "status": e.status.value} if e else None
    if e is None:
        e = Enrollment(offering_id=m.offering.id, user_id=user.id)
        db.add(e)
    e.role, e.ta_sections = body.role, body.ta_sections
    from grader.models import EnrollmentStatus

    e.status = EnrollmentStatus.active
    db.flush()
    audit.record(
        db,
        actor_id=m.user.id,
        offering_id=m.offering.id,
        entity="enrollment",
        entity_id=e.id,
        action="staff",
        before=before,
        after={"netid": netid, "role": e.role.value, "ta_sections": e.ta_sections},
    )
    return {"netid": netid, "role": e.role.value, "ta_sections": e.ta_sections}


class StudentIn(BaseModel):
    netid: str
    display_name: str | None = None
    section: str | None = None


@router.post("/offerings/{offering_id}/roster/students", status_code=201)
def add_student(
    body: StudentIn, m: Membership = Depends(require_instructor), db: Session = Depends(get_db)
):
    """Add or reinstate one student without a CSV round-trip.

    Import stays the bulk path and the source of truth; this is for the
    late add and the person Canvas has not caught up with yet.
    """
    netid = body.netid.strip().lower()
    if not netid:
        raise api_error(422, "bad_netid", "a NetID is required")
    user = db.scalar(select(User).where(User.netid == netid))
    if user is None:
        user = User(netid=netid, display_name=body.display_name)
        db.add(user)
        db.flush()
    e = db.scalar(
        select(Enrollment).where(
            Enrollment.offering_id == m.offering.id, Enrollment.user_id == user.id
        )
    )
    if e is not None and e.role != Role.student:
        raise api_error(
            409, "is_staff", f"{netid} is enrolled as {e.role.value}; remove them from staff first"
        )
    before = {"status": e.status.value} if e else None
    section = roster.section_for(db, m.offering, body.section)
    if e is None:
        e = Enrollment(offering_id=m.offering.id, user_id=user.id, role=Role.student)
        db.add(e)
    e.status = EnrollmentStatus.active
    e.section_id = section.id if section else None
    db.flush()
    audit.record(
        db,
        actor_id=m.user.id,
        offering_id=m.offering.id,
        entity="enrollment",
        entity_id=e.id,
        action="add_student",
        before=before,
        after={"netid": netid, "section": body.section},
    )
    return {"netid": netid, "role": e.role.value, "status": e.status.value}


@router.delete("/offerings/{offering_id}/roster/{netid}")
def drop_enrollment(
    netid: str, m: Membership = Depends(require_instructor), db: Session = Depends(get_db)
):
    """Mark one enrollment dropped, staff included.

    A soft drop, not a delete: submissions reference the enrollment, and the
    grade record of someone who withdraws has to survive them leaving. A later
    import (or add_student) reinstates the same row rather than making a second.
    """
    netid = netid.strip().lower()
    e = db.scalar(
        select(Enrollment)
        .join(User)
        .where(Enrollment.offering_id == m.offering.id, User.netid == netid)
    )
    if e is None:
        raise api_error(404, "not_found", f"{netid} is not enrolled in this offering")
    if e.user_id == m.user.id:
        raise api_error(409, "self_drop", "you cannot remove yourself from an offering")
    if e.role == Role.instructor:
        others = db.scalars(
            select(Enrollment).where(
                Enrollment.offering_id == m.offering.id,
                Enrollment.role == Role.instructor,
                Enrollment.status == EnrollmentStatus.active,
                Enrollment.id != e.id,
            )
        ).all()
        if not others:
            # Otherwise one click locks everyone out of the offering for good.
            raise api_error(409, "last_instructor", "an offering needs at least one instructor")
    before = {"role": e.role.value, "status": e.status.value}
    e.status = EnrollmentStatus.dropped
    db.flush()
    audit.record(
        db,
        actor_id=m.user.id,
        offering_id=m.offering.id,
        entity="enrollment",
        entity_id=e.id,
        action="drop",
        before=before,
        after={"netid": netid, "status": e.status.value},
    )
    return {"netid": netid, "status": e.status.value}
