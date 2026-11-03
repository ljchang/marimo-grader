"""The student's own outputs go with every submission: marimo's session snapshot,
read when Submit is clicked and sent by message, never through a synced trait."""

from __future__ import annotations

import json
import os
import time

import pytest

from marimo_grader_client import Grader
from marimo_grader_client.notebook import read_session_snapshot, session_snapshot_path
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


@pytest.fixture
def nb(tmp_path):
    p = tmp_path / "assignment.py"
    p.write_text(NOTEBOOK)
    snap = session_snapshot_path(p)
    snap.parent.mkdir(parents=True)
    snap.write_text(json.dumps(SESSION))
    return p


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


def test_the_payload_trait_never_holds_the_snapshot_even_at_render(nb):
    w = Grader(notebook_path=nb).submit_button("glm-q01")
    assert set(w.payload) == {"notebook", "check_results", "outputs", "client"}
