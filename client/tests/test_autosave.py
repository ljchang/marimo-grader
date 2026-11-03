"""The student's own outputs, captured without them doing anything: the session
snapshot that goes with each submission, and the autosave that starts at sign-in."""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path

import pytest

from marimo_grader_client import Grader, autosave, storage
from marimo_grader_client.notebook import (
    read_assignment_metadata,
    read_session_snapshot,
    session_snapshot_path,
)
from marimo_grader_client.storage import _state
from marimo_grader_client.storage._fs import LocalFS
from marimo_grader_client.storage._mount import Mount
from marimo_grader_client.widget import GraderWidget

NOTEBOOK = """# /// script
# grader-server = "https://grader.example"
# grader-offering-id = "off-1"
# grader-assignment = "glm"
# grader-assignment-id = "33333333-3333-3333-3333-333333333333"
# grader-assignment-version = "v-1"
# ///
import marimo
app = marimo.App()
"""
SESSION = {"version": "1", "metadata": {"marimo_version": "0.25.2"}, "cells": []}


def _jwt(sub="f00abc1"):
    def seg(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    return f"{seg({'alg': 'EdDSA'})}.{seg({'sub': sub, 'exp': int(time.time()) + 3600})}.sig"


@pytest.fixture
def nb(tmp_path):
    p = tmp_path / "assignment.py"
    p.write_text(NOTEBOOK)
    snap = session_snapshot_path(p)
    snap.parent.mkdir(parents=True)
    snap.write_text(json.dumps(SESSION))
    return p


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in ("GRADER_RENDER", "GRADER_STORAGE_ROOT", "GRADER_AUTOSAVE", "GRADER_STORAGE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GRADER_RUNTIME", "local")
    autosave._reset_for_tests()
    _state.reset()
    yield
    autosave._reset_for_tests()
    _state.reset()


# -- the notebook names its assignment ----------------------------------------------


def test_slug_and_id_are_separate_keys_in_either_order():
    meta = read_assignment_metadata(NOTEBOOK)
    assert meta["assignment_slug"] == "glm"
    assert meta["assignment_id"] == "33333333-3333-3333-3333-333333333333"
    flipped = NOTEBOOK.replace(
        '# grader-assignment = "glm"\n# grader-assignment-id = "33333333-3333-3333-3333-333333333333"\n',
        '# grader-assignment-id = "33333333-3333-3333-3333-333333333333"\n# grader-assignment = "glm"\n',
    )
    assert flipped != NOTEBOOK
    assert read_assignment_metadata(flipped)["assignment_id"].startswith("3333")


# -- the snapshot goes with Submit --------------------------------------------------


def test_snapshot_path_is_next_to_the_notebook(tmp_path):
    assert session_snapshot_path(tmp_path / "nb.py") == (
        tmp_path / "__marimo__" / "session" / "nb.py.json"
    )


def test_read_snapshot_waits_for_a_fresh_write(nb):
    snap = session_snapshot_path(nb)
    newer = {**SESSION, "cells": [{"id": "a"}]}
    calls = []

    def sleep(_s):
        calls.append(_s)
        if len(calls) == 2:  # marimo writes the newest outputs a moment after the click
            snap.write_text(json.dumps(newer))
            t = time.time() + 5
            import os

            os.utime(snap, (t, t))

    text, note = read_session_snapshot(snap, wait=2.5, poll=0.25, sleep=sleep)
    assert json.loads(text) == newer and note.endswith("bytes")
    assert len(calls) == 3  # returned early: two polls, then one to let the write settle


def test_read_snapshot_never_raises(nb, tmp_path):
    def nosleep(_s):
        return None

    assert read_session_snapshot(tmp_path / "missing.json", wait=0, sleep=nosleep) == (
        None,
        "no session snapshot",
    )
    snap = session_snapshot_path(nb)
    text, note = read_session_snapshot(snap, wait=0, max_bytes=10, sleep=nosleep)
    assert text is None and note.startswith("skipped:")
    snap.write_text('{"cells": [')  # caught mid-write, and it stays that way
    assert read_session_snapshot(snap, wait=0, sleep=nosleep) == (
        None,
        "unreadable session snapshot",
    )


def test_submit_sends_the_snapshot_by_message_not_in_the_payload(nb):
    g = Grader(notebook_path=nb)
    w = g.submit_button("glm-q01")
    assert isinstance(w, GraderWidget)
    assert "snapshot" not in w.payload  # never in a synced trait (or the session file)
    sent = []
    w.send = lambda content, buffers=None: sent.append(content)
    w._extra_factory = lambda: g.snapshot_extra(wait=0)
    w._on_custom_msg(w, {"type": "refresh"}, [])
    [msg] = sent
    assert msg["type"] == "payload"
    assert json.loads(msg["extra"]["snapshot"]) == SESSION
    assert msg["extra"]["client"]["snapshot"].endswith("bytes")
    assert "snapshot" not in w.payload and w.payload["notebook"] == NOTEBOOK


def test_submit_without_a_snapshot_says_why(nb):
    session_snapshot_path(nb).unlink()
    extra = Grader(notebook_path=nb).snapshot_extra(wait=0)
    assert "snapshot" not in extra and extra["client"]["snapshot"] == "no session snapshot"


def test_a_failing_extra_never_blocks_the_submit():
    w = GraderWidget(mode="submit", extra_factory=lambda: 1 / 0)
    sent = []
    w.send = lambda content, buffers=None: sent.append(content)
    w._on_custom_msg(w, {"type": "refresh"}, [])
    assert sent == [{"type": "payload", "extra": {}}]


# -- autosave: what one check uploads -------------------------------------------------


class Counting:
    """A /private mount that counts uploads."""

    def __init__(self, root: Path):
        self.m = Mount("/private", "users/me/", "rw", LocalFS(root), root / ".cache")
        self.puts: list[str] = []

    def put_bytes(self, rel, data):
        self.puts.append(rel)
        self.m.put_bytes(rel, data)

    def __getattr__(self, name):
        return getattr(self.m, name)


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


def _saver(nb, root, **kw):
    mount, clock = Counting(root), Clock()
    saver = autosave.Autosaver(
        mount, "glm", nb, session_snapshot_path(nb), clock=clock, history_every=600, **kw
    )
    return saver, mount, clock


def test_uploads_only_what_changed(nb, tmp_path):
    saver, mount, clock = _saver(nb, tmp_path / "bucket")
    assert saver.tick()
    assert sorted(p for p in mount.puts if "/history/" not in p) == [
        "glm/.autosave/notebook.py",
        "glm/.autosave/session.json",
    ]
    assert mount.get_bytes("glm/.autosave/notebook.py").decode() == NOTEBOOK
    assert saver.status() == {"on": True, "saved_at": clock.t, "error": None}

    mount.puts.clear()
    clock.t += 45
    assert not saver.tick()  # nothing changed: nothing sent
    assert mount.puts == []

    nb.write_text(NOTEBOOK + "x = 1\n")
    clock.t += 45
    assert saver.tick()
    assert mount.puts == ["glm/.autosave/notebook.py"]  # the snapshot did not change


def test_history_is_throttled_and_capped(nb, tmp_path):
    saver, mount, clock = _saver(nb, tmp_path / "bucket", keep=3)

    def versions():
        return sorted({k.split("/")[3] for k in mount.ls("glm/.autosave/history")})

    saver.tick()
    assert len(versions()) == 1
    for i in range(3):  # edits every 45 s: the live copy follows, history does not
        nb.write_text(NOTEBOOK + f"x = {i}\n")
        clock.t += 45
        saver.tick()
    assert len(versions()) == 1
    for i in range(5):  # ten minutes apart: one version each, the oldest dropped
        nb.write_text(NOTEBOOK + f"y = {i}\n")
        clock.t += 600
        saver.tick()
    kept = versions()
    assert len(kept) == 3
    assert kept[-1] == time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(clock.t))
    newest = f"glm/.autosave/history/{kept[-1]}"
    assert sorted(mount.ls(newest)) == [f"{newest}/notebook.py", f"{newest}/session.json"]
    assert mount.get_bytes(f"{newest}/notebook.py").decode().endswith("y = 4\n")


def test_a_snapshot_caught_mid_write_waits_for_the_next_check(nb, tmp_path):
    session_snapshot_path(nb).write_text('{"cells": [')
    saver, mount, _ = _saver(nb, tmp_path / "bucket")
    saver.tick()
    assert not mount.exists("glm/.autosave/session.json")
    assert mount.exists("glm/.autosave/notebook.py")


def test_a_failed_upload_is_retried_with_a_fresh_mount(nb, tmp_path):
    good = Counting(tmp_path / "bucket")
    opened = []

    def open_private():
        opened.append(1)
        if len(opened) == 1:
            raise ConnectionError("R2 unreachable")
        return good

    saver = autosave.Autosaver(open_private, "glm", nb, session_snapshot_path(nb))
    with pytest.raises(ConnectionError):
        saver.tick()
    assert saver.status()["error"].startswith("ConnectionError") and saver.saved_at is None
    assert saver.tick()
    assert saver.status()["error"] is None and len(opened) == 2


# -- autosave: when it starts --------------------------------------------------------


def test_starts_once_per_kernel_and_saves_right_away(nb, tmp_path, monkeypatch):
    mount = Counting(tmp_path / "bucket")
    monkeypatch.setattr(autosave, "_private_mount", lambda token, offering: lambda: mount)
    first = autosave.start(notebook=nb)
    assert first is not None and autosave.start(notebook=nb) is first
    deadline = time.time() + 5
    while not mount.exists("glm/.autosave/session.json") and time.time() < deadline:
        time.sleep(0.05)
    assert mount.exists("glm/.autosave/session.json")
    assert first._thread.daemon


@pytest.mark.parametrize(
    "env, why",
    [
        ({"GRADER_RENDER": "1"}, "grader render"),
        ({"GRADER_RUNTIME": "wasm"}, "browser (no storage)"),
        ({"GRADER_STORAGE_ROOT": "/tmp/x"}, "local storage root"),
        ({"GRADER_AUTOSAVE": "0"}, "GRADER_AUTOSAVE is off"),
    ],
)
def test_skipped_where_there_is_nothing_to_protect(nb, monkeypatch, env, why):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert autosave.disabled_reason(nb) == why
    assert autosave.start(notebook=nb) is None


def test_skipped_for_a_notebook_without_an_assignment(tmp_path):
    p = tmp_path / "scratch.py"
    p.write_text("import marimo\n")
    assert autosave.start(notebook=p) is None


def test_start_never_raises(nb, monkeypatch):
    monkeypatch.setattr(autosave, "read_assignment_metadata", lambda src: 1 / 0)
    assert autosave.start(notebook=nb) is None


def test_the_signin_token_starts_it(nb, monkeypatch):
    started = []
    monkeypatch.setattr(autosave, "start", lambda token=None, **kw: started.append((token, kw)))
    g = Grader(notebook_path=nb)
    w = g.signin_button()
    w.send = lambda content, buffers=None: None
    w._on_custom_msg(w, {"type": "token", "token": "tok", "netid": "f00abc1"}, [])
    [(token, kw)] = started
    assert token.value == "tok" and token.server == "https://grader.example"
    assert kw == {"offering": "off-1", "notebook": nb}


def test_storage_connect_starts_it(monkeypatch):
    started = []
    monkeypatch.setattr(autosave, "start", lambda token=None, **kw: started.append(token))
    monkeypatch.setattr(_state, "adopt", lambda token, offering=None: None)
    monkeypatch.setattr(_state, "session", lambda: None)

    class Button:
        value = {"server": "https://grader.example"}
        token = _jwt()

    assert storage.connect(Button())
    assert [t.value for t in started] == [Button.token]


def test_the_widget_reports_autosave_status(nb, tmp_path, monkeypatch):
    w = GraderWidget(mode="signin")
    sent = []
    w.send = lambda content, buffers=None: sent.append(content)
    w._on_custom_msg(w, {"type": "autosave?"}, [])
    assert sent == [{"type": "autosave", "on": False}]
    mount = Counting(tmp_path / "bucket")
    monkeypatch.setattr(autosave, "_private_mount", lambda token, offering: lambda: mount)
    saver = autosave.start(notebook=nb)
    saver.stop()
    saver.tick()
    w._on_custom_msg(w, {"type": "autosave?"}, [])
    assert sent[-1]["on"] is True and sent[-1]["saved_at"] == saver.saved_at
    assert "autosave" not in w.get_state()  # status is never part of the button's value
