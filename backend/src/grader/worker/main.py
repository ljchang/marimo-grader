"""grader-worker: claims queued grader runs and executes them.

Two run kinds:

* ``render`` — ``marimo export html`` of the submitted notebook, stored as an
  artifact for the grading view and the student portal.
* ``autograde`` — materialize the submission in the on-disk layout MoGrader
  expects, reinject the instructor's check/hidden-test cells from the pinned
  assignment version, run MoGrader's runner, and turn the per-check results
  into an ``auto_points`` score for the submitted question.

Job claiming uses ``SELECT ... FOR UPDATE SKIP LOCKED`` on PostgreSQL so
several workers can run side by side. The MoGrader integration lives in
``grader.worker.mograder_runner`` and is optional: if the package is not
installed the worker still renders notebooks and marks autograde runs failed
with a clear error.
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from grader.api.submissions import is_test
from grader.db import get_engine, get_sessionmaker
from grader.models import (
    Artifact,
    GraderRun,
    GradingMode,
    RunKind,
    RunStatus,
    Score,
    Submission,
    SubmissionStatus,
    utcnow,
)
from grader.services.artifacts import store
from grader.services.grades import recompute_question_grade
from grader.worker.materialize import rewrite_dependencies

log = logging.getLogger("grader.worker")

RENDER_TIMEOUT = int(os.environ.get("GRADER_RENDER_TIMEOUT", "180"))


def claim(db: Session) -> GraderRun | None:
    stmt = (
        select(GraderRun)
        .where(GraderRun.status == RunStatus.queued)
        .order_by(GraderRun.queued_at)
        .limit(1)
    )
    if get_engine().dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    run = db.scalar(stmt)
    if run is None:
        return None
    run.status = RunStatus.running
    run.started_at = utcnow()
    db.commit()
    return run


def _notebook_bytes(db: Session, sub: Submission) -> bytes:
    art = db.get(Artifact, sub.notebook_artifact_id)
    assert art is not None
    return store().get(art)


def do_render(db: Session, run: GraderRun, sub: Submission) -> None:
    from grader.worker.sandbox import prepare_env, run_with_timeout

    src = rewrite_dependencies(_notebook_bytes(db, sub).decode("utf-8", "replace"))
    venv = prepare_env(src)
    with tempfile.TemporaryDirectory() as td:
        nb = Path(td) / "notebook.py"
        nb.write_text(src)
        out = Path(td) / "notebook.html"
        python = str(venv / "bin" / "python") if venv else sys.executable
        cmd = [
            python,
            "-m",
            "marimo",
            "export",
            "html",
            str(nb),
            "-o",
            str(out),
            "--no-include-code",
            "--no-sandbox",
        ]
        # Rendering executes the notebook; widgets render as placeholders (GRADER_RENDER).
        env = {**os.environ, "MARIMO_SKIP_UPDATE_CHECK": "1", "GRADER_RENDER": "1"}
        proc = run_with_timeout(cmd, timeout=RENDER_TIMEOUT, env=env, cwd=td)
        if proc.returncode != 0 or not out.exists():
            raise RuntimeError(f"marimo export failed: {proc.stderr[-2000:]}")
        html = out.read_bytes()
    art = store().put(db, html, kind="render", content_type="text/html")
    sub.render_artifact_id = art.id
    run.results = {"bytes": len(html), "env": str(venv) if venv else "worker"}


def do_autograde(db: Session, run: GraderRun, sub: Submission) -> None:
    from grader.worker import mograder_runner

    result = mograder_runner.grade(db, sub)
    run.grader_version = result.grader_version
    run.results = result.as_dict()
    q = sub.question
    auto_max = float(q.auto_points_max)
    auto_points = round(result.fraction * auto_max, 2) if auto_max else 0.0
    prev = next(
        (s for s in sorted(sub.scores, key=lambda s: s.graded_at, reverse=True) if s.is_final), None
    )
    sc = Score(
        submission_id=sub.id,
        auto_points=auto_points,
        manual_points=prev.manual_points if prev else None,
        rubric_scores=prev.rubric_scores if prev else {},
        feedback=result.feedback
        if q.grading_mode == GradingMode.auto
        else (prev.feedback if prev else None),
        is_final=q.grading_mode == GradingMode.auto or bool(prev and prev.is_final),
    )
    db.add(sc)
    db.flush()
    if q.grading_mode == GradingMode.auto:
        sub.status = SubmissionStatus.graded
    # A staff attempt is scored and returned to the notebook like any other, but
    # it must not roll up into a grade -- no QuestionGrade row is written for it,
    # so an instructor testing their own assignment leaves the gradebook alone.
    if not is_test(sub):
        recompute_question_grade(db, sub.enrollment_id, q, q.assignment)


def process(db: Session, run: GraderRun) -> None:
    sub = db.get(Submission, run.submission_id)
    assert sub is not None
    try:
        if run.kind == RunKind.render:
            do_render(db, run, sub)
        elif run.kind == RunKind.autograde:
            if sub.status == SubmissionStatus.received:
                sub.status = SubmissionStatus.grading
            do_autograde(db, run, sub)
            if sub.status == SubmissionStatus.grading:
                # manual/hybrid: auto part done, awaiting a human
                sub.status = SubmissionStatus.received
        else:
            raise RuntimeError(f"unsupported run kind {run.kind}")
        run.status = RunStatus.succeeded
    except Exception as e:  # noqa: BLE001
        log.exception("run %s failed", run.id)
        run.status = RunStatus.failed
        run.error = f"{type(e).__name__}: {e}"[:4000]
        if run.kind == RunKind.autograde:
            sub.status = SubmissionStatus.failed
    run.finished_at = utcnow()
    db.commit()


def requeue_stale(db: Session) -> int:
    """Runs stuck in 'running' belong to a worker that died; give them back to the queue."""
    rows = db.scalars(select(GraderRun).where(GraderRun.status == RunStatus.running)).all()
    for r in rows:
        r.status, r.started_at = RunStatus.queued, None
    db.commit()
    return len(rows)


def loop(poll_seconds: float = 2.0, once: bool = False) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    Session_ = get_sessionmaker()
    log.info("worker started (db=%s)", get_engine().dialect.name)
    with Session_() as db:
        n = requeue_stale(db)
        if n:
            log.warning("re-queued %d run(s) left 'running' by a previous worker", n)
    while True:
        with Session_() as db:
            run = claim(db)
            if run is None:
                if once:
                    return
                time.sleep(poll_seconds)
                continue
            log.info("run %s kind=%s submission=%s", run.id, run.kind.value, run.submission_id)
            process(db, run)
        if once:
            return


def run() -> None:  # console script
    loop(once="--once" in sys.argv)


def _now() -> datetime:  # for tests
    return datetime.now(UTC)


__all__ = ["claim", "process", "loop", "run", "uuid"]
