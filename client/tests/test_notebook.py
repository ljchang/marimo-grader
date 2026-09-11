import json

from grader_client.notebook import (
    build_payload,
    collect_check_results,
    read_assignment_metadata,
    read_notebook_source,
    script_block,
)

TOP_LEVEL = """import marimo

# /// script
# requires-python = ">=3.11"
# dependencies = ["marimo", "grader-client"]
# mograder-assignment = "week03-glm"
# mograder-cell-hashes = "abc123,def456"
# mograder-hidden-tests = true
# mograder-type = "student"
# grader-assignment-version = "11111111-1111-1111-1111-111111111111"
# grader-offering-id = "22222222-2222-2222-2222-222222222222"
# grader-assignment-id = "33333333-3333-3333-3333-333333333333"
# grader-server = "https://grader.example.edu"
# ///

app = marimo.App()
"""

TABLE = """import marimo

# /// script
# requires-python = ">=3.11"
# dependencies = ["marimo"]
# mograder-assignment = "week03-glm"
#
# [tool.grader]
# assignment-version = "11111111-1111-1111-1111-111111111111"
# offering-id = "22222222-2222-2222-2222-222222222222"
# assignment-id = "33333333-3333-3333-3333-333333333333"
# server = "https://grader.example.edu/"
# ///

app = marimo.App()
"""


def test_script_block_strips_comment_prefix():
    body = script_block(TOP_LEVEL)
    assert body is not None
    assert 'mograder-assignment = "week03-glm"' in body
    assert "# " not in body.splitlines()[0]
    assert script_block("import marimo\napp = marimo.App()\n") is None


def test_top_level_keys():
    meta = read_assignment_metadata(TOP_LEVEL)
    assert meta["assignment_version_id"] == "11111111-1111-1111-1111-111111111111"
    assert meta["offering_id"] == "22222222-2222-2222-2222-222222222222"
    assert meta["assignment_id"] == "33333333-3333-3333-3333-333333333333"
    assert meta["server"] == "https://grader.example.edu"
    assert meta["mograder_assignment"] == "week03-glm"
    assert meta["mograder_cell_hashes"] == ["abc123", "def456"]
    assert meta["mograder_hidden_tests"] is True
    assert meta["mograder_type"] == "student"


def test_tool_grader_table_keys():
    meta = read_assignment_metadata(TABLE)
    assert meta["assignment_version_id"] == "11111111-1111-1111-1111-111111111111"
    assert meta["offering_id"] == "22222222-2222-2222-2222-222222222222"
    assert meta["assignment_id"] == "33333333-3333-3333-3333-333333333333"
    assert meta["server"] == "https://grader.example.edu/"
    assert meta["mograder_assignment"] == "week03-glm"


def test_table_wins_over_top_level():
    src = TOP_LEVEL.replace(
        "# ///\n",
        '# [tool.grader]\n# assignment-version = "from-table"\n# ///\n',
        1,
    )
    meta = read_assignment_metadata(src)
    assert meta["assignment_version_id"] == "from-table"
    assert meta["server"] == "https://grader.example.edu"


def test_loose_parser_handles_invalid_toml():
    src = (
        "# /// script\n"
        "# this is = not = toml\n"
        '# grader-server = "https://loose.example.edu"\n'
        "# [tool.grader]\n"
        '# offering-id = "off-1"\n'
        "# ///\n"
    )
    meta = read_assignment_metadata(src)
    assert meta["server"] == "https://loose.example.edu"
    assert meta["offering_id"] == "off-1"


def test_metadata_empty_when_missing():
    assert read_assignment_metadata(None) == {}
    assert read_assignment_metadata("") == {}
    assert read_assignment_metadata("import marimo\n") == {}


def test_read_notebook_source_explicit_and_missing(tmp_path):
    nb = tmp_path / "nb.py"
    nb.write_text(TOP_LEVEL)
    assert read_notebook_source(nb) == TOP_LEVEL
    assert read_notebook_source(tmp_path / "missing.py") is None


def test_read_notebook_source_from_main_file(tmp_path, monkeypatch):
    import __main__

    nb = tmp_path / "nb.py"
    nb.write_text("print('hi')\n")
    monkeypatch.delenv("GRADER_NOTEBOOK_PATH", raising=False)
    monkeypatch.setattr(__main__, "__file__", str(nb), raising=False)
    assert read_notebook_source() == "print('hi')\n"


def test_read_notebook_source_from_env(tmp_path, monkeypatch):
    nb = tmp_path / "env.py"
    nb.write_text("x = 1\n")
    monkeypatch.setenv("GRADER_NOTEBOOK_PATH", str(nb))
    assert read_notebook_source() == "x = 1\n"


def test_collect_check_results_sidecar(tmp_path, monkeypatch):
    sidecar = tmp_path / "checks.jsonl"
    rec = {
        "label": "Q1: shape",
        "status": "success",
        "details": [],
        "earned_weight": 2,
        "total_weight": 2,
    }
    sidecar.write_text(json.dumps(rec) + "\nnot json\n\n")
    monkeypatch.setenv("MOGRADER_SIDECAR_PATH", str(sidecar))
    assert collect_check_results() == [rec]
    monkeypatch.delenv("MOGRADER_SIDECAR_PATH")
    assert collect_check_results() == []
    assert collect_check_results(tmp_path / "nope.jsonl") == []


def test_build_payload_shape():
    p = build_payload("src", [{"label": "a"}], {"fig": "png"}, {"package": "grader-client"})
    assert p == {
        "notebook": "src",
        "check_results": [{"label": "a"}],
        "outputs": {"fig": "png"},
        "client": {"package": "grader-client"},
    }
    assert build_payload(None) == {"notebook": "", "check_results": [], "outputs": {}, "client": {}}
