"""Grade policy: which attempt counts, and the official per-question grade."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from grader.models import (
    Assignment,
    Question,
    QuestionGrade,
    Score,
    Submission,
    SubmissionStatus,
    utcnow,
)

POLICIES = ("latest", "highest", "first", "selected")


def final_score(db: Session, submission: Submission) -> Score | None:
    """Latest final score for a submission, else latest score of any kind."""
    rows = db.scalars(
        select(Score).where(Score.submission_id == submission.id).order_by(Score.graded_at.desc())
    ).all()
    for r in rows:
        if r.is_final:
            return r
    return rows[0] if rows else None


def submissions_for(
    db: Session, enrollment_id: uuid.UUID, question_id: uuid.UUID
) -> list[Submission]:
    return list(
        db.scalars(
            select(Submission)
            .where(Submission.enrollment_id == enrollment_id, Submission.question_id == question_id)
            .order_by(Submission.attempt_no)
        )
    )


def pick_attempt(
    db: Session, subs: list[Submission], policy: str, pinned: Submission | None = None
) -> tuple[Submission | None, Score | None]:
    if pinned is not None:
        return pinned, final_score(db, pinned)
    if not subs:
        return None, None
    if policy == "first":
        s = subs[0]
        return s, final_score(db, s)
    if policy == "highest":
        best: tuple[Submission | None, Score | None] = (None, None)
        for s in subs:
            sc = final_score(db, s)
            if sc is not None and (best[1] is None or sc.total > best[1].total):
                best = (s, sc)
        return best if best[0] is not None else (subs[-1], None)
    # latest (default) and "selected" without a pin
    s = subs[-1]
    return s, final_score(db, s)


def recompute_question_grade(
    db: Session, enrollment_id: uuid.UUID, question: Question, assignment: Assignment
) -> QuestionGrade:
    policy = (assignment.settings or {}).get("grade_policy", "latest")
    qg = db.scalar(
        select(QuestionGrade).where(
            QuestionGrade.enrollment_id == enrollment_id, QuestionGrade.question_id == question.id
        )
    )
    pinned = None
    if qg is not None and qg.pinned and qg.submission_id is not None:
        pinned = db.get(Submission, qg.submission_id)
    subs = submissions_for(db, enrollment_id, question.id)
    chosen, score = pick_attempt(db, subs, policy, pinned)
    if qg is None:
        qg = QuestionGrade(enrollment_id=enrollment_id, question_id=question.id)
        db.add(qg)
    qg.submission_id = chosen.id if chosen else None
    qg.points = score.total if score else None
    qg.updated_at = utcnow()
    db.flush()
    return qg


def cell_state(db: Session, subs: list[Submission]) -> dict:
    """State for one roster-grid cell."""
    if not subs:
        return {"state": "none"}
    latest = subs[-1]
    sc = final_score(db, latest)
    if latest.status == SubmissionStatus.failed:
        return {"state": "failed", "attempts": len(subs)}
    if sc is None or latest.status in (SubmissionStatus.received, SubmissionStatus.grading):
        return {"state": "submitted", "attempts": len(subs)}
    return {"state": "graded", "attempts": len(subs), "points": sc.total}
