"""Render must be claimed before autograde when both are queued at the same instant.

Rendering is the only one of the two that runs outside bubblewrap, so it is the only
one with network. Autograde runs under --unshare-net and can read only what is already
in HF_HOME, so for a data-downloading assignment a cold-cache autograde fails the whole
run while a render would have warmed the cache. Ordering on queued_at alone does not
express that: the column defaults to datetime.now(UTC), and two rows created in the
same flush usually land on the identical microsecond.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from grader.models import Base, GraderRun, RunKind, RunStatus
from grader.worker.main import _RUN_PRIORITY


def _claim_order(rows: list[tuple[RunKind, datetime]]) -> list[str]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sid = uuid.uuid4()
    with Session(engine) as db:
        for kind, queued_at in rows:
            db.add(
                GraderRun(
                    submission_id=sid,
                    kind=kind,
                    status=RunStatus.queued,
                    queued_at=queued_at,
                )
            )
        db.commit()
        claimed = db.scalars(
            select(GraderRun)
            .where(GraderRun.status == RunStatus.queued)
            .order_by(GraderRun.queued_at, _RUN_PRIORITY)
        ).all()
        return [r.kind.value for r in claimed]


def test_render_wins_a_tie_regardless_of_insert_order():
    t = datetime.now(UTC)
    assert _claim_order([(RunKind.autograde, t), (RunKind.render, t)])[0] == "render"
    assert _claim_order([(RunKind.render, t), (RunKind.autograde, t)])[0] == "render"


def test_older_work_still_goes_first():
    """The tiebreak must not turn the queue into a priority queue across submissions."""
    t = datetime.now(UTC)
    order = _claim_order([(RunKind.autograde, t), (RunKind.render, t + timedelta(seconds=5))])
    assert order == ["autograde", "render"]


def test_queued_at_alone_would_not_have_decided_it():
    """Guards the premise: same-flush rows really do collide on queued_at."""
    ties = sum(datetime.now(UTC) == datetime.now(UTC) for _ in range(2000))
    assert ties > 100, "if timestamps no longer collide, the tiebreak's rationale has changed"
