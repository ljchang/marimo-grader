"""Offerings, assignments, versions, and the student notebook download."""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from grader.auth.deps import (
    Membership,
    api_error,
    current_user,
    membership_for,
    require_instructor,
    require_member,
)
from grader.db import get_db
from grader.models import (
    Assignment,
    AssignmentVersion,
    Enrollment,
    EnrollmentStatus,
    GradingMode,
    Offering,
    Question,
    Role,
    User,
)
from grader.services import audit
from grader.services.artifacts import store
from grader.services.grades import POLICIES

router = APIRouter(tags=["offerings"])

DEFAULT_SETTINGS: dict[str, Any] = {
    "due_at": None,
    "late_policy": None,
    "attempts_allowed": None,
    "grade_policy": "latest",
    "environments": ["molab"],
    "log_checks": True,
    "canvas_assignment_id": None,
    "required_datasets": [],
}


def _offering_json(o: Offering, role: Role | None) -> dict:
    return {
        "id": str(o.id),
        "offering_id": str(o.id),
        "course_slug": o.course.slug,
        "course_title": o.course.title,
        "term": o.term,
        "title": o.title,
        "role": role.value if role else None,
        "settings": o.settings or {},
        "sections": [{"id": str(s.id), "name": s.name} for s in o.sections],
    }


def _question_json(q: Question) -> dict:
    return {
        "id": str(q.id),
        "qid": q.qid,
        "title": q.title,
        "order": q.order,
        "max_points": float(q.max_points),
        "auto_points_max": float(q.auto_points_max),
        "grading_mode": q.grading_mode.value,
        "check_keys": q.check_keys or [],
        "rubric_id": str(q.rubric_id) if q.rubric_id else None,
        "active": q.active,
    }


def assignment_json(a: Assignment) -> dict:
    latest = a.versions[-1] if a.versions else None
    return {
        "id": str(a.id),
        "slug": a.slug,
        "title": a.title,
        "settings": {**DEFAULT_SETTINGS, **(a.settings or {})},
        "latest_version": latest.version if latest else None,
        "latest_version_id": str(latest.id) if latest else None,
        "questions": [_question_json(q) for q in a.questions if q.active],
    }


@router.get("/offerings")
def list_offerings(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Enrollment).where(
            Enrollment.user_id == user.id, Enrollment.status == EnrollmentStatus.active
        )
    ).all()
    return [_offering_json(e.offering, e.role) for e in rows]


@router.get("/offerings/{offering_id}")
def get_offering(m: Membership = Depends(require_member)):
    return _offering_json(m.offering, m.role)


@router.get("/offerings/{offering_id}/assignments")
def list_assignments(m: Membership = Depends(require_member), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Assignment)
        .where(Assignment.offering_id == m.offering.id)
        .order_by(Assignment.created_at)
    ).all()
    return [assignment_json(a) for a in rows]


class AssignmentIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    title: str
    settings: dict[str, Any] = Field(default_factory=dict)


class AssignmentPatch(BaseModel):
    title: str | None = None
    settings: dict[str, Any] | None = None
    reason: str | None = None


def _validate_settings(settings: dict[str, Any]) -> dict[str, Any]:
    merged = {**DEFAULT_SETTINGS, **settings}
    if merged["grade_policy"] not in POLICIES:
        raise api_error(422, "bad_policy", f"grade_policy must be one of {POLICIES}")
    if merged["attempts_allowed"] is not None and int(merged["attempts_allowed"]) < 1:
        raise api_error(422, "bad_attempts", "attempts_allowed must be >= 1 or null")
    return merged


@router.post("/offerings/{offering_id}/assignments", status_code=201)
def create_assignment(
    body: AssignmentIn, m: Membership = Depends(require_instructor), db: Session = Depends(get_db)
):
    if db.scalar(
        select(Assignment).where(
            Assignment.offering_id == m.offering.id, Assignment.slug == body.slug
        )
    ):
        raise api_error(409, "exists", "an assignment with that slug exists")
    a = Assignment(
        offering_id=m.offering.id,
        slug=body.slug,
        title=body.title,
        settings=_validate_settings(body.settings),
    )
    db.add(a)
    db.flush()
    audit.record(
        db,
        actor_id=m.user.id,
        offering_id=m.offering.id,
        entity="assignment",
        entity_id=a.id,
        action="create",
        after={"slug": a.slug, "settings": a.settings},
    )
    return assignment_json(a)


@router.patch("/offerings/{offering_id}/assignments/{assignment_id}")
def patch_assignment(
    assignment_id: uuid.UUID,
    body: AssignmentPatch,
    m: Membership = Depends(require_instructor),
    db: Session = Depends(get_db),
):
    a = db.get(Assignment, assignment_id)
    if a is None or a.offering_id != m.offering.id:
        raise api_error(404, "not_found", "assignment not found")
    before = {"title": a.title, "settings": a.settings}
    if body.title is not None:
        a.title = body.title
    if body.settings is not None:
        a.settings = _validate_settings({**(a.settings or {}), **body.settings})
    audit.record(
        db,
        actor_id=m.user.id,
        offering_id=m.offering.id,
        entity="assignment",
        entity_id=a.id,
        action="update",
        before=before,
        after={"title": a.title, "settings": a.settings},
        reason=body.reason,
    )
    return assignment_json(a)


class QuestionIn(BaseModel):
    qid: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    title: str
    max_points: float = 1
    auto_points_max: float | None = None
    grading_mode: GradingMode = GradingMode.auto
    check_keys: list[str] = Field(default_factory=list)


@router.post("/offerings/{offering_id}/assignments/{assignment_id}/versions", status_code=201)
async def publish_version(
    assignment_id: uuid.UUID,
    instructor_notebook: UploadFile = File(...),
    student_notebook: UploadFile = File(...),
    questions: str = Form(...),
    cell_hashes: str = Form("{}"),
    m: Membership = Depends(require_instructor),
    db: Session = Depends(get_db),
):
    a = db.get(Assignment, assignment_id)
    if a is None or a.offering_id != m.offering.id:
        raise api_error(404, "not_found", "assignment not found")
    try:
        qs = [QuestionIn.model_validate(q) for q in json.loads(questions)]
        hashes = json.loads(cell_hashes)
    except (ValueError, TypeError) as e:
        raise api_error(422, "bad_json", f"questions/cell_hashes must be JSON: {e}") from e
    if not qs:
        raise api_error(422, "no_questions", "at least one question is required")

    st = store()
    inst = st.put(
        db, await instructor_notebook.read(), kind="notebook", content_type="text/x-python"
    )
    stud = st.put(db, await student_notebook.read(), kind="notebook", content_type="text/x-python")

    # Upsert questions by stable qid; deactivate ones no longer present.
    existing = {q.qid: q for q in a.questions}
    seen = set()
    for i, qi in enumerate(qs):
        seen.add(qi.qid)
        auto_max = qi.auto_points_max
        if auto_max is None:
            auto_max = qi.max_points if qi.grading_mode == GradingMode.auto else 0
        q = existing.get(qi.qid)
        if q is None:
            q = Question(assignment_id=a.id, qid=qi.qid)
            db.add(q)
        q.title, q.order, q.max_points = qi.title, i, qi.max_points
        q.auto_points_max, q.grading_mode, q.check_keys, q.active = (
            auto_max,
            qi.grading_mode,
            qi.check_keys,
            True,
        )
    for qid, q in existing.items():
        if qid not in seen:
            q.active = False
    db.flush()

    version = (a.versions[-1].version + 1) if a.versions else 1
    v = AssignmentVersion(
        assignment_id=a.id,
        version=version,
        instructor_artifact_id=inst.id,
        student_artifact_id=stud.id,
        cell_hashes=hashes,
        question_snapshot=[q.model_dump(mode="json") for q in qs],
        published_by=m.user.id,
    )
    db.add(v)
    db.flush()
    db.refresh(a)
    audit.record(
        db,
        actor_id=m.user.id,
        offering_id=m.offering.id,
        entity="assignment_version",
        entity_id=v.id,
        action="publish",
        after={"version": version, "questions": [q.qid for q in qs]},
    )
    return {
        "id": str(v.id),
        "version": version,
        "student_url": f"/api/v1/assignment-versions/{v.id}/student.py",
        "assignment": assignment_json(a),
    }


@router.get("/assignment-versions/{version_id}/student.py")
def student_notebook(
    version_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    v = db.get(AssignmentVersion, version_id)
    if v is None:
        raise api_error(404, "not_found", "version not found")
    offering = v.assignment.offering
    public = bool((offering.settings or {}).get("public_student_notebooks"))
    if not public and membership_for(db, user, offering.id) is None:
        raise api_error(404, "not_found", "version not found")
    from grader.models import Artifact

    art = db.get(Artifact, v.student_artifact_id)
    assert art is not None
    return Response(
        content=store().get(art),
        media_type="text/x-python",
        headers={"Content-Disposition": f'inline; filename="{v.assignment.slug}.py"'},
    )
