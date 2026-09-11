"""Publish flow, public alias routes, version binding, idempotent submits, disabled auth."""

import io
import json

from grader import config
from grader.services.notebook_meta import inject_grader_keys, read_grader_keys
from tests.conftest import login, notebook_token

INSTRUCTOR = """# /// script
# dependencies = ["marimo", "numpy"]
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
    x = 1
    ### END SOLUTION
    return (x,)
"""

STUDENT = INSTRUCTOR.replace(
    "    ### BEGIN SOLUTION\n    x = 1\n    ### END SOLUTION\n", "    # YOUR CODE HERE\n"
)


def _publish(client, csrf, seed, *, questions, student=STUDENT, instructor=INSTRUCTOR):
    return client.post(
        f"/api/v1/offerings/{seed.offering_id}/assignments/{seed.assignment_id}/versions",
        files={
            "instructor_notebook": ("glm.py", io.BytesIO(instructor.encode()), "text/x-python"),
            "student_notebook": ("glm.py", io.BytesIO(student.encode()), "text/x-python"),
        },
        data={"questions": json.dumps(questions)},
        headers={"X-CSRF-Token": csrf},
    )


Q2 = [
    {"qid": "q1", "title": "One", "max_points": 5, "grading_mode": "auto", "check_keys": ["q1"]},
    {"qid": "q2", "title": "Two", "max_points": 5, "grading_mode": "manual"},
]


def test_publish_refuses_leaked_solutions(client, seed):
    csrf = login(client, "prof")
    r = _publish(client, csrf, seed, questions=Q2, student=INSTRUCTOR)
    assert r.status_code == 422 and r.json()["error"]["code"] == "solution_leak"


def test_publish_finalizes_student_notebook_and_is_idempotent(client, seed):
    csrf = login(client, "prof")
    r = _publish(client, csrf, seed, questions=Q2)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["version"] == 2 and body["unchanged"] is False  # seed already has v1
    assert body["student_url"].endswith("/a/neuroimaging/2026-fall/glm/student.py")

    # Publishing the same bytes again is a no-op.
    r2 = _publish(client, csrf, seed, questions=Q2)
    assert r2.status_code == 200 and r2.json()["unchanged"] is True
    assert r2.json()["version"] == 2

    # The served notebook carries the grader keys, including the version id.
    served = client.get("/a/neuroimaging/2026-fall/glm/student.py")
    assert served.status_code == 200 and served.headers["X-Grader-Version"] == "2"
    keys = read_grader_keys(served.text)
    assert keys["assignment-version"] == body["id"]
    assert keys["course"] == "neuroimaging" and keys["term"] == "2026-fall"
    assert keys["assignment"] == "glm" and keys["version"] == "2"
    assert "BEGIN SOLUTION" not in served.text
    # Older versions stay addressable.
    assert (
        client.get("/a/neuroimaging/2026-fall/glm/student.py?v=1").headers["X-Grader-Version"]
        == "1"
    )
    assert client.get("/a/neuroimaging/2026-fall/glm/student.py?v=9").status_code == 404


def test_public_metadata_and_molab_redirect(client, seed):
    csrf = login(client, "prof")
    _publish(client, csrf, seed, questions=Q2)
    client.cookies.clear()
    meta = client.get("/a/neuroimaging/2026-fall/assignments.json")
    assert meta.status_code == 200
    a = meta.json()["assignments"][0]
    assert a["slug"] == "glm" and a["version"] == 2 and a["points"] == 10.0
    assert [q["qid"] for q in a["questions"]] == ["q1", "q2"]
    r = client.get("/a/neuroimaging/2026-fall/glm/molab", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].startswith("https://molab.marimo.io/new/#code/")
    assert client.get("/a/neuroimaging/2026-fall/nope/molab").status_code == 404
    assert client.get("/a/neuroimaging/2027-fall/assignments.json").status_code == 404


def test_public_routes_can_be_disabled_per_offering(client, seed):
    from grader import db as dbmod
    from grader.models import Offering

    with dbmod.get_sessionmaker()() as db:
        o = db.get(Offering, seed.offering_id)
        o.settings = {**(o.settings or {}), "public_student_notebooks": False}
        db.commit()
    assert client.get("/a/neuroimaging/2026-fall/assignments.json").status_code == 404


def test_old_version_keeps_working_after_question_removed(client, seed):
    csrf = login(client, "prof")
    v2 = _publish(client, csrf, seed, questions=Q2).json()
    only_q1 = [Q2[0]]
    v3 = _publish(client, csrf, seed, questions=only_q1, instructor=INSTRUCTOR + "\n# v3\n").json()
    assert v3["version"] == 3
    client.cookies.clear()
    token = notebook_token(client, "f00abc1")
    # Student still on v2 submits q2, which v3 dropped.
    r = client.post(
        "/api/v1/submissions",
        headers={"Authorization": f"Bearer {token}"},
        json={"assignment_version_id": v2["id"], "question_id": "q2", "notebook": "# nb\n"},
    )
    assert r.status_code == 201, r.text
    assert (
        r.json()["version"] == 2 and r.json()["latest_version"] == 3 and r.json()["stale"] is True
    )
    # But q2 is unknown to v3.
    r = client.post(
        "/api/v1/submissions",
        headers={"Authorization": f"Bearer {token}"},
        json={"assignment_version_id": v3["id"], "question_id": "q2", "notebook": "# nb\n"},
    )
    assert r.status_code == 404 and r.json()["error"]["code"] == "unknown_question"


def test_client_submission_id_dedupes(client, seed):
    token = notebook_token(client, "f00abc1")
    body = {
        "assignment_version_id": str(seed.version_id),
        "question_id": "glm-q01",
        "notebook": "# nb\n",
        "client_submission_id": "click-1",
    }
    h = {"Authorization": f"Bearer {token}"}
    r1 = client.post("/api/v1/submissions", headers=h, json=body)
    r2 = client.post("/api/v1/submissions", headers=h, json=body)
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]
    assert r1.json()["duplicate"] is False and r2.json()["duplicate"] is True
    r3 = client.post(
        "/api/v1/submissions", headers=h, json={**body, "client_submission_id": "click-2"}
    )
    assert r3.json()["attempt_no"] == 2


def test_auth_disabled_mode(client, seed, monkeypatch):
    monkeypatch.setenv("GRADER_AUTH_MODE", "disabled")
    config.get_settings.cache_clear()
    try:
        r = client.get("/api/v1/auth/login")
        assert r.status_code == 503 and "not available yet" in r.text
        assert client.get("/api/health").json()["submissions_enabled"] is False
        assert (
            client.get("/api/v1/auth/dev-login?netid=x", follow_redirects=False).status_code == 404
        )
    finally:
        config.get_settings.cache_clear()


def test_inject_grader_keys_is_idempotent():
    text = inject_grader_keys(STUDENT, server="http://s", assignment_version="v1")
    text2 = inject_grader_keys(text, server="http://s2", assignment_version="v2")
    keys = read_grader_keys(text2)
    assert keys == {"server": "http://s2", "assignment-version": "v2"}
    assert text2.count("# /// script") == 1
