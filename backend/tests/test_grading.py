import io

from grader import db as dbmod
from grader.models import GradeAudit, Score, SubmissionStatus
from tests.conftest import login, notebook_token


def _submit(client, token, seed, qid):
    return client.post(
        "/api/v1/submissions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "assignment_version_id": str(seed.version_id),
            "question_id": qid,
            "notebook": "# nb\n",
        },
    ).json()


def test_manual_score_audit_and_grid(client, seed):
    token = notebook_token(client, "f00abc1")
    sub = _submit(client, token, seed, "glm-q05")

    csrf = login(client, "ta1")
    tri = client.get(f"/api/v1/offerings/{seed.offering_id}/triage").json()
    assert tri["awaiting_manual"][0]["qid"] == "glm-q05" and tri["awaiting_manual"][0]["count"] == 1
    assert {s["netid"] for s in tri["inactive_students"]} == {"f00xyz9"}

    q = client.get(
        f"/api/v1/offerings/{seed.offering_id}/queue?question_id={seed.q_manual_id}"
    ).json()
    assert q["items"][0]["needs_grading"] is True

    r = client.post(
        f"/api/v1/submissions/{sub['id']}/score",
        json={"manual_points": 4, "feedback": "Good, but discuss uncertainty.", "final": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 200, r.text
    assert r.json()["score"]["total"] == 4.0 and r.json()["question_grade"]["points"] == 4.0

    grid = client.get(f"/api/v1/offerings/{seed.offering_id}/grid").json()
    row = next(s for s in grid["students"] if s["netid"] == "f00abc1")
    assert row["cells"][str(seed.q_manual_id)] == {
        "state": "graded",
        "attempts": 1,
        "points": 4.0,
        "max": 5.0,
    }
    assert row["cells"][str(seed.q_auto_id)]["state"] == "none"

    tri = client.get(f"/api/v1/offerings/{seed.offering_id}/triage").json()
    assert tri["awaiting_manual"] == []

    with dbmod.get_sessionmaker()() as db:
        assert db.query(Score).count() == 1
        a = db.query(GradeAudit).filter(GradeAudit.entity == "score").one()
        assert a.after["total"] == 4.0
        assert db.query(Score).one().submission.status == SubmissionStatus.graded


def test_score_out_of_range(client, seed):
    token = notebook_token(client, "f00abc1")
    sub = _submit(client, token, seed, "glm-q05")
    csrf = login(client, "prof")
    r = client.post(
        f"/api/v1/submissions/{sub['id']}/score",
        json={"manual_points": 7},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "out_of_range"


def test_student_cannot_score_or_see_grid(client, seed):
    token = notebook_token(client, "f00abc1")
    sub = _submit(client, token, seed, "glm-q05")
    csrf = login(client, "f00abc1")
    r = client.post(
        f"/api/v1/submissions/{sub['id']}/score",
        json={"manual_points": 5},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 404
    assert client.get(f"/api/v1/offerings/{seed.offering_id}/grid").status_code == 403


def test_platform_admin_cannot_read_student_work(client, seed):
    token = notebook_token(client, "f00abc1")
    sub = _submit(client, token, seed, "glm-q05")
    login(client, "admin")
    assert client.get(f"/api/v1/submissions/{sub['id']}").status_code == 404
    assert client.get(f"/api/v1/offerings/{seed.offering_id}/grid").status_code == 404
    assert client.get("/api/v1/admin/courses").status_code == 200


def test_student_overview_and_history(client, seed):
    token = notebook_token(client, "f00abc1")
    sub = _submit(client, token, seed, "glm-q05")
    csrf = login(client, "prof")
    client.post(
        f"/api/v1/submissions/{sub['id']}/score",
        json={"manual_points": 3},
        headers={"X-CSRF-Token": csrf},
    )
    hist = client.get(f"/api/v1/offerings/{seed.offering_id}/students/f00abc1").json()
    assert hist["submissions"][0]["score"]["total"] == 3.0
    client.cookies.clear()
    login(client, "f00abc1")
    me = client.get(f"/api/v1/offerings/{seed.offering_id}/me").json()
    a = me["assignments"][0]
    assert a["status"] == "in_progress" and a["points"] == 3.0 and a["max_points"] == 10.0


def test_canvas_export_roundtrip(client, seed):
    token = notebook_token(client, "f00abc1")
    sub = _submit(client, token, seed, "glm-q05")
    csrf = login(client, "prof")
    client.post(
        f"/api/v1/submissions/{sub['id']}/score",
        json={"manual_points": 4.5},
        headers={"X-CSRF-Token": csrf},
    )
    r = client.get(
        f"/api/v1/offerings/{seed.offering_id}/export/canvas?assignment_ids={seed.assignment_id}"
    )
    assert r.status_code == 409  # no template yet
    canvas = (
        "Student,ID,SIS User ID,SIS Login ID,Section,Other (1)\n"
        "    Points Possible,,,,,10\n"
        '"Student, Alice",11,S1,f00abc1,NEUR 01,\n'
        '"Student, Bob",12,S2,f00xyz9@dartmouth.edu,NEUR 01,\n'
    )
    r = client.post(
        f"/api/v1/offerings/{seed.offering_id}/roster/preview",
        files={"file": ("grades.csv", io.BytesIO(canvas.encode()), "text/csv")},
        data={"source": "canvas_csv"},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 200, r.text
    r = client.get(
        f"/api/v1/offerings/{seed.offering_id}/export/canvas?assignment_ids={seed.assignment_id}"
    )
    assert r.status_code == 200
    lines = r.text.strip().splitlines()
    assert lines[0].endswith("GLM")
    assert lines[2].endswith(",4.5") and lines[3].endswith(",")
