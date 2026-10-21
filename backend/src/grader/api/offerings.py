"""Offerings, assignments, versions, and the student notebook download."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from grader.auth.deps import (
    Membership,
    api_error,
    current_user,
    effective_role,
    membership_for,
    previewing,
    require_instructor,
    require_member,
)
from grader.config import get_settings
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
    Rubric,
    User,
    new_id,
)
from grader.services import audit, availability, notebook_submission, student_copy
from grader.services.artifacts import store
from grader.services.grades import POLICIES
from grader.services.notebook_meta import inject_grader_keys, leaked_markers
from grader.util import iso

router = APIRouter(tags=["offerings"])

DEFAULT_SETTINGS: dict[str, Any] = {
    # Who may fetch the student notebook, and when: see services/availability.py.
    "visibility": "public",
    "release_at": None,
    "due_at": None,
    "close_at": None,
    "late_policy": None,
    "attempts_allowed": None,
    "grade_policy": "latest",
    "environments": ["molab"],
    "log_checks": True,
    "canvas_assignment_id": None,
    "required_datasets": [],
    # False: submissions are stored and rendered but never run against the checks.
    "autograde": True,
    # False: no `marimo export html` re-run either. For notebooks too heavy for the
    # worker (a group analysis); the grading view shows the code and the files the
    # student saved under storage.private()/<slug>/ instead.
    "render": True,
    # One extra question that takes the whole notebook (services/notebook_submission.py).
    "notebook_submission": False,
    "notebook_points": 0,
    # Seconds the worker gives `marimo export html`; None means the deployment default.
    "render_timeout": None,
}


def _offering_json(o: Offering, e: Enrollment | None) -> dict:
    return {
        "id": str(o.id),
        "offering_id": str(o.id),
        "course_slug": o.course.slug,
        "course_title": o.course.title,
        "term": o.term,
        "title": o.title,
        "role": effective_role(e).value if e else None,
        # Staff in student preview: `role` says student, this says who they are.
        "staff_role": e.role.value if e and e.role != Role.student else None,
        "preview": previewing(e) if e else False,
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


def assignment_json(a: Assignment, preview: bool = False) -> dict:
    latest = a.versions[-1] if a.versions else None
    return {
        "id": str(a.id),
        "slug": a.slug,
        "title": a.title,
        "settings": {**DEFAULT_SETTINGS, **(a.settings or {})},
        "availability": availability.json_for(a, datetime.now(UTC), preview),
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
    return [_offering_json(e.offering, e) for e in rows]


@router.get("/offerings/{offering_id}")
def get_offering(m: Membership = Depends(require_member)):
    return _offering_json(m.offering, m.enrollment)


class PreviewIn(BaseModel):
    on: bool


@router.put("/offerings/{offering_id}/preview")
def set_preview(
    offering_id: uuid.UUID,
    body: PreviewIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Switch a staff member's own view of the offering to a student's and back.

    Checked against the enrollment's own role, not the effective one, so the
    way out of preview is never itself a staff page that preview refuses.
    """
    m = membership_for(db, user, offering_id)
    if m is None:
        raise api_error(404, "not_found", "offering not found")
    if m.enrollment.role == Role.student:
        raise api_error(403, "forbidden", "student preview is for course staff")
    before = {"preview_student": bool(m.enrollment.preview_student)}
    m.enrollment.preview_student = body.on
    db.flush()
    audit.record(
        db,
        actor_id=user.id,
        offering_id=offering_id,
        entity="enrollment",
        entity_id=m.enrollment.id,
        action="preview",
        before=before,
        after={"preview_student": body.on},
    )
    return _offering_json(m.offering, m.enrollment)


@router.get("/offerings/{offering_id}/assignments")
def list_assignments(m: Membership = Depends(require_member), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Assignment)
        .where(Assignment.offering_id == m.offering.id)
        .order_by(Assignment.created_at)
    ).all()
    if not m.is_staff():
        # A private assignment is not announced before it opens: an exam being
        # built is invisible to the class (see services/availability.py).
        now = datetime.now(UTC)
        rows = [
            a
            for a in rows
            if not (
                availability.is_private(a)
                and availability.Window.of(a).state(now, m.previewing) == "upcoming"
            )
        ]
    return [assignment_json(a, m.previewing) for a in rows]


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
    if merged["visibility"] not in availability.VISIBILITIES:
        raise api_error(
            422, "bad_visibility", f"visibility must be one of {availability.VISIBILITIES}"
        )
    if merged["late_policy"] not in availability.LATE_POLICIES:
        raise api_error(422, "bad_late_policy", "late_policy must be null, 'accept' or 'reject'")
    when: dict[str, datetime] = {}
    for key in ("release_at", "due_at", "close_at"):
        try:
            if (dt := availability.parse(merged[key])) is not None:
                when[key] = dt
                merged[key] = dt.isoformat()
        except (TypeError, ValueError) as e:
            raise api_error(422, "bad_date", f"{key} must be an ISO 8601 timestamp") from e
    order = [k for k in ("release_at", "due_at", "close_at") if k in when]
    for first, then in zip(order, order[1:], strict=False):
        # A deadline may coincide with the close; nothing may run backwards.
        if when[then] < when[first] or (first == "release_at" and when[then] == when[first]):
            raise api_error(422, "bad_window", f"{first} must come before {then}")
    for key in ("autograde", "render", "notebook_submission"):
        if not isinstance(merged[key], bool):
            raise api_error(422, f"bad_{key}", f"{key} must be true or false")
    try:
        if float(merged["notebook_points"] or 0) < 0:
            raise ValueError
    except (TypeError, ValueError) as e:
        raise api_error(422, "bad_points", "notebook_points must be a number >= 0") from e
    rt = merged["render_timeout"]
    if rt is not None and not (isinstance(rt, int) and 30 <= rt <= 3600):
        raise api_error(422, "bad_timeout", "render_timeout must be 30-3600 seconds or null")
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
    notebook_submission.sync(db, a)
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


@router.get("/offerings/{offering_id}/assignments/{assignment_id}/versions")
def list_versions(
    assignment_id: uuid.UUID,
    m: Membership = Depends(require_instructor),
    db: Session = Depends(get_db),
):
    """Every published version, newest first, for the assignment's detail page."""
    a = db.get(Assignment, assignment_id)
    if a is None or a.offering_id != m.offering.id:
        raise api_error(404, "not_found", "assignment not found")
    return [
        {
            "id": str(v.id),
            "version": v.version,
            "created_at": iso(v.created_at),
            "published_by": (u.netid if (u := db.get(User, v.published_by)) else None),
            "questions": [q.get("qid") for q in (v.question_snapshot or [])],
            "student_url": f"/api/v1/assignment-versions/{v.id}/student.py",
        }
        for v in sorted(a.versions, key=lambda v: v.version, reverse=True)
    ]


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
        settings = _validate_settings({**(a.settings or {}), **body.settings})
        nb = next((q for q in a.questions if q.qid == notebook_submission.NOTEBOOK_QID), None)
        if (
            nb is not None
            and nb.rubric is not None
            and settings["notebook_submission"]
            and abs(float(settings["notebook_points"] or 0) - rubric_total(nb.rubric)) > 1e-9
        ):
            raise api_error(
                422,
                "points_set_by_rubric",
                f"The notebook is worth what its rubric adds up to "
                f"({rubric_total(nb.rubric):g}); change the rubric instead",
            )
        a.settings = settings
        notebook_submission.sync(db, a)
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


class RubricItemIn(BaseModel):
    key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
    label: str = Field(min_length=1, max_length=300)
    points: float = Field(gt=0)
    group: str | None = Field(default=None, max_length=200)


class RubricIn(BaseModel):
    items: list[RubricItemIn] = Field(max_length=200)
    reason: str | None = None


def rubric_total(r: Rubric) -> float:
    return sum(float(i.get("points") or 0) for i in r.items or [])


def _rubric_json(q: Question) -> dict:
    r = q.rubric
    return {
        "question_id": str(q.id),
        "items": list(r.items) if r else [],
        "total": rubric_total(r) if r else 0,
    }


def _staff_question(db: Session, m: Membership, question_id: uuid.UUID) -> Question:
    q = db.get(Question, question_id)
    if q is None or q.assignment.offering_id != m.offering.id:
        raise api_error(404, "not_found", "question not found")
    return q


@router.get("/offerings/{offering_id}/questions/{question_id}/rubric")
def get_rubric(
    question_id: uuid.UUID,
    m: Membership = Depends(require_instructor),
    db: Session = Depends(get_db),
):
    return _rubric_json(_staff_question(db, m, question_id))


@router.put("/offerings/{offering_id}/questions/{question_id}/rubric")
def put_rubric(
    question_id: uuid.UUID,
    body: RubricIn,
    m: Membership = Depends(require_instructor),
    db: Session = Depends(get_db),
):
    """Replace a question's rubric; an empty list removes it.

    Items are scored one by one in the grading queue and their scores add up to
    the manual points. The whole-notebook question takes its points from the
    rubric; any other question's rubric has to fit in its manual points.
    """
    q = _staff_question(db, m, question_id)
    a = q.assignment
    keys = [i.key for i in body.items]
    if len(set(keys)) != len(keys):
        raise api_error(422, "duplicate_key", "rubric item keys must be unique")
    items = [i.model_dump(exclude_none=True) for i in body.items]
    total = sum(i.points for i in body.items)
    is_notebook = q.qid == notebook_submission.NOTEBOOK_QID
    manual_max = float(q.max_points) - float(q.auto_points_max)
    if items and not is_notebook and total > manual_max + 1e-9:
        raise api_error(
            422,
            "rubric_over",
            f"the rubric adds up to {total:g}, more than the {manual_max:g} manual points",
        )
    before = list(q.rubric.items) if q.rubric else []
    if items:
        if q.rubric is None:
            q.rubric = Rubric(offering_id=m.offering.id, name=f"{a.title}: {q.title}", items=items)
        else:
            q.rubric.items = items
        if is_notebook:
            a.settings = {**(a.settings or {}), "notebook_points": total}
            notebook_submission.sync(db, a)
    elif q.rubric is not None:
        old, q.rubric = q.rubric, None
        db.delete(old)
    db.flush()
    audit.record(
        db,
        actor_id=m.user.id,
        offering_id=m.offering.id,
        entity="rubric",
        entity_id=q.id,
        action="update",
        before={"items": before},
        after={"items": items},
        reason=body.reason,
    )
    return _rubric_json(q)


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
    """Publish a new immutable version.

    The server finalizes the student notebook: it injects the ``grader-*`` keys (server,
    course/term, slug, ids, version) into the PEP 723 block and stores exactly those bytes.
    Publishing the same instructor notebook and question list twice is a no-op (200,
    ``unchanged: true``) so CI can re-run safely.
    """
    a = db.get(Assignment, assignment_id)
    if a is None or a.offering_id != m.offering.id:
        raise api_error(404, "not_found", "assignment not found")
    try:
        qs = [QuestionIn.model_validate(q) for q in json.loads(questions)]
        client_hashes = json.loads(cell_hashes)
    except (ValueError, TypeError) as e:
        raise api_error(422, "bad_json", f"questions/cell_hashes must be JSON: {e}") from e
    inst_bytes = await instructor_notebook.read()
    student_text = (await student_notebook.read()).decode("utf-8", "replace")
    return _publish(db, m, a, inst_bytes, student_text, qs, client_hashes)


def _build(a: Assignment, upload: UploadFile, inst_bytes: bytes) -> tuple[str, list[QuestionIn]]:
    """What ``grader publish`` makes from an instructor notebook, made here."""
    text = inst_bytes.decode("utf-8", "replace")
    try:
        student = student_copy.generate_student(text, upload.filename or "notebook.py")
        raw = student_copy.questions_from(text, optional=notebook_submission.enabled(a))
    except student_copy.BuildError as e:
        raise api_error(422, e.code, e.message) from e
    return student, [QuestionIn.model_validate(q) for q in raw]


@router.post("/offerings/{offering_id}/assignments/{assignment_id}/versions/preview")
async def preview_version(
    assignment_id: uuid.UUID,
    instructor_notebook: UploadFile = File(...),
    m: Membership = Depends(require_instructor),
    db: Session = Depends(get_db),
):
    """What publishing this instructor notebook would do, without doing it: the
    questions it defines, how they differ from the live ones, and the student
    copy. Refuses (422) exactly where publishing would."""
    a = db.get(Assignment, assignment_id)
    if a is None or a.offering_id != m.offering.id:
        raise api_error(404, "not_found", "assignment not found")
    inst_bytes = await instructor_notebook.read()
    student, qs = _build(a, instructor_notebook, inst_bytes)
    _check_questions(a, qs)
    payload = [q.model_dump(mode="json") for q in qs]
    latest = a.versions[-1] if a.versions else None
    unchanged = bool(
        latest
        and (latest.cell_hashes or {}).get("publish_fingerprint")
        == _fingerprint(inst_bytes, payload)
    )
    live = {q.qid: q for q in a.questions if q.active and q.qid != notebook_submission.NOTEBOOK_QID}
    new = {q.qid: q for q in qs}
    changed = []
    for qid, q in new.items():
        old = live.get(qid)
        if old is None:
            continue
        what = []
        if float(old.max_points) != q.max_points:
            what.append(f"points {float(old.max_points):g} → {q.max_points:g}")
        if old.grading_mode != q.grading_mode:
            what.append(f"graded {old.grading_mode.value} → {q.grading_mode.value}")
        if old.title != q.title:
            what.append("title")
        if what:
            changed.append({"qid": qid, "what": what})
    return {
        "unchanged": unchanged,
        "version": latest.version
        if unchanged and latest
        else (latest.version + 1 if latest else 1),
        "questions": payload,
        "added": [qid for qid in new if qid not in live],
        "removed": [qid for qid in live if qid not in new],
        "changed": changed,
        "student_notebook": student,
    }


@router.post(
    "/offerings/{offering_id}/assignments/{assignment_id}/versions/from-notebook",
    status_code=201,
)
async def publish_from_notebook(
    assignment_id: uuid.UUID,
    instructor_notebook: UploadFile = File(...),
    m: Membership = Depends(require_instructor),
    db: Session = Depends(get_db),
):
    """Publish from the instructor notebook alone, as ``grader publish`` does."""
    a = db.get(Assignment, assignment_id)
    if a is None or a.offering_id != m.offering.id:
        raise api_error(404, "not_found", "assignment not found")
    inst_bytes = await instructor_notebook.read()
    student, qs = _build(a, instructor_notebook, inst_bytes)
    return _publish(db, m, a, inst_bytes, student, qs, {})


def _check_questions(a: Assignment, qs: list[QuestionIn]) -> None:
    if any(q.qid == notebook_submission.NOTEBOOK_QID for q in qs):
        raise api_error(
            422,
            "reserved_qid",
            f"{notebook_submission.NOTEBOOK_QID!r} is reserved for whole-notebook submission",
        )
    if not qs and not notebook_submission.enabled(a):
        raise api_error(
            422,
            "no_questions",
            "at least one question is required (or turn on notebook_submission)",
        )


def _fingerprint(inst_bytes: bytes, question_payload: list[dict]) -> str:
    # Titles are presentation only: changing one updates the question in place and
    # does not create a new version.
    structural = [{k: v for k, v in q.items() if k != "title"} for q in question_payload]
    return hashlib.sha256(inst_bytes + json.dumps(structural, sort_keys=True).encode()).hexdigest()


def _publish(
    db: Session,
    m: Membership,
    a: Assignment,
    inst_bytes: bytes,
    student_text: str,
    qs: list[QuestionIn],
    client_hashes: dict,
):
    _check_questions(a, qs)
    leaked = leaked_markers(student_text)
    if leaked:
        raise api_error(
            422, "solution_leak", f"student notebook still contains {', '.join(leaked)}"
        )

    course, term = a.offering.course.slug, a.offering.term
    question_payload = [q.model_dump(mode="json") for q in qs]
    fingerprint = _fingerprint(inst_bytes, question_payload)
    if a.versions:
        latest = a.versions[-1]
        if (latest.cell_hashes or {}).get("publish_fingerprint") == fingerprint:
            by_qid = {q.qid: q for q in a.questions}
            for qi in qs:
                if qi.qid in by_qid and by_qid[qi.qid].title != qi.title:
                    by_qid[qi.qid].title = qi.title
            db.flush()
            return JSONResponse(
                {
                    "id": str(latest.id),
                    "version": latest.version,
                    "unchanged": True,
                    "student_url": f"{get_settings().base_url}/a/{course}/{term}/{a.slug}/student.py",
                    "download_url": f"{get_settings().base_url}/a/{course}/{term}/{a.slug}/student.py?v={latest.version}",
                    "assignment": assignment_json(a),
                },
                status_code=200,
            )

    st = store()
    inst = st.put(db, inst_bytes, kind="notebook", content_type="text/x-python")

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
    notebook_submission.sync(db, a)

    version_no = (a.versions[-1].version + 1) if a.versions else 1
    version_id = new_id()
    final_text = inject_grader_keys(
        student_text,
        server=get_settings().base_url,
        course=course,
        term=term,
        offering_id=str(a.offering_id),
        assignment=a.slug,
        assignment_id=str(a.id),
        assignment_version=str(version_id),
        version=str(version_no),
    )
    final_bytes = final_text.encode()
    stud = st.put(db, final_bytes, kind="notebook", content_type="text/x-python")
    mograder_hashes = re.search(r'^# mograder-cell-hashes = "([^"]*)"', final_text, re.M)
    v = AssignmentVersion(
        id=version_id,
        assignment_id=a.id,
        version=version_no,
        instructor_artifact_id=inst.id,
        student_artifact_id=stud.id,
        cell_hashes={
            "publish_fingerprint": fingerprint,
            "student_sha256": hashlib.sha256(final_bytes).hexdigest(),
            "mograder_cells": mograder_hashes.group(1).split(",") if mograder_hashes else [],
            **({"client": client_hashes} if client_hashes else {}),
        },
        question_snapshot=question_payload,
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
        after={"version": version_no, "questions": [q.qid for q in qs]},
    )
    base = f"{get_settings().base_url}/a/{course}/{term}/{a.slug}"
    return {
        "id": str(v.id),
        "version": version_no,
        "unchanged": False,
        "student_url": f"{base}/student.py",
        "download_url": f"{base}/student.py?v={version_no}",
        "molab_url": f"{base}/molab",
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
    reason = availability.fetch_refusal(db, user, v.assignment, datetime.now(UTC))
    if reason == "not_found":
        raise api_error(404, "not_found", "version not found")
    if reason is not None:
        raise api_error(
            403, "not_released" if reason == "upcoming" else reason, f"assignment {reason}"
        )
    from grader.models import Artifact

    art = db.get(Artifact, v.student_artifact_id)
    assert art is not None
    return Response(
        content=store().get(art),
        media_type="text/x-python",
        headers={"Content-Disposition": f'inline; filename="{v.assignment.slug}.py"'},
    )
