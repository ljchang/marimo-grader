"""Re-render past submissions so the grading view shows their code.

Renders made before 0.1.5 left the code out (``--no-include-code``): a grader
saw each check's "passed" but not the answer it passed on. This re-runs the
render of every submission that still has such a render.

The worker takes runs in arrival order, so queueing hundreds of renders at
once would put every new submission behind them. ``trickle`` instead adds one
render only while nothing else is queued or running, and waits for it, so the
backfill uses idle time and stops being in the way the moment students
submit. It is resumable: a submission counts as done once a render with code
has succeeded, and a failed re-render keeps the old render and moves on.
"""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from grader.models import GraderRun, RunKind, RunStatus, Submission


def _rendered_with_code(sub: Submission) -> bool:
    return any(
        r.kind == RunKind.render
        and r.status == RunStatus.succeeded
        and (r.results or {}).get("code")
        for r in sub.runs
    )


def pending(db: Session, tried: set | frozenset = frozenset()) -> list[Submission]:
    """Submissions whose render predates code, newest first; skips assignments
    that do not re-run (``render: false``) and anything in ``tried``."""
    subs = db.scalars(select(Submission).order_by(Submission.submitted_at.desc())).all()
    return [
        s
        for s in subs
        if s.id not in tried
        and s.render_artifact_id is not None
        and (s.question.assignment.settings or {}).get("render", True) is not False
        and not _rendered_with_code(s)
    ]


def _busy(db: Session) -> bool:
    return (
        db.scalar(
            select(GraderRun.id)
            .where(GraderRun.status.in_([RunStatus.queued, RunStatus.running]))
            .limit(1)
        )
        is not None
    )


def trickle(sessionmaker, *, poll: float = 5.0, limit: int | None = None, echo=print) -> int:
    """Re-render one submission at a time while the queue is otherwise idle."""
    tried: set = set()
    done = 0
    while limit is None or done < limit:
        with sessionmaker() as db:
            if _busy(db):
                time.sleep(poll)
                continue
            todo = pending(db, tried)
            if not todo:
                break
            sub = todo[0]
            tried.add(sub.id)
            run = GraderRun(submission_id=sub.id, kind=RunKind.render)
            db.add(run)
            db.commit()
            run_id = run.id
            echo(f"re-render {sub.id} ({len(todo) - 1} after this)")
        while True:
            time.sleep(poll)
            with sessionmaker() as db:
                status = db.get(GraderRun, run_id).status
            if status in (RunStatus.succeeded, RunStatus.failed):
                if status == RunStatus.failed:
                    echo(f"  failed; the previous render stays ({run_id})")
                break
        done += 1
    return done
