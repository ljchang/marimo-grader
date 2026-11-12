"""Class progress: where every student stands on every question, in a few queries.

The assignments table and the assignment page both read this. Each (student,
question) is one of six states, decided from the latest attempt:

``none``     no attempt yet
``failed``   the grader could not run it (the Needs attention page has the cause)
``waiting``  to be graded by a person, who has not started
``draft``    a person has started grading it; nothing is published yet
``running``  queued or being graded automatically
``graded``   has a published score
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from grader.models import (
    Enrollment,
    GradingMode,
    Question,
    QuestionGrade,
    Score,
    Submission,
    SubmissionStatus,
)

STATES = ("graded", "draft", "waiting", "failed", "running", "none")
# A student's state on a whole assignment is the most pressing of their questions.
_URGENCY = {"waiting": 0, "failed": 1, "draft": 2, "running": 3, "graded": 4, "none": 5}


def _state(sub: Submission | None, score: Score | None, by_hand: bool, drafted: bool) -> str:
    if sub is None:
        return "none"
    if sub.status == SubmissionStatus.failed:
        return "failed"
    if by_hand and (score is None or not score.is_final):
        return "draft" if drafted else "waiting"
    if score is None or sub.status in (SubmissionStatus.received, SubmissionStatus.grading):
        return "running"
    return "graded"


def compute(
    db: Session,
    students: Sequence[Enrollment],
    questions: Sequence[Question],
    marks: bool = False,
) -> dict:
    enr_ids = [e.id for e in students]
    q_ids = [q.id for q in questions]

    latest: dict[tuple[uuid.UUID, uuid.UUID], Submission] = {}
    if enr_ids and q_ids:
        for s in db.scalars(
            select(Submission)
            .where(Submission.enrollment_id.in_(enr_ids), Submission.question_id.in_(q_ids))
            .order_by(Submission.attempt_no)
        ):
            latest[(s.enrollment_id, s.question_id)] = s

    # published_score() for every latest attempt at once; drafts do not count as
    # grades, but an attempt whose newest row is a person's draft is under way.
    newest_final: dict[uuid.UUID, Score] = {}
    newest_any: dict[uuid.UUID, Score] = {}
    sub_ids = [s.id for s in latest.values()]
    if sub_ids:
        for sc in db.scalars(
            select(Score).where(Score.submission_id.in_(sub_ids)).order_by(Score.graded_at)
        ):
            newest_any[sc.submission_id] = sc
            if sc.is_final:
                newest_final[sc.submission_id] = sc
    drafted = {
        sid for sid, sc in newest_any.items() if not sc.is_final and sc.grader_user_id is not None
    }

    points: dict[tuple[uuid.UUID, uuid.UUID], float | None] = {}
    if enr_ids and q_ids:
        for qg in db.scalars(
            select(QuestionGrade).where(
                QuestionGrade.enrollment_id.in_(enr_ids), QuestionGrade.question_id.in_(q_ids)
            )
        ):
            points[(qg.enrollment_id, qg.question_id)] = (
                float(qg.points) if qg.points is not None else None
            )

    by_assignment: dict[uuid.UUID, list[Question]] = {}
    for q in questions:
        by_assignment.setdefault(q.assignment_id, []).append(q)

    out: dict[str, dict] = {}
    for aid, qs in by_assignment.items():
        autograde = (qs[0].assignment.settings or {}).get("autograde", True)
        possible = sum(float(q.max_points) for q in qs)
        q_out: dict[str, dict] = {}
        per_student: dict[uuid.UUID, list[str]] = {e.id: [] for e in students}
        to_grade = 0
        for q in qs:
            by_hand = q.grading_mode != GradingMode.auto or not autograde
            counts = dict.fromkeys(STATES, 0)
            row: list[str] = []
            for e in students:
                sub = latest.get((e.id, q.id))
                sc = newest_final.get(sub.id) if sub else None
                st = _state(sub, sc, by_hand, sub is not None and sub.id in drafted)
                counts[st] += 1
                per_student[e.id].append(st)
                row.append(st)
            to_grade += counts["waiting"] + counts["draft"]
            q_out[str(q.id)] = {"counts": counts, **({"marks": row} if marks else {})}

        students_counts = dict.fromkeys(STATES, 0)
        ratios: list[float] = []
        for e in students:
            states = per_student[e.id]
            if all(st == "none" for st in states):
                students_counts["none"] += 1
                continue
            worst = min((st for st in states if st != "none"), key=_URGENCY.__getitem__)
            students_counts[worst] += 1
            # The average counts only students whose work is fully graded; a question
            # they skipped counts as zero, as it does in the gradebook.
            if worst == "graded" and possible > 0:
                earned = sum(points.get((e.id, q.id)) or 0.0 for q in qs)
                ratios.append(earned / possible)

        out[str(aid)] = {
            "students": students_counts,
            "submitted": len(students) - students_counts["none"],
            "to_grade": to_grade,
            "average": round(100 * sum(ratios) / len(ratios), 1) if ratios else None,
            "averaged_over": len(ratios),
            "questions": q_out,
        }
    return out
