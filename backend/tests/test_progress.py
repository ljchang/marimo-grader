"""Class progress: per-student states behind the assignments table and the
assignment page's roster strips."""

from __future__ import annotations

import uuid

from grader import db as dbmod
from grader.models import Question, Score, Submission, SubmissionStatus
from grader.services.grades import recompute_question_grade
from tests.conftest import login, notebook_token


def _submit(client, seed, netid, qid):
    r = client.post(
        "/api/v1/submissions",
        headers={"Authorization": f"Bearer {notebook_token(client, netid)}"},
        json={
            "assignment_version_id": str(seed.version_id),
            "question_id": qid,
            "notebook": "x = 1\n",
        },
    )
    assert r.status_code == 201, r.text
    return uuid.UUID(r.json()["id"])


def _grade(sid, points, final=True):
    with dbmod.get_sessionmaker()() as db:
        sub = db.get(Submission, sid)
        db.add(Score(submission_id=sid, auto_points=points, is_final=final))
        sub.status = SubmissionStatus.graded
        db.flush()
        q = db.get(Question, sub.question_id)
        recompute_question_grade(db, sub.enrollment_id, q, q.assignment)
        db.commit()


def _progress(client, seed, **params):
    login(client, "ta1")
    r = client.get(f"/api/v1/offerings/{seed.offering_id}/progress", params=params)
    client.cookies.clear()
    assert r.status_code == 200, r.text
    return r.json()


def test_states_counts_and_average(client, seed):
    a1 = _submit(client, seed, "f00abc1", "glm-q01")
    _submit(client, seed, "f00abc1", "glm-q05")  # by hand, not yet graded
    b1 = _submit(client, seed, "f00xyz9", "glm-q01")

    p = _progress(client, seed)
    assert p["roster"] == 2 and p["students"] is None
    a = p["assignments"][str(seed.assignment_id)]
    assert a["submitted"] == 2 and a["to_grade"] == 1
    # Nothing has a score yet: q01 attempts are still with the autograder.
    assert a["questions"][str(seed.q_auto_id)]["counts"]["running"] == 2
    assert a["students"]["waiting"] == 1 and a["students"]["running"] == 1
    assert a["average"] is None and "marks" not in a["questions"][str(seed.q_auto_id)]

    _grade(a1, 5)
    _grade(b1, 4)
    a = _progress(client, seed)["assignments"][str(seed.assignment_id)]
    # Alice still waits on q05; Bob is fully graded, his skipped q05 counting as zero.
    assert a["students"] == {"graded": 1, "waiting": 1, "failed": 0, "running": 0, "none": 0}
    assert a["average"] == 40.0 and a["averaged_over"] == 1


def test_marks_follow_the_student_order(client, seed):
    sid = _submit(client, seed, "f00xyz9", "glm-q05")
    with dbmod.get_sessionmaker()() as db:
        db.get(Submission, sid).status = SubmissionStatus.failed
        db.commit()
    p = _progress(client, seed, assignment_id=str(seed.assignment_id))
    assert [s["netid"] for s in p["students"]] == ["f00abc1", "f00xyz9"]
    q = p["assignments"][str(seed.assignment_id)]["questions"]
    assert q[str(seed.q_manual_id)]["marks"] == ["none", "failed"]
    assert q[str(seed.q_auto_id)]["marks"] == ["none", "none"]


def test_autograde_off_means_every_answer_is_read_by_hand(client, seed):
    csrf = login(client, "prof")
    r = client.patch(
        f"/api/v1/offerings/{seed.offering_id}/assignments/{seed.assignment_id}",
        json={"settings": {"autograde": False}},
        headers={"X-CSRF-Token": csrf},
    )
    client.cookies.clear()
    assert r.status_code == 200, r.text
    _submit(client, seed, "f00abc1", "glm-q01")
    a = _progress(client, seed)["assignments"][str(seed.assignment_id)]
    assert a["questions"][str(seed.q_auto_id)]["counts"]["waiting"] == 1 and a["to_grade"] == 1


def test_students_cannot_read_progress(client, seed):
    login(client, "f00abc1")
    r = client.get(f"/api/v1/offerings/{seed.offering_id}/progress")
    assert r.status_code == 403
