import pytest

import grader_client
from grader_client import Grader, GraderWidget, _Html, check, render_check_html

SRC = """import marimo

# /// script
# grader-assignment-version = "meta-version"
# grader-offering-id = "meta-offering"
# grader-server = "https://meta.example.edu"
# ///
"""


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (
        "GRADER_SERVER",
        "GRADER_ASSIGNMENT_VERSION_ID",
        "GRADER_OFFERING_ID",
        "GRADER_ASSIGNMENT_ID",
        "GRADER_NOTEBOOK_PATH",
        "MOGRADER_SIDECAR_PATH",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def no_mograder(monkeypatch):
    monkeypatch.setattr(grader_client, "_mograder_check", lambda: None)


def test_argument_beats_metadata_beats_env(monkeypatch):
    monkeypatch.setenv("GRADER_SERVER", "https://env.example.edu")
    monkeypatch.setenv("GRADER_ASSIGNMENT_VERSION_ID", "env-version")
    monkeypatch.setenv("GRADER_OFFERING_ID", "env-offering")
    monkeypatch.setenv("GRADER_ASSIGNMENT_ID", "env-assignment")
    g = Grader(server="https://arg.example.edu/", source=SRC)
    assert g.server == "https://arg.example.edu"  # explicit argument, trailing slash removed
    assert g.assignment_version_id == "meta-version"  # from metadata
    assert g.offering_id == "meta-offering"
    assert g.assignment_id == "env-assignment"  # only the env var has it


def test_env_fallback_without_metadata(monkeypatch):
    monkeypatch.setenv("GRADER_SERVER", "https://env.example.edu")
    g = Grader(source="import marimo\n")
    assert g.server == "https://env.example.edu"
    assert g.assignment_version_id == ""


def test_widgets_carry_context(no_mograder):
    g = Grader(source=SRC, assignment_id="asg")
    s = g.signin_button()
    assert isinstance(s, GraderWidget)
    assert s.mode == "signin"
    assert s.server == "https://meta.example.edu"

    w = g.submit_button("q03", outputs={"plot": "..."})
    assert w.mode == "submit"
    assert w.question_id == "q03"
    assert w.assignment_version_id == "meta-version"
    assert w.payload["notebook"] == SRC
    assert w.payload["outputs"] == {"plot": "..."}
    assert w.payload["client"]["package"] == "grader-client"
    assert w.payload["client"]["version"] == grader_client.__version__

    f = g.feedback("q03")
    assert f.mode == "feedback"
    assert f.offering_id == "meta-offering"
    assert f.assignment_id == "asg"


def test_local_check_fallback_records_results(no_mograder):
    g = Grader(source=SRC)
    out = g.check("Q1: shapes", [(True, "x is wrong"), (False, "y is wrong", 2)])
    html = out._repr_html_()
    assert "Q1: shapes" in html
    assert "y is wrong" in html
    assert "x is wrong" not in html

    ok = g.check("Q2", [(True, "never shown")])
    assert "all checks passed" in ok._repr_html_()

    waiting = g.check("Q3", [])
    assert "waiting" in waiting._repr_html_()

    results = {r["label"]: r for r in g.check_results()}
    assert results["Q1: shapes"]["status"] == "partial"
    assert results["Q1: shapes"]["earned_weight"] == 1.0
    assert results["Q1: shapes"]["total_weight"] == 3.0
    assert results["Q1: shapes"]["details"] == ["y is wrong"]
    assert results["Q2"]["status"] == "success"
    assert results["Q3"]["status"] == "warn"

    # The submit payload carries the recorded checks.
    w = g.submit_button("q01")
    labels = {r["label"] for r in w.payload["check_results"]}
    assert labels == {"Q1: shapes", "Q2", "Q3"}


def test_check_all_failed_is_danger(no_mograder):
    g = Grader(source=SRC)
    g.check("Q9", [(False, "a"), (False, "b")])
    rec = g.check_results()[0]
    assert rec["status"] == "danger"
    assert rec["details"] == ["a", "b"]


def test_module_level_check_fallback(no_mograder):
    out = check("Standalone", [(False, "boom")])
    assert "boom" in out._repr_html_()
    assert "Standalone" in out._repr_html_()


def test_render_check_html_escapes():
    html = render_check_html({"label": "<b>", "status": "danger", "details": ["<i>"]})
    assert "&lt;b&gt;" in html
    assert "&lt;i&gt;" in html


def test_html_fallback_object():
    h = _Html("<p>x</p>")
    assert h._repr_html_() == "<p>x</p>"


def test_payload_refresh_rereads_notebook(tmp_path, no_mograder):
    nb = tmp_path / "nb.py"
    nb.write_text("v1\n")
    g = Grader(server="https://s", notebook_path=nb)
    w = g.submit_button("q1")
    assert w.payload["notebook"] == "v1\n"
    nb.write_text("v2\n")
    assert w.refresh_payload()["notebook"] == "v2\n"
    assert w.payload["notebook"] == "v2\n"
