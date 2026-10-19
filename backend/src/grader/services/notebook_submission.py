"""The whole-notebook question: one submission that carries the entire notebook.

Per-question submissions already store the full notebook, but each is filed
under the question its button belongs to. An assignment with
``notebook_submission`` on gets one more question, ``notebook``, that is not
tied to a cell: the student submits the whole thing for an instructor to read.

``notebook_points`` decides what kind of question it is. Above zero it is a
manual question and lands in the grading queue like any other. At zero it is a
receipt: the attempt is stored and rendered, marked graded on arrival, and
never asks anyone for a score.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from grader.models import Assignment, GradingMode, Question

NOTEBOOK_QID = "notebook"
NOTEBOOK_TITLE = "Whole notebook"


def enabled(a: Assignment) -> bool:
    return bool((a.settings or {}).get("notebook_submission"))


def points(a: Assignment) -> float:
    return float((a.settings or {}).get("notebook_points") or 0)


def is_receipt(q: Question) -> bool:
    """A zero-point notebook question: nothing to grade, so nothing waits on a grader."""
    return q.qid == NOTEBOOK_QID and float(q.max_points) == 0


def sync(db: Session, a: Assignment) -> Question | None:
    """Make the ``notebook`` question match the assignment's settings.

    Called after a publish (whose question upsert deactivates anything it was not
    sent) and after a settings change, so either order of the two works.
    """
    q = next((x for x in a.questions if x.qid == NOTEBOOK_QID), None)
    if not enabled(a):
        if q is not None:
            q.active = False
        return None
    if q is None:
        q = Question(assignment_id=a.id, qid=NOTEBOOK_QID, title=NOTEBOOK_TITLE, check_keys=[])
        db.add(q)
        a.questions.append(q)
    pts = points(a)
    others = [x.order for x in a.questions if x is not q and x.order is not None]
    q.order = max(others, default=-1) + 1
    q.max_points = pts
    q.auto_points_max = 0
    q.grading_mode = GradingMode.manual if pts > 0 else GradingMode.auto
    q.active = True
    db.flush()
    return q
