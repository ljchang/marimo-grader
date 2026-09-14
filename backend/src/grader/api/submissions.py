"""Submissions (immutable attempts), student views of them, and check events."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from grader.auth.deps import (
    Membership,
    api_error,
    current_user,
    membership_for,
    require_member,
)
from grader.config import get_settings
from grader.db import get_db
from grader.models import (
    Artifact,
    AssignmentVersion,
    CheckEvent,
    Enrollment,
    GraderRun,
    Question,
    Role,
    RunKind,
    Submission,
    SubmissionStatus,
    User,
)
from grader.services.artifacts import store
from grader.services.events import Event, bus
from grader.services.grades import final_score
from grader.util import iso

router = APIRouter(tags=["submissions"])


class SubmissionIn(BaseModel):
    assignment_version_id: uuid.UUID
    question_id: str = Field(description="stable qid, e.g. glm-q03")
    notebook: str
    check_results: list[dict[str, Any]] = Field(default_factory=list)
    outputs: dict[str, Any] = Field(default_factory=dict)
    client: dict[str, Any] = Field(default_factory=dict)
    client_submission_id: str | None = Field(default=None, max_length=64)


def _resolve(
    db: Session, user: User, version_id: uuid.UUID, qid: str
) -> tuple[Enrollment, AssignmentVersion, Question]:
    v = db.get(AssignmentVersion, version_id)
    if v is None:
        raise api_error(404, "not_found", "assignment version not found")
    m = membership_for(db, user, v.assignment.offering_id)
    if m is None:
        raise api_error(403, "not_enrolled", "you are not enrolled in this offering")
    # Staff may submit too, so an instructor can exercise their own assignment
    # end to end before students see it. Nothing special marks those attempts:
    # they hang off the submitter's own (instructor or TA) enrollment, and every
    # view that surfaces grades -- the class grid, the attention queue, the
    # Canvas export -- already selects student enrollments only. See is_test().
    return m.enrollment, v, q_of(db, v, qid)


def is_test(sub: Submission) -> bool:
    """True when a submission came from staff exercising the assignment.

    Derived from the enrollment's role rather than stored on the row: there is
    no flag to set, forget to set, or let drift out of step with the roster.
    """
    return sub.enrollment.role != Role.student


def q_of(db: Session, v: AssignmentVersion, qid: str) -> Question:
    """Resolve against the version the submitter actually opened, not the live
    question list: a question dropped in a later version must still accept
    submissions from older copies."""
    q = db.scalar(
        select(Question).where(Question.assignment_id == v.assignment_id, Question.qid == qid)
    )
    snapshot_qids = {x.get("qid") for x in (v.question_snapshot or [])}
    if q is None or (snapshot_qids and qid not in snapshot_qids):
        raise api_error(404, "unknown_question", f"question {qid!r} not in this assignment version")
    return q


def submission_outputs(db: Session, s: Submission) -> dict:
    """Structured answers the widget sent alongside the notebook (e.g. text-area values)."""
    if s.outputs_artifact_id is None:
        return {}
    art = db.get(Artifact, s.outputs_artifact_id)
    if art is None:
        return {}
    try:
        return json.loads(store().get(art).decode("utf-8", "replace"))
    except ValueError:
        return {}


def submission_json(db: Session, s: Submission, *, include_feedback: bool = True) -> dict:
    sc = final_score(db, s)
    out = {
        "id": str(s.id),
        "question_id": str(s.question_id),
        "qid": s.question.qid,
        "assignment_id": str(s.question.assignment_id),
        "assignment_version_id": str(s.assignment_version_id),
        "attempt_no": s.attempt_no,
        "submitted_at": iso(s.submitted_at),
        "status": s.status.value,
        "netid": s.enrollment.user.netid,
        "render_url": f"/api/v1/submissions/{s.id}/render" if s.render_artifact_id else None,
        "notebook_url": f"/api/v1/submissions/{s.id}/notebook",
        "outputs": submission_outputs(db, s),
        "score": None,
    }
    if sc is not None:
        out["score"] = {
            "auto_points": float(sc.auto_points) if sc.auto_points is not None else None,
            "manual_points": float(sc.manual_points) if sc.manual_points is not None else None,
            "total": sc.total,
            "max_points": float(s.question.max_points),
            "rubric_scores": sc.rubric_scores or {},
            "feedback": sc.feedback if include_feedback else None,
            "is_final": sc.is_final,
            "graded_at": iso(sc.graded_at),
        }
    return out


def created_json(sub: Submission, *, duplicate: bool = False) -> dict:
    version = sub.version
    latest = version.assignment.versions[-1] if version.assignment.versions else version
    return {
        "id": str(sub.id),
        "attempt_no": sub.attempt_no,
        "submitted_at": iso(sub.submitted_at),
        "status": sub.status.value,
        "version": version.version,
        "latest_version": latest.version,
        "stale": latest.version > version.version,
        "duplicate": duplicate,
        # Staff attempt: graded and returned, but never recorded as a grade.
        "test": is_test(sub),
    }


@router.post("/submissions", status_code=201)
def create_submission(
    body: SubmissionIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    s = get_settings()
    nb = body.notebook.encode()
    if len(nb) > s.max_notebook_bytes:
        raise api_error(413, "too_large", f"notebook exceeds {s.max_notebook_bytes} bytes")
    enrollment, version, question = _resolve(db, user, body.assignment_version_id, body.question_id)

    if body.client_submission_id:
        existing = db.scalar(
            select(Submission).where(
                Submission.enrollment_id == enrollment.id,
                Submission.question_id == question.id,
                Submission.client_submission_id == body.client_submission_id,
            )
        )
        if existing is not None:
            return created_json(existing, duplicate=True)

    settings = version.assignment.settings or {}
    allowed = settings.get("attempts_allowed")
    n_prev = (
        db.scalar(
            select(func.count(Submission.id)).where(
                Submission.enrollment_id == enrollment.id, Submission.question_id == question.id
            )
        )
        or 0
    )
    if allowed is not None and n_prev >= int(allowed):
        raise api_error(
            409, "attempts_exhausted", f"{allowed} attempt(s) allowed for this question"
        )

    st = store()
    nb_art = st.put(db, nb, kind="notebook", content_type="text/x-python")
    out_art = None
    if body.outputs:
        raw = json.dumps(body.outputs).encode()
        if len(raw) > s.max_outputs_bytes:
            raise api_error(413, "too_large", "outputs too large")
        out_art = st.put(db, raw, kind="outputs", content_type="application/json")

    sub = Submission(
        enrollment_id=enrollment.id,
        assignment_version_id=version.id,
        question_id=question.id,
        attempt_no=n_prev + 1,
        notebook_artifact_id=nb_art.id,
        outputs_artifact_id=out_art.id if out_art else None,
        client_check_results=body.check_results[:200],
        client_meta={k: str(v)[:120] for k, v in body.client.items()},
        client_submission_id=body.client_submission_id,
    )
    db.add(sub)
    db.flush()
    db.add(GraderRun(submission_id=sub.id, kind=RunKind.autograde))
    db.add(GraderRun(submission_id=sub.id, kind=RunKind.render))
    db.flush()
    bus.publish(
        Event(
            version.assignment.offering_id,
            "submission.received",
            {"submission_id": str(sub.id), "question_id": str(question.id), "netid": user.netid},
        )
    )
    return created_json(sub)


def _load_visible(db: Session, user: User, submission_id: uuid.UUID) -> Submission:
    sub = db.get(Submission, submission_id)
    if sub is None:
        raise api_error(404, "not_found", "submission not found")
    if sub.enrollment.user_id == user.id:
        return sub
    m = membership_for(db, user, sub.enrollment.offering_id)
    if m is None or not m.is_staff() or not m.can_see_section(sub.enrollment.section_id):
        raise api_error(404, "not_found", "submission not found")
    return sub


@router.get("/submissions/{submission_id}")
def get_submission(
    submission_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    sub = _load_visible(db, user, submission_id)
    out = submission_json(db, sub)
    out["client_check_results"] = sub.client_check_results
    out["runs"] = [
        {
            "kind": r.kind.value,
            "status": r.status.value,
            "error": r.error,
            "results": r.results,
            "finished_at": iso(r.finished_at),
        }
        for r in sub.runs
    ]
    return out


_INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)


def _inline_script_hashes(html: str) -> list[str]:
    """CSP hashes for the inline scripts marimo's export uses to mount its viewer."""
    out = []
    for body in _INLINE_SCRIPT.findall(html):
        digest = hashlib.sha256(body.encode("utf-8")).digest()
        out.append("'sha256-" + base64.b64encode(digest).decode() + "'")
    return out


@router.get("/submissions/{submission_id}/render")
def get_render(
    submission_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    sub = _load_visible(db, user, submission_id)
    if sub.render_artifact_id is None:
        raise api_error(404, "not_rendered", "render not available yet")
    art = db.get(Artifact, sub.render_artifact_id)
    assert art is not None
    html = store().get(art)
    # marimo's exported HTML embeds the outputs as data and renders them with marimo's
    # viewer bundle from jsDelivr. Student code never runs here. Only that pinned CDN
    # and the export's own inline mount scripts (by hash) are allowed, and the
    # document is sandboxed so it has no origin, cookies, or access to the parent.
    scripts = " ".join(
        ["https://cdn.jsdelivr.net", *_inline_script_hashes(html.decode("utf-8", "replace"))]
    )
    csp = (
        "default-src 'none'; "
        f"script-src {scripts}; "
        "style-src 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src data: blob: https://cdn.jsdelivr.net; "
        "font-src data: https://cdn.jsdelivr.net; "
        "connect-src https://cdn.jsdelivr.net; "
        "worker-src blob:; form-action 'none'; base-uri 'none'; sandbox allow-scripts"
    )
    return Response(
        content=html,
        media_type="text/html",
        headers={"Content-Security-Policy": csp, "X-Frame-Options": "SAMEORIGIN"},
    )


@router.get("/submissions/{submission_id}/notebook")
def get_notebook(
    submission_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    sub = _load_visible(db, user, submission_id)
    art = db.get(Artifact, sub.notebook_artifact_id)
    assert art is not None
    return Response(content=store().get(art), media_type="text/x-python")


@router.get("/offerings/{offering_id}/me/submissions")
def my_submissions(
    assignment_id: uuid.UUID | None = None,
    m: Membership = Depends(require_member),
    db: Session = Depends(get_db),
):
    stmt = select(Submission).where(Submission.enrollment_id == m.enrollment.id)
    if assignment_id is not None:
        stmt = stmt.join(Question).where(Question.assignment_id == assignment_id)
    subs = db.scalars(stmt.order_by(Submission.submitted_at)).all()
    return [submission_json(db, s) for s in subs]


class CheckEventIn(BaseModel):
    assignment_version_id: uuid.UUID
    question_id: str
    check_key: str = Field(max_length=120)
    passed: bool


@router.post("/check-events", status_code=202)
def check_event(
    body: CheckEventIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    try:
        enrollment, version, question = _resolve(
            db, user, body.assignment_version_id, body.question_id
        )
    except Exception:  # noqa: BLE001 - best effort, never break a notebook over telemetry
        return {"ok": False}
    if not (version.assignment.settings or {}).get("log_checks", True):
        return {"ok": False}
    db.add(
        CheckEvent(
            enrollment_id=enrollment.id,
            question_id=question.id,
            check_key=body.check_key,
            passed=body.passed,
        )
    )
    return {"ok": True}


def mark_status(db: Session, sub: Submission, status: SubmissionStatus) -> None:
    """Used by the worker; the only mutation submissions ever receive."""
    sub.status = status
    db.flush()
