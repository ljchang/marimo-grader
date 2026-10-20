"""Publishing from the web page: the instructor notebook alone, previewed first."""

from __future__ import annotations

import io

import pytest

from tests.conftest import login

pytest.importorskip("mograder.grading.cells")

NB = """# /// script
# dependencies = ["marimo"]
# ///
import marimo
app = marimo.App()

@app.cell
def _():
    # === MOGRADER: MARKS ===
    _marks = {"q1": 5, "q2": 5}
    return

@app.cell
def _():
    ### BEGIN SOLUTION
    x = 41 + 1
    ### END SOLUTION
    return (x,)

@app.cell
def _(check, x):
    check("q1: The answer", [x == 42])
    return
"""


def _post(client, seed, csrf, what, text):
    return client.post(
        f"/api/v1/offerings/{seed.offering_id}/assignments/{seed.assignment_id}/versions/{what}",
        files={"instructor_notebook": ("glm.py", io.BytesIO(text.encode()), "text/x-python")},
        headers={"X-CSRF-Token": csrf},
    )


def test_preview_then_publish(client, seed):
    csrf = login(client, "prof")
    p = _post(client, seed, csrf, "preview", NB).json()
    # The seed has version 1 with glm-q01 and glm-q05; this notebook replaces them.
    assert p["version"] == 2 and not p["unchanged"]
    assert sorted(p["added"]) == ["q1", "q2"] and sorted(p["removed"]) == ["glm-q01", "glm-q05"]
    modes = {q["qid"]: q["grading_mode"] for q in p["questions"]}
    assert modes == {"q1": "auto", "q2": "manual"}  # q2 has no check(): graded by hand
    assert "41 + 1" not in p["student_notebook"]

    r = _post(client, seed, csrf, "from-notebook", NB)
    assert r.status_code == 201, r.text
    assert r.json()["version"] == 2

    again = _post(client, seed, csrf, "preview", NB).json()
    assert again["unchanged"] and again["version"] == 2 and again["added"] == []

    more = _post(client, seed, csrf, "preview", NB.replace('"q2": 5', '"q2": 10')).json()
    assert more["version"] == 3
    assert more["changed"] == [{"qid": "q2", "what": ["points 5 → 10"]}]


@pytest.mark.parametrize(
    "text, code",
    [
        (NB.replace("    ### END SOLUTION\n", ""), "bad_markers"),
        (NB.replace('_marks = {"q1": 5, "q2": 5}', "pass"), "no_marks"),
    ],
)
def test_refused_where_publishing_would_be(client, seed, text, code):
    csrf = login(client, "prof")
    for what in ("preview", "from-notebook"):
        r = _post(client, seed, csrf, what, text)
        assert r.status_code == 422 and r.json()["error"]["code"] == code, r.text


def test_instructors_only(client, seed):
    csrf = login(client, "ta1")
    assert _post(client, seed, csrf, "preview", NB).status_code == 403
