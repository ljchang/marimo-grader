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


# Node script for test_signin_button_syncs_outcomes_only. It builds the
# triple-quote marker at runtime so this module's own string stays intact.
_NODE_SET_STATUS = r"""
const Q3 = '"'.repeat(3);
const src = require("fs").readFileSync(process.argv[1], "utf8");
const js = src.split("_ESM = r" + Q3)[1].split(Q3)[0];
const pick = (name) => {
  const i = js.indexOf(name);
  return js.slice(i, js.indexOf("\n}\n", i) + 2);
};
eval(pick("function setModel(") + "\n" + pick("const SIGNIN_SYNCED") + "\n" + pick("function setStatus("));
const fake = (mode) => {
  const st = { mode, status: "idle", message: "" };
  let saves = 0;
  return { get: (k) => st[k], set: (k, v) => { st[k] = v; }, save_changes: () => saves++, st, saves: () => saves };
};
const out = {};
const s = fake("signin");
for (const [st, msg] of [["pending", "waiting"], ["error", "Could not reach"], ["approved", ""]]) setStatus(s, st, msg);
out.signin = { saves: s.saves(), status: s.st.status, message: s.st.message };
const m = fake("submit");
for (const st of ["pending", "submitting", "error"]) setStatus(m, st, "x");
out.submit = { saves: m.saves(), status: m.st.status };
console.log(JSON.stringify(out));
"""


def test_signin_button_syncs_outcomes_only():
    """Each synced change reruns every cell that depends on the button (cached
    ones included), so a sign-in's progress stays in the widget's own display."""
    import json
    import shutil
    import subprocess

    import marimo_grader_client.widget as widget_module

    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    out = subprocess.run(
        [node, "-e", _NODE_SET_STATUS, widget_module.__file__],
        capture_output=True,
        text=True,
        check=True,
    )
    result = json.loads(out.stdout)
    assert result["signin"] == {"saves": 1, "status": "approved", "message": ""}
    assert result["submit"] == {"saves": 3, "status": "error"}  # other modes unchanged
