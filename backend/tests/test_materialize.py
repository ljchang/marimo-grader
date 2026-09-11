from grader.worker.materialize import rewrite_dependencies

SRC = """# /// script
# requires-python = ">=3.11"
# dependencies = ["marimo", "numpy>=2", "grader-client", "mograder"]
# grader-server = "http://localhost:8000"
# ///
import marimo
"""


def test_rewrites_client_and_pins_mograder(monkeypatch):
    monkeypatch.setenv("GRADER_CLIENT_REQUIREMENT", "grader-client @ file:///app/client")
    out = rewrite_dependencies(SRC)
    line = next(line_ for line_ in out.splitlines() if line_.startswith("# dependencies"))
    assert '"marimo"' in line and '"numpy>=2"' in line
    assert '"grader-client @ file:///app/client"' in line
    assert '"mograder==' in line
    assert '"grader-client"' not in line.replace("grader-client @", "")
    assert '# grader-server = "http://localhost:8000"' in out  # other keys untouched


def test_adds_missing_requirements():
    out = rewrite_dependencies('# /// script\n# dependencies = ["numpy"]\n# ///\n')
    assert "grader-client" in out and "mograder" in out


def test_no_block_is_untouched():
    assert rewrite_dependencies("import marimo\n") == "import marimo\n"
