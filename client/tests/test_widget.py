import pytest
import traitlets

from marimo_grader_client.widget import MODES, STATUSES, GraderWidget


def test_trait_defaults():
    w = GraderWidget()
    assert w.server == ""
    assert w.mode == "signin"
    assert w.assignment_version_id == ""
    assert w.question_id == ""
    assert w.offering_id == ""
    assert w.assignment_id == ""
    assert w.token == ""
    assert w.netid == ""
    assert w.payload == {}
    assert w.result == {}
    assert w.status == "idle"
    assert w.message == ""


def test_traits_are_synced():
    for name in (
        "server",
        "mode",
        "assignment_version_id",
        "question_id",
        "offering_id",
        "assignment_id",
        "payload",
        "result",
        "status",
        "message",
    ):
        assert GraderWidget.class_traits()[name].metadata.get("sync") is True


def test_token_is_never_a_synced_trait():
    """marimo hashes a UI element's value into downstream persistent-cache keys;
    a synced token would make every sign-in its own cache."""
    traits = GraderWidget.class_traits()
    assert "token" not in traits and "netid" not in traits
    import re

    writes = re.findall(r"setModel\([^;]*", GraderWidget._esm)
    assert writes and not [w for w in writes if "token" in w or "netid" in w]


def test_token_arrives_by_message_and_is_acknowledged(monkeypatch):
    w = GraderWidget(mode="signin")
    sent = []
    monkeypatch.setattr(w, "send", lambda content, buffers=None: sent.append(content))
    w._on_custom_msg(w, {"type": "token", "token": "tok-abc", "netid": "f00abc1"}, [])
    assert (w.token, w.netid) == ("tok-abc", "f00abc1")
    assert sent == [{"type": "token-ok"}]  # the browser flips status on this ack
    assert w.status == "idle"  # a kernel-side change would rerun nothing in marimo
    assert "tok-abc" not in str(w.get_state())  # the synced state stays token-free


def test_mode_and_status_are_validated():
    w = GraderWidget(mode="submit", status="done")
    assert w.mode == "submit"
    assert MODES == ("signin", "submit", "feedback")
    assert "error" in STATUSES
    with pytest.raises(traitlets.TraitError):
        GraderWidget(mode="bogus")
    with pytest.raises(traitlets.TraitError):
        w.status = "bogus"


def test_esm_and_css_present():
    js = GraderWidget._esm
    assert "export default" in js
    for path in ("/auth/device", "/auth/device/token", "/submissions", "/me/submissions"):
        assert path in js
    assert "Sign in with Dartmouth" in js
    assert "grader:${server}:token" in js
    assert ".grader-button" in GraderWidget._css


def test_custom_refresh_message_updates_payload():
    calls = []

    def factory():
        calls.append(1)
        return {"notebook": f"v{len(calls)}"}

    w = GraderWidget(mode="submit", payload_factory=factory)
    sent = []
    w.send = lambda content, buffers=None: sent.append(content)
    w._on_custom_msg(w, {"type": "refresh"}, [])
    assert w.payload == {"notebook": "v1"}
    assert sent == [{"type": "payload"}]
    w._on_custom_msg(w, {"type": "other"}, [])
    assert w.payload == {"notebook": "v1"}
