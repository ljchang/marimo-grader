"""Grading from the student's own outputs: the session snapshot sent with an
attempt, rendered without running anything, and the instructor backfill.

The fixture is a small synthetic notebook and the session ``marimo export
session`` wrote for it (marimo 0.25.2, the version the worker pins).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from grader import config
from grader import db as dbmod
from grader.models import (
    Artifact,
    GraderRun,
    RunKind,
    RunStatus,
    Submission,
)
from grader.services.artifacts import store
from tests.conftest import login, notebook_token
from tests.test_private_assignments import _patch

FIXTURE = Path(__file__).parent / "fixtures" / "snapshot"
NOTEBOOK = (FIXTURE / "notebook.py").read_text()
SESSION = (FIXTURE / "session.json").read_text()
# What the last cell printed when the student ran it.
PRINTED = "largest beta: 1.25"


def _submit(client, seed, netid="f00abc1", *, notebook=NOTEBOOK, snapshot=SESSION, **extra):
    body = {
        "assignment_version_id": str(seed.version_id),
        "question_id": "glm-q01",
        "notebook": notebook,
        **extra,
    }
    if snapshot is not None:
        body["snapshot"] = snapshot
    r = client.post(
        "/api/v1/submissions",
        headers={"Authorization": f"Bearer {notebook_token(client, netid)}"},
        json=body,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _work(kind: RunKind = RunKind.snapshot) -> list[GraderRun]:
    """Process every queued run of ``kind``, the way the worker would."""
    from grader.worker.main import process

    done = []
    with dbmod.get_sessionmaker()() as db:
        runs = db.scalars(
            select(GraderRun).where(GraderRun.kind == kind, GraderRun.status == RunStatus.queued)
        ).all()
        for run in runs:
            process(db, run)
            done.append(run)
        for r in done:
            db.refresh(r)
        db.expunge_all()
    return done


def _sub(sub_id: str) -> Submission:
    with dbmod.get_sessionmaker()() as db:
        sub = db.get(Submission, uuid.UUID(sub_id))
        db.expunge(sub)
        return sub


def _artifact(art_id) -> tuple[str, bytes]:
    with dbmod.get_sessionmaker()() as db:
        art = db.get(Artifact, art_id)
        return art.kind, store().get(art)


def _as_prof(client, sub_id: str) -> dict:
    login(client, "prof")
    j = client.get(f"/api/v1/submissions/{sub_id}").json()
    client.cookies.clear()
    return j


# -- the snapshot travels with the attempt ----------------------------------------


def test_snapshot_is_stored_with_the_attempt(client, seed):
    sub_id = _submit(client, seed)
    sub = _sub(sub_id)
    kind, data = _artifact(sub.snapshot_artifact_id)
    assert kind == "snapshot" and data.decode() == SESSION
    assert sub.client_meta["snapshot"] == f"{len(SESSION.encode())} bytes"


@pytest.mark.parametrize(
    "snapshot, why",
    [
        ("{not json", "dropped: not JSON"),
        ('{"version": "1"}', "dropped: not a marimo session"),
    ],
)
def test_a_bad_snapshot_is_dropped_never_the_attempt(client, seed, snapshot, why):
    sub = _sub(_submit(client, seed, snapshot=snapshot))
    assert sub.snapshot_artifact_id is None
    assert sub.client_meta["snapshot"] == why


def test_an_oversized_snapshot_is_dropped(client, seed, monkeypatch):
    monkeypatch.setenv("GRADER_MAX_SNAPSHOT_BYTES", "100")
    config.get_settings.cache_clear()
    sub = _sub(_submit(client, seed))
    assert sub.snapshot_artifact_id is None
    assert (
        sub.client_meta["snapshot"].startswith("dropped:")
        and "100 limit" in (sub.client_meta["snapshot"])
    )


# -- the worker renders it, executing nothing -------------------------------------


def test_render_from_the_snapshot(client, seed):
    pytest.importorskip("marimo")
    sub_id = _submit(client, seed)
    [run] = _work()
    assert run.status == RunStatus.succeeded, run.error
    assert run.results["snapshot"] == "submitted"
    assert (run.results["matched"], run.results["total"]) == (5, 5)
    sub = _sub(sub_id)
    kind, html = _artifact(sub.render_artifact_id)
    assert kind == "render-snapshot"
    assert PRINTED in html.decode()

    j = _as_prof(client, sub_id)
    assert j["render_url"] == f"/api/v1/submissions/{sub_id}/render"
    assert j["render_info"] == {
        "source": "snapshot",
        "snapshot": "submitted",
        "matched": 5,
        "total": 5,
    }


def test_a_cell_edited_after_it_ran_loses_only_its_output(client, seed):
    pytest.importorskip("marimo")
    edited = NOTEBOOK.replace(
        'print("largest beta:", max(betas))', 'print("smallest beta:", min(betas))'
    )
    assert edited != NOTEBOOK
    sub_id = _submit(client, seed, notebook=edited)
    [run] = _work()
    assert (run.results["matched"], run.results["total"]) == (4, 5)
    html = _artifact(_sub(sub_id).render_artifact_id)[1].decode()
    assert "smallest beta" in html  # the code is shown
    assert PRINTED not in html  # its stale output is not
    assert "A synthetic assignment" in html  # the untouched cells keep theirs


def test_snapshot_only_when_the_assignment_does_not_rerun(client, seed):
    pytest.importorskip("marimo")
    assert _patch(client, seed, autograde=False, render=False).status_code == 200
    sub_id = _submit(client, seed)
    _work()
    j = _as_prof(client, sub_id)
    assert j["renders"] is False
    assert j["render_url"] and j["render_info"]["source"] == "snapshot"


def test_a_finished_rerun_is_not_replaced(client, seed):
    pytest.importorskip("marimo")
    sub_id = _submit(client, seed)
    with dbmod.get_sessionmaker()() as db:
        rerun = store().put(db, b"<html>re-run</html>", kind="render", content_type="text/html")
        db.get(Submission, uuid.UUID(sub_id)).render_artifact_id = rerun.id
        db.commit()
        rerun_id = rerun.id
    [run] = _work()
    assert run.status == RunStatus.succeeded and run.results["shown"] is False
    assert _sub(sub_id).render_artifact_id == rerun_id


def test_nothing_to_render_is_not_a_failure(client, seed):
    sub_id = _submit(client, seed, snapshot=None)
    [run] = _work()
    assert run.status == RunStatus.succeeded
    assert run.results["snapshot"] is None and "skipped" in run.results
    assert _sub(sub_id).render_artifact_id is None


def test_failed_snapshot_render_does_not_explain_a_failed_grade(client, seed):
    from grader.api.grading import _last_error

    sub_id = _submit(client, seed)
    with dbmod.get_sessionmaker()() as db:
        sid = uuid.UUID(sub_id)
        now = datetime.now(UTC)
        db.add(
            GraderRun(
                submission_id=sid,
                kind=RunKind.autograde,
                status=RunStatus.failed,
                error="SyntaxError: autograde",
                finished_at=now,
            )
        )
        db.add(
            GraderRun(
                submission_id=sid,
                kind=RunKind.snapshot,
                status=RunStatus.failed,
                error="snapshot render failed",
                finished_at=now + timedelta(seconds=5),
            )
        )
        db.commit()
        assert _last_error(db.get(Submission, sid)) == "SyntaxError: autograde"


# -- instructor backfill -----------------------------------------------------------


def _attach(client, sub_id, netid="prof", **body):
    csrf = login(client, netid)
    r = client.post(
        f"/api/v1/submissions/{sub_id}/outputs", json=body, headers={"X-CSRF-Token": csrf}
    )
    client.cookies.clear()
    return r


def test_instructor_attaches_a_snapshot(client, seed):
    pytest.importorskip("marimo")
    sub_id = _submit(client, seed, snapshot=None)
    _work()  # nothing to render yet
    r = _attach(client, sub_id, snapshot=SESSION, note="re-run locally")
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "snapshot-attached"
    [run] = _work()
    assert run.results["snapshot"] == "attached" and run.results["note"] == "re-run locally"
    j = _as_prof(client, sub_id)
    assert j["render_info"]["snapshot"] == "attached"
    assert j["render_info"]["matched"] == 5


def test_instructor_attaches_a_render(client, seed):
    sub_id = _submit(client, seed, snapshot=None)
    r = _attach(client, sub_id, html="<html><body>rendered elsewhere</body></html>")
    assert r.status_code == 201 and r.json()["status"] == "succeeded"
    j = _as_prof(client, sub_id)
    assert j["render_info"] == {"source": "attached", "snapshot": "attached-html"}
    login(client, "prof")
    assert b"rendered elsewhere" in client.get(j["render_url"]).content


@pytest.mark.parametrize(
    "netid, body, status",
    [
        ("ta1", {"html": "<html></html>"}, 403),
        ("f00abc1", {"html": "<html></html>"}, 404),
        ("prof", {}, 422),
        ("prof", {"html": "<p/>", "snapshot": SESSION}, 422),
        ("prof", {"snapshot": "{}"}, 422),
    ],
)
def test_attach_is_for_instructors_with_one_thing(client, seed, netid, body, status):
    sub_id = _submit(client, seed, snapshot=None)
    assert _attach(client, sub_id, netid, **body).status_code == status


def test_attach_outputs_cli_finds_the_latest_attempt(client, seed, monkeypatch, tmp_path, capsys):
    from contextlib import nullcontext

    from grader import cli

    _submit(client, seed, snapshot=None)
    newest = _submit(client, seed, snapshot=None)
    token = notebook_token(client, "prof")
    monkeypatch.setattr(cli.httpx, "Client", lambda **kw: nullcontext(client))
    snap = tmp_path / "student.py.json"
    snap.write_text(SESSION)
    cli.main(
        [
            "attach-outputs",
            "--server",
            "http://testserver",
            "--offering",
            "neuroimaging/2026-fall",
            "--assignment",
            "glm",
            "--netid",
            "f00abc1",
            "--snapshot",
            str(snap),
            "--note",
            "re-run locally",
            "--token",
            token,
        ]
    )
    out = capsys.readouterr().out
    assert f"attempt 2 ({newest})" in out and "snapshot-attached" in out
    kind, data = _artifact(_sub(newest).snapshot_artifact_id)
    assert kind == "snapshot-attached" and data.decode() == SESSION


def test_attach_outputs_cli_needs_the_assignment_with_a_netid():
    from grader import cli

    with pytest.raises(SystemExit):
        cli.main(["attach-outputs", "--server", "x", "--netid", "f00abc1", "--html", "a.html"])


def test_cells_with_identical_code_keep_their_own_outputs():
    """marimo matches outputs by code hash alone; two cells with the same code must
    not collapse onto one, and an empty cell is not a lost output."""
    pytest.importorskip("marimo")
    import json

    from grader.worker.snapshot_render import render

    session = json.loads((FIXTURE / "duplicates.session.json").read_text())
    html, matched, total = render(FIXTURE / "duplicates.py", session)
    assert (matched, total) == (3, 3)  # the empty fourth cell is not counted
    assert "run 1" in html and "run 2" in html
