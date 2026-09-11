from grader import db as dbmod
from grader.models import GraderRun, RunKind, RunStatus, Submission
from tests.conftest import login, notebook_token


def _submit(client, token, seed, qid="glm-q01", notebook="# student\nx = 1\n"):
    return client.post(
        "/api/v1/submissions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "assignment_version_id": str(seed.version_id),
            "question_id": qid,
            "notebook": notebook,
            "check_results": [{"label": "glm-q01: Load", "status": "success"}],
            "client": {"package": "tests", "version": "0", "env": "pytest"},
        },
    )


def test_submit_creates_immutable_attempt_and_queues_runs(client, seed):
    token = notebook_token(client, "f00abc1")
    r1 = _submit(client, token, seed)
    assert r1.status_code == 201, r1.text
    assert r1.json()["attempt_no"] == 1 and r1.json()["status"] == "received"
    r2 = _submit(client, token, seed, notebook="# student\nx = 2\n")
    assert r2.json()["attempt_no"] == 2
    with dbmod.get_sessionmaker()() as db:
        subs = db.query(Submission).order_by(Submission.attempt_no).all()
        assert [s.attempt_no for s in subs] == [1, 2]
        assert subs[0].notebook_artifact_id != subs[1].notebook_artifact_id
        runs = db.query(GraderRun).filter(GraderRun.submission_id == subs[0].id).all()
        assert {r.kind for r in runs} == {RunKind.autograde, RunKind.render}
        assert all(r.status == RunStatus.queued for r in runs)


def test_submit_requires_student_enrollment(client, seed):
    token = notebook_token(client, "prof")  # instructor, not a student
    r = _submit(client, token, seed)
    assert r.status_code == 403 and r.json()["error"]["code"] == "not_enrolled"


def test_submit_unknown_question(client, seed):
    token = notebook_token(client, "f00abc1")
    r = _submit(client, token, seed, qid="nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "unknown_question"


def test_attempt_limit(client, seed):
    csrf = login(client, "prof")
    r = client.patch(
        f"/api/v1/offerings/{seed.offering_id}/assignments/{seed.assignment_id}",
        json={"settings": {"attempts_allowed": 1}},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 200, r.text
    client.cookies.clear()
    token = notebook_token(client, "f00abc1")
    assert _submit(client, token, seed).status_code == 201
    r = _submit(client, token, seed)
    assert r.status_code == 409 and r.json()["error"]["code"] == "attempts_exhausted"


def test_student_sees_own_but_not_others(client, seed):
    t1 = notebook_token(client, "f00abc1")
    sid = _submit(client, t1, seed).json()["id"]
    t2 = notebook_token(client, "f00xyz9")
    assert (
        client.get(
            f"/api/v1/submissions/{sid}", headers={"Authorization": f"Bearer {t1}"}
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/v1/submissions/{sid}", headers={"Authorization": f"Bearer {t2}"}
        ).status_code
        == 404
    )


def test_staff_can_see_student_submission(client, seed):
    t1 = notebook_token(client, "f00abc1")
    sid = _submit(client, t1, seed).json()["id"]
    login(client, "ta1")
    r = client.get(f"/api/v1/submissions/{sid}")
    assert r.status_code == 200 and r.json()["netid"] == "f00abc1"


def test_my_submissions_and_check_events(client, seed):
    token = notebook_token(client, "f00abc1")
    _submit(client, token, seed)
    r = client.post(
        "/api/v1/check-events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "assignment_version_id": str(seed.version_id),
            "question_id": "glm-q01",
            "check_key": "glm-q01",
            "passed": False,
        },
    )
    assert r.status_code == 202 and r.json()["ok"] is True
    login(client, "f00abc1")
    mine = client.get(
        f"/api/v1/offerings/{seed.offering_id}/me/submissions?assignment_id={seed.assignment_id}"
    ).json()
    assert len(mine) == 1 and mine[0]["qid"] == "glm-q01" and mine[0]["score"] is None


def test_notebook_too_large(client, seed):
    token = notebook_token(client, "f00abc1")
    r = _submit(client, token, seed, notebook="x" * (2 * 1024 * 1024 + 1))
    assert r.status_code == 413
