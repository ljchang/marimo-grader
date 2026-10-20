"""Grading shows what students wrote: renders keep their code, a backfill
re-renders old ones while the queue is idle, and the safety check does not
blame students for lines the course gave them."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from grader import db as dbmod
from grader import rerender
from grader.models import Artifact, Assignment, GraderRun, RunKind, RunStatus, Submission
from tests.conftest import login
from tests.test_private_assignments import _set, _submit
from tests.test_publish_public import Q2, _publish

# -- the safety check ------------------------------------------------------------


def test_template_lines_are_excused_student_lines_are_not():
    pytest.importorskip("mograder.grading.safety")
    from grader.worker.mograder_runner import student_safety_findings

    released = "import marimo\nimport io\nanswer = ...\n"
    # The template's own import, untouched: nothing to blame the student for.
    assert student_safety_findings("import marimo\nimport io\nanswer = 1\n", released) == []
    # Something the student added is still refused.
    assert student_safety_findings(
        "import marimo\nimport io\nimport os\nanswer = 1\n", released
    ) == ["denied import: os"]
    # With no released copy to compare against, nothing is excused.
    assert student_safety_findings("import io\n", None) == ["denied import: io"]
    # A line that is in the release but was not flagged there excuses nothing:
    # here the release only mentions the import inside a string.
    released_doc = 'doc = """\nfrom os import (\n"""\n'
    assert student_safety_findings("from os import (\n    path,\n)\n", released_doc) == [
        "denied import: os"
    ]
    # The template's import on a line of the student's own is theirs.
    assert student_safety_findings("import io, os\n", released) == [
        "denied import: io",
        "denied import: os",
    ]


# -- the backfill ------------------------------------------------------------------


def _render_ok(sub_id, code: bool):
    with dbmod.get_sessionmaker()() as db:
        sub = db.get(Submission, sub_id)
        art = Artifact(
            kind="render", content_type="text/html", sha256="x" * 64, size=1, storage_key="r"
        )
        db.add(art)
        db.flush()
        sub.render_artifact_id = art.id
        db.add(
            GraderRun(
                submission_id=sub.id,
                kind=RunKind.render,
                status=RunStatus.succeeded,
                results={"code": True} if code else {},
            )
        )
        db.commit()


def _clear_queue():
    with dbmod.get_sessionmaker()() as db:
        for r in db.scalars(select(GraderRun).where(GraderRun.status == RunStatus.queued)):
            r.status = RunStatus.succeeded
        db.commit()


def test_backfill_rerenders_old_renders_one_at_a_time(client, seed, monkeypatch):
    csrf = login(client, "prof")
    _publish(client, csrf, seed, questions=Q2)
    client.cookies.clear()
    old = uuid.UUID(_submit(client, seed, "f00abc1").json()["id"])
    new = uuid.UUID(_submit(client, seed, "f00xyz9").json()["id"])
    _clear_queue()  # the runs the submissions queued; no worker in tests
    _render_ok(old, code=False)
    _render_ok(new, code=True)

    with dbmod.get_sessionmaker()() as db:
        assert [s.id for s in rerender.pending(db)] == [old]

    # Stand in for the worker: whenever trickle waits, finish what is queued.
    def worker_tick(_seconds):
        with dbmod.get_sessionmaker()() as db:
            for r in db.scalars(select(GraderRun).where(GraderRun.status == RunStatus.queued)):
                r.status, r.results = RunStatus.succeeded, {"code": True}
            db.commit()

    monkeypatch.setattr(rerender.time, "sleep", worker_tick)
    assert rerender.trickle(dbmod.get_sessionmaker(), echo=lambda *_: None) == 1
    with dbmod.get_sessionmaker()() as db:
        assert rerender.pending(db) == []


def test_backfill_waits_for_the_queue_and_skips_no_rerun_assignments(client, seed, monkeypatch):
    csrf = login(client, "prof")
    _publish(client, csrf, seed, questions=Q2)
    client.cookies.clear()
    sub = uuid.UUID(_submit(client, seed, "f00abc1").json()["id"])
    _render_ok(sub, code=False)  # the submission's own autograde run is still queued

    waits = []

    def worker_tick(_seconds):
        waits.append(1)
        _clear_queue()

    monkeypatch.setattr(rerender.time, "sleep", worker_tick)
    rerender.trickle(dbmod.get_sessionmaker(), echo=lambda *_: None, limit=1)
    assert waits, "queued a render while a student's run was waiting"

    _set(seed, render=False)
    with dbmod.get_sessionmaker()() as db:
        a = db.get(Assignment, seed.assignment_id)
        assert a.settings["render"] is False
        assert rerender.pending(db) == []
