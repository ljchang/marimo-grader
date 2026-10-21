"""Staff views: triage, roster grid, grading queue, scoring, student history, SSE, Canvas export."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from grader.api.offerings import assignment_json
from grader.api.submissions import submission_json
from grader.auth.deps import (
    Membership,
    api_error,
    current_user,
    membership_for,
    require_instructor,
    require_member,
    require_staff,
)
from grader.db import get_db
from grader.models import (
    Artifact,
    Assignment,
    CheckEvent,
    Enrollment,
    EnrollmentStatus,
    GradeAudit,
    GraderRun,
    GradingMode,
    Question,
    QuestionGrade,
    Role,
    RosterUpload,
    RunKind,
    RunStatus,
    Score,
    Submission,
    SubmissionStatus,
    User,
)
from grader.services import audit, failures, progress
from grader.services.artifacts import store
from grader.services.canvas_export import build_canvas_csv, header_for
from grader.services.events import Event, bus
from grader.services.grades import (
    cell_state,
    final_score,
    recompute_question_grade,
    submissions_for,
)
from grader.util import iso

router = APIRouter(tags=["grading"])


def _students(db: Session, m: Membership) -> list[Enrollment]:
    rows = db.scalars(
        select(Enrollment)
        .join(User)
        .where(
            Enrollment.offering_id == m.offering.id,
            Enrollment.role == Role.student,
            Enrollment.status == EnrollmentStatus.active,
        )
        .order_by(User.netid)
    ).all()
    return [e for e in rows if m.can_see_section(e.section_id)]


def _needs_manual(db: Session, sub: Submission) -> bool:
    if sub.question.grading_mode == GradingMode.auto:
        return False
    sc = final_score(db, sub)
    return sc is None or not sc.is_final


@router.get("/offerings/{offering_id}/triage")
def triage(m: Membership = Depends(require_staff), db: Session = Depends(get_db)):
    students = _students(db, m)
    enr_ids = [e.id for e in students]
    now = datetime.now(UTC)

    # Awaiting manual grading: latest attempt per (enrollment, question) that has no final score.
    awaiting: dict[uuid.UUID, dict] = {}
    inactive: list[dict] = []
    for e in students:
        last = db.scalar(
            select(func.max(Submission.submitted_at)).where(Submission.enrollment_id == e.id)
        )
        last_check = db.scalar(
            select(func.max(CheckEvent.at)).where(CheckEvent.enrollment_id == e.id)
        )
        last_any = max([d for d in (last, last_check) if d is not None], default=None)
        if last_any is not None and last_any.tzinfo is None:
            last_any = last_any.replace(tzinfo=UTC)
        if last_any is None or last_any < now - timedelta(days=7):
            inactive.append(
                {
                    "netid": e.user.netid,
                    "display_name": e.user.name,
                    "last_activity": iso(last_any),
                }
            )
    questions = db.scalars(
        select(Question)
        .join(Assignment)
        .where(Assignment.offering_id == m.offering.id, Question.active)
    ).all()
    for q in questions:
        if q.grading_mode == GradingMode.auto:
            continue
        for e in students:
            subs = submissions_for(db, e.id, q.id)
            if subs and _needs_manual(db, subs[-1]):
                a = awaiting.setdefault(
                    q.id,
                    {
                        "question_id": str(q.id),
                        "qid": q.qid,
                        "title": q.title,
                        "assignment_id": str(q.assignment_id),
                        "count": 0,
                        "oldest_submitted_at": None,
                    },
                )
                a["count"] += 1
                ts = iso(subs[-1].submitted_at)
                if a["oldest_submitted_at"] is None or ts < a["oldest_submitted_at"]:
                    a["oldest_submitted_at"] = ts

    # Failing checks in the last 48 h, by (question, check_key), latest event per student.
    failing: list[dict] = []
    if enr_ids:
        since = now - timedelta(hours=48)
        events = db.scalars(
            select(CheckEvent)
            .where(CheckEvent.enrollment_id.in_(enr_ids), CheckEvent.at >= since)
            .order_by(CheckEvent.at)
        ).all()
        latest: dict[tuple, bool] = {}
        for ev in events:
            latest[(ev.question_id, ev.check_key, ev.enrollment_id)] = ev.passed
        agg: dict[tuple, list[bool]] = {}
        for (qid, key, _e), passed in latest.items():
            agg.setdefault((qid, key), []).append(passed)
        qmap = {q.id: q for q in questions}
        for (qid, key), vals in agg.items():
            n = len(vals)
            fails = sum(1 for v in vals if not v)
            if n >= 3 and fails / n >= 1 / 3:
                failing.append(
                    {
                        "question_id": str(qid),
                        "qid": qmap[qid].qid if qid in qmap else None,
                        "check_key": key,
                        "fail_rate": round(fails / n, 2),
                        "n": n,
                    }
                )
        failing.sort(key=lambda r: -r["fail_rate"])

    failed_list = []
    groups: dict[tuple, dict] = {}
    if enr_ids:
        failed_subs = db.scalars(
            select(Submission)
            .where(
                Submission.enrollment_id.in_(enr_ids), Submission.status == SubmissionStatus.failed
            )
            .order_by(Submission.submitted_at.desc())
            .limit(500)
        ).all()
        for s in failed_subs:
            err = _last_error(s)
            row = {
                "submission_id": str(s.id),
                "netid": s.enrollment.user.netid,
                "display_name": s.enrollment.user.name,
                "question_id": str(s.question_id),
                "qid": s.question.qid,
                "submitted_at": iso(s.submitted_at),
                "error": (err or "")[:300],
            }
            failed_list.append(row)
            # One entry per cause and assignment: 23 copies of one error are one problem.
            cause = failures.classify(err)
            a = s.question.assignment
            g = groups.setdefault(
                (a.id, cause.kind, cause.summary),
                {
                    "key": f"{a.id}:{cause.kind}:{cause.summary}",
                    **cause.as_dict(),
                    "assignment_id": str(a.id),
                    "assignment_title": a.title,
                    "error": (err or "")[:2000],
                    "qids": [],
                    "submissions": [],
                },
            )
            if s.question.qid not in g["qids"]:
                g["qids"].append(s.question.qid)
            g["submissions"].append(row)

    return {
        "awaiting_manual": sorted(awaiting.values(), key=lambda a: a["oldest_submitted_at"] or ""),
        "inactive_students": inactive,
        "failing_checks": failing,
        "grader_failures": failed_list,
        "failure_groups": sorted(
            groups.values(), key=lambda g: (-len(g["submissions"]), g["summary"])
        ),
    }


def _last_error(sub: Submission) -> str | None:
    failed = [r for r in sub.runs if r.status == RunStatus.failed and r.error]
    if not failed:
        return None
    return max(failed, key=lambda r: r.finished_at or r.queued_at).error


@router.get("/offerings/{offering_id}/grid")
def grid(
    assignment_id: uuid.UUID | None = None,
    m: Membership = Depends(require_staff),
    db: Session = Depends(get_db),
):
    stmt = (
        select(Question)
        .join(Assignment)
        .where(Assignment.offering_id == m.offering.id, Question.active)
    )
    if assignment_id is not None:
        stmt = stmt.where(Question.assignment_id == assignment_id)
    questions = db.scalars(stmt.order_by(Assignment.created_at, Question.order)).all()
    out = []
    for e in _students(db, m):
        cells = {}
        last: datetime | None = None
        for q in questions:
            subs = submissions_for(db, e.id, q.id)
            c = cell_state(db, subs)
            c["max"] = float(q.max_points)
            cells[str(q.id)] = c
            if subs:
                ts = subs[-1].submitted_at
                last = ts if last is None or ts > last else last
        out.append(
            {
                "netid": e.user.netid,
                "display_name": e.user.name,
                "section": e.section.name if e.section else None,
                "last_activity": iso(last),
                "cells": cells,
            }
        )
    return {
        "questions": [
            {
                "id": str(q.id),
                "qid": q.qid,
                "title": q.title,
                "assignment_id": str(q.assignment_id),
                "max_points": float(q.max_points),
                "grading_mode": q.grading_mode.value,
            }
            for q in questions
        ],
        "students": out,
    }


@router.get("/offerings/{offering_id}/progress")
def class_progress(
    assignment_id: uuid.UUID | None = None,
    m: Membership = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Where the class stands, per assignment and per question (services/progress.py).

    With ``assignment_id`` the answer also carries one mark per student per
    question, in the order of ``students``, for the assignment page's roster strips.
    """
    students = _students(db, m)
    stmt = (
        select(Question)
        .join(Assignment)
        .where(Assignment.offering_id == m.offering.id, Question.active)
    )
    if assignment_id is not None:
        stmt = stmt.where(Question.assignment_id == assignment_id)
    questions = db.scalars(stmt.order_by(Question.order)).all()
    marks = assignment_id is not None
    return {
        "roster": len(students),
        "students": (
            [{"netid": e.user.netid, "display_name": e.user.name} for e in students]
            if marks
            else None
        ),
        "assignments": progress.compute(db, students, questions, marks=marks),
    }


@router.get("/offerings/{offering_id}/queue")
def queue(
    question_id: uuid.UUID, m: Membership = Depends(require_staff), db: Session = Depends(get_db)
):
    q = db.get(Question, question_id)
    if q is None or q.assignment.offering_id != m.offering.id:
        raise api_error(404, "not_found", "question not found")
    items = []
    for e in _students(db, m):
        subs = submissions_for(db, e.id, q.id)
        if not subs:
            continue
        s = subs[-1]
        j = submission_json(db, s)
        j["display_name"] = e.user.name
        j["needs_grading"] = _needs_manual(db, s)
        items.append(j)
    items.sort(key=lambda j: (not j["needs_grading"], j["submitted_at"]))
    return {
        "question": {
            "id": str(q.id),
            "qid": q.qid,
            "title": q.title,
            "max_points": float(q.max_points),
            "auto_points_max": float(q.auto_points_max),
            "grading_mode": q.grading_mode.value,
            "rubric": {"id": str(q.rubric.id), "name": q.rubric.name, "items": q.rubric.items}
            if q.rubric
            else None,
        },
        "items": items,
    }


class ScoreIn(BaseModel):
    manual_points: float | None = None
    rubric_scores: dict[str, float] = Field(default_factory=dict)
    feedback: str | None = None
    final: bool = True
    reason: str | None = None


@router.post("/submissions/{submission_id}/score")
def score_submission(
    submission_id: uuid.UUID,
    body: ScoreIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    sub = db.get(Submission, submission_id)
    if sub is None:
        raise api_error(404, "not_found", "submission not found")
    m = membership_for(db, user, sub.enrollment.offering_id)
    if m is None or not m.is_staff() or not m.can_see_section(sub.enrollment.section_id):
        raise api_error(404, "not_found", "submission not found")
    if (
        m.role == Role.ta
        and body.final
        and not (m.offering.settings or {}).get("ta_can_finalize", True)
    ):
        raise api_error(403, "forbidden", "TAs may not finalize grades in this offering")

    q = sub.question
    if q.rubric is not None:
        limits = {i["key"]: float(i["points"]) for i in q.rubric.items or []}
        for key, v in body.rubric_scores.items():
            if key not in limits:
                raise api_error(422, "unknown_rubric_item", f"no rubric item {key!r}")
            if not (0 <= v <= limits[key] + 1e-9):
                raise api_error(
                    422, "out_of_range", f"rubric item {key!r} takes 0 to {limits[key]:g}"
                )
    manual = body.manual_points
    if manual is None and body.rubric_scores:
        manual = sum(body.rubric_scores.values())
    manual_max = float(q.max_points) - float(q.auto_points_max)
    if manual is not None and not (0 <= manual <= manual_max + 1e-9):
        raise api_error(422, "out_of_range", f"manual_points must be between 0 and {manual_max:g}")
    prev = final_score(db, sub)
    sc = Score(
        submission_id=sub.id,
        auto_points=prev.auto_points if prev else None,
        manual_points=manual,
        rubric_scores=body.rubric_scores,
        feedback=body.feedback,
        grader_user_id=user.id,
        is_final=body.final,
    )
    db.add(sc)
    db.flush()
    if sub.status != SubmissionStatus.failed and body.final:
        sub.status = SubmissionStatus.graded
    qg = recompute_question_grade(db, sub.enrollment_id, q, q.assignment)
    audit.record(
        db,
        actor_id=user.id,
        offering_id=m.offering.id,
        entity="score",
        entity_id=sub.id,
        action="score",
        before={"total": prev.total if prev else None},
        after={"total": sc.total, "final": sc.is_final},
        reason=body.reason,
    )
    bus.publish(
        Event(
            m.offering.id,
            "score.updated",
            {
                "submission_id": str(sub.id),
                "question_id": str(q.id),
                "netid": sub.enrollment.user.netid,
            },
        )
    )
    j = submission_json(db, sub)
    j["question_grade"] = {
        "points": float(qg.points) if qg.points is not None else None,
        "submission_id": str(qg.submission_id) if qg.submission_id else None,
    }
    return j


@router.get("/offerings/{offering_id}/students/{netid}")
def student_history(
    netid: str, m: Membership = Depends(require_staff), db: Session = Depends(get_db)
):
    e = db.scalar(
        select(Enrollment)
        .join(User)
        .where(Enrollment.offering_id == m.offering.id, User.netid == netid.lower())
    )
    if e is None or not m.can_see_section(e.section_id):
        raise api_error(404, "not_found", "student not found")
    subs = db.scalars(
        select(Submission).where(Submission.enrollment_id == e.id).order_by(Submission.submitted_at)
    ).all()
    grades = db.scalars(select(QuestionGrade).where(QuestionGrade.enrollment_id == e.id)).all()
    return {
        "netid": e.user.netid,
        "display_name": e.user.name,
        "section": e.section.name if e.section else None,
        "status": e.status.value,
        "submissions": [submission_json(db, s) for s in subs],
        "question_grades": {
            str(g.question_id): float(g.points) if g.points is not None else None for g in grades
        },
    }


@router.get("/offerings/{offering_id}/me")
def my_overview(m: Membership = Depends(require_member), db: Session = Depends(get_db)):
    """Student portal summary: per assignment status and grade."""
    assignments = db.scalars(
        select(Assignment)
        .where(Assignment.offering_id == m.offering.id)
        .order_by(Assignment.created_at)
    ).all()
    out = []
    for a in assignments:
        qs = [q for q in a.questions if q.active]
        total_max = sum(float(q.max_points) for q in qs)
        earned = 0.0
        any_grade = False
        n_sub = 0
        for q in qs:
            subs = submissions_for(db, m.enrollment.id, q.id)
            if subs:
                n_sub += 1
            g = db.scalar(
                select(QuestionGrade).where(
                    QuestionGrade.enrollment_id == m.enrollment.id,
                    QuestionGrade.question_id == q.id,
                )
            )
            if g is not None and g.points is not None:
                earned += float(g.points)
                any_grade = True
        status = (
            "not_started"
            if n_sub == 0
            else ("complete" if n_sub == len(qs) and any_grade else "in_progress")
        )
        out.append(
            {
                **assignment_json(a),
                "status": status,
                "points": earned if any_grade else None,
                "max_points": total_max,
            }
        )
    return {
        "offering": {"id": str(m.offering.id), "title": m.offering.title, "term": m.offering.term},
        "assignments": out,
    }


@router.get("/offerings/{offering_id}/events")
async def events(request: Request, m: Membership = Depends(require_staff)):
    q = bus.subscribe(m.offering.id)

    async def gen():
        try:
            yield {"event": "hello", "data": "{}"}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield ev.sse()
                except TimeoutError:
                    yield {"comment": "keepalive"}
        finally:
            bus.unsubscribe(m.offering.id, q)

    return EventSourceResponse(gen())


@router.get("/offerings/{offering_id}/export/canvas")
def export_canvas(
    assignment_ids: str, m: Membership = Depends(require_instructor), db: Session = Depends(get_db)
):
    upload = db.scalar(
        select(RosterUpload)
        .where(RosterUpload.offering_id == m.offering.id, RosterUpload.source == "canvas_csv")
        .order_by(RosterUpload.created_at.desc())
    )
    if upload is None:
        raise api_error(
            409, "no_canvas_template", "upload a Canvas gradebook export on the roster page first"
        )
    art = db.get(Artifact, upload.artifact_id)
    assert art is not None
    template = store().get(art).decode("utf-8-sig")
    ids = [uuid.UUID(x) for x in assignment_ids.split(",") if x]
    columns: dict[str, dict[str, float | None]] = {}
    for aid in ids:
        a = db.get(Assignment, aid)
        if a is None or a.offering_id != m.offering.id:
            raise api_error(404, "not_found", f"assignment {aid} not found")
        header = header_for(a.title, (a.settings or {}).get("canvas_assignment_id"))
        col: dict[str, float | None] = {}
        for e in _students(db, m):
            pts = 0.0
            seen = False
            for q in a.questions:
                if not q.active:
                    continue
                g = db.scalar(
                    select(QuestionGrade).where(
                        QuestionGrade.enrollment_id == e.id, QuestionGrade.question_id == q.id
                    )
                )
                if g is not None and g.points is not None:
                    pts += float(g.points)
                    seen = True
            col[e.user.netid] = pts if seen else None
        columns[header] = col
    csv_text = build_canvas_csv(template, columns)
    audit.record(
        db,
        actor_id=m.user.id,
        offering_id=m.offering.id,
        entity="export",
        entity_id=m.offering.id,
        action="canvas_csv",
        after={"assignments": [str(i) for i in ids]},
    )
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="canvas-grades.csv"'},
    )


def audit_json(rows, users: dict) -> list[dict]:
    return [
        {
            "id": str(r.id),
            "at": iso(r.at),
            "actor": users.get(r.actor_user_id),
            "entity": r.entity,
            "entity_id": r.entity_id,
            "action": r.action,
            "before": r.before,
            "after": r.after,
            "reason": r.reason,
        }
        for r in rows
    ]


@router.get("/offerings/{offering_id}/audit")
def offering_audit(
    limit: int = 200,
    m: Membership = Depends(require_instructor),
    db: Session = Depends(get_db),
):
    """Every audited action in this offering: grades, roster, settings, publishes, exports."""
    rows = db.scalars(
        select(GradeAudit)
        .where(GradeAudit.offering_id == m.offering.id)
        .order_by(GradeAudit.at.desc())
        .limit(min(limit, 1000))
    ).all()
    users = {
        u.id: u.netid
        for u in db.scalars(
            select(User).where(User.id.in_({r.actor_user_id for r in rows if r.actor_user_id}))
        )
    }
    return audit_json(rows, users)


@router.post("/submissions/{submission_id}/retry")
def retry_submission(
    submission_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    """Re-queue grading (and rendering if missing) for a submission whose run failed."""
    sub = db.get(Submission, submission_id)
    if sub is None:
        raise api_error(404, "not_found", "submission not found")
    m = membership_for(db, user, sub.enrollment.offering_id)
    if m is None or not m.is_staff() or not m.can_see_section(sub.enrollment.section_id):
        raise api_error(404, "not_found", "submission not found")
    _requeue(db, user, m, sub)
    return {"id": str(sub.id), "status": sub.status.value}


def _requeue(db: Session, user: User, m: Membership, sub: Submission) -> None:
    sub.status = SubmissionStatus.received
    db.add(GraderRun(submission_id=sub.id, kind=RunKind.autograde))
    if sub.render_artifact_id is None:
        db.add(GraderRun(submission_id=sub.id, kind=RunKind.render))
    db.flush()
    audit.record(
        db,
        actor_id=user.id,
        offering_id=m.offering.id,
        entity="submission",
        entity_id=sub.id,
        action="retry",
        after={"netid": sub.enrollment.user.netid, "qid": sub.question.qid},
    )


def _visible_subs(db: Session, m: Membership, ids: list[uuid.UUID]) -> list[Submission]:
    subs = db.scalars(select(Submission).where(Submission.id.in_(ids))).all() if ids else []
    return [
        s
        for s in subs
        if s.enrollment.offering_id == m.offering.id and m.can_see_section(s.enrollment.section_id)
    ]


class RetryMany(BaseModel):
    submission_ids: list[uuid.UUID] = Field(max_length=500)


@router.post("/offerings/{offering_id}/retry")
def retry_many(
    body: RetryMany,
    m: Membership = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Re-queue several failed submissions (Retry all on one cause)."""
    done = []
    for sub in _visible_subs(db, m, body.submission_ids):
        if sub.status == SubmissionStatus.failed:
            _requeue(db, m.user, m, sub)
            done.append(str(sub.id))
    return {"requeued": done}


@router.get("/offerings/{offering_id}/retry-status")
def retry_status(
    ids: str,
    m: Membership = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Where each retried submission stands: queued, running, graded, waiting
    for a hand grade, or failed again (with why). Status alone cannot say: a
    hand-graded question is back at 'received' both before and after its run."""
    wanted = []
    for raw in ids.split(",")[:500]:
        try:
            wanted.append(uuid.UUID(raw))
        except ValueError:
            continue
    out = []
    for sub in _visible_subs(db, m, wanted):
        runs = [r for r in sub.runs if r.kind == RunKind.autograde]
        if any(r.status == RunStatus.running for r in runs):
            state = "running"
        elif any(r.status == RunStatus.queued for r in runs):
            state = "queued"
        elif sub.status == SubmissionStatus.failed:
            state = "failed"
        elif sub.status == SubmissionStatus.graded:
            state = "graded"
        else:
            state = "waiting_for_grade"
        out.append(
            {
                "submission_id": str(sub.id),
                "state": state,
                "cause": failures.classify(_last_error(sub)).as_dict()
                if state == "failed"
                else None,
            }
        )
    return out
