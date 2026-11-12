"""Grading autosaves drafts; students see a score only once it is published."""

import uuid

from grader import db as dbmod
from grader.models import GradeAudit, Score
from tests.conftest import login, notebook_token
from tests.test_grading import _submit


def _score(client, csrf, sub_id, **body):
    r = client.post(
        f"/api/v1/submissions/{sub_id}/score", json=body, headers={"X-CSRF-Token": csrf}
    )
    assert r.status_code == 200, r.text
    return r.json()


def _student_view(client, seed):
    client.cookies.clear()
    login(client, "f00abc1")
    subs = client.get(f"/api/v1/offerings/{seed.offering_id}/me/submissions").json()
    me = client.get(f"/api/v1/offerings/{seed.offering_id}/me").json()
    return subs[0], me["assignments"][0]


def _queue(client, seed, qid):
    a = client.get(f"/api/v1/offerings/{seed.offering_id}/assignments").json()[0]
    q = next(x for x in a["questions"] if x["qid"] == qid)
    return client.get(
        f"/api/v1/offerings/{seed.offering_id}/queue", params={"question_id": q["id"]}
    ).json()["items"]


def _rows(sub_id):
    with dbmod.get_sessionmaker()() as db:
        return db.query(Score).filter(Score.submission_id == uuid.UUID(sub_id)).all()


def _audits():
    with dbmod.get_sessionmaker()() as db:
        return db.query(GradeAudit).filter(GradeAudit.entity == "score").count()


def test_drafts_autosave_in_place_and_stay_hidden_from_the_student(client, seed):
    token = notebook_token(client, "f00abc1")
    sub = _submit(client, token, seed, "glm-q05")
    csrf = login(client, "prof")

    # Autosaves while typing: one draft row, updated in place, no audit entries.
    _score(client, csrf, sub["id"], manual_points=1, feedback="Go", final=False)
    j = _score(client, csrf, sub["id"], manual_points=2, feedback="Good start", final=False)
    assert j["score"]["is_final"] is False and j["score"]["published_at"] is None
    assert len(_rows(sub["id"])) == 1 and _audits() == 0

    # Staff pick the draft back up, and it still needs grading.
    [item] = _queue(client, seed, "glm-q05")
    assert item["score"]["feedback"] == "Good start" and item["needs_grading"] is True

    # The student sees nothing of it.
    mine, overview = _student_view(client, seed)
    assert mine["score"] is None and mine["status"] != "graded"
    assert overview["points"] is None


def test_publish_then_edit_keeps_the_published_grade_until_republished(client, seed):
    token = notebook_token(client, "f00abc1")
    sub = _submit(client, token, seed, "glm-q05")
    csrf = login(client, "prof")
    _score(client, csrf, sub["id"], manual_points=2, feedback="Draft", final=False)
    pub = _score(client, csrf, sub["id"], manual_points=3, feedback="Well done", final=True)
    assert pub["score"]["is_final"] is True and pub["score"]["published_at"]
    assert pub["question_grade"]["points"] == 3.0 and _audits() == 1

    # Editing after publishing starts a new draft; the published grade stands.
    d = _score(client, csrf, sub["id"], manual_points=4, feedback="Regrade", final=False)
    assert d["score"]["is_final"] is False and d["score"]["published_at"]
    assert d["question_grade"]["points"] == 3.0 and _audits() == 1
    [item] = _queue(client, seed, "glm-q05")
    assert item["score"]["feedback"] == "Regrade" and item["needs_grading"] is False

    mine, overview = _student_view(client, seed)
    assert mine["score"]["total"] == 3.0 and mine["score"]["feedback"] == "Well done"
    assert "published_at" not in mine["score"]
    assert overview["points"] == 3.0


def test_another_graders_draft_is_not_overwritten_in_place(client, seed):
    token = notebook_token(client, "f00abc1")
    sub = _submit(client, token, seed, "glm-q05")
    csrf = login(client, "ta1")
    _score(client, csrf, sub["id"], manual_points=1, final=False)
    client.cookies.clear()
    csrf = login(client, "prof")
    _score(client, csrf, sub["id"], manual_points=2, final=False)
    assert sorted(float(r.manual_points) for r in _rows(sub["id"])) == [1.0, 2.0]


def _qid(client, seed, qid):
    a = client.get(f"/api/v1/offerings/{seed.offering_id}/assignments").json()[0]
    return next(x for x in a["questions"] if x["qid"] == qid)["id"]


def test_publish_drafts_publishes_each_as_its_grader_left_it(client, seed):
    alice = _submit(client, notebook_token(client, "f00abc1"), seed, "glm-q05")
    _submit(client, notebook_token(client, "f00xyz9"), seed, "glm-q05")
    csrf = login(client, "ta1")
    _score(client, csrf, alice["id"], manual_points=2, feedback="Alice draft", final=False)
    client.cookies.clear()
    csrf = login(client, "prof")
    q = _qid(client, seed, "glm-q05")
    marks = client.get(
        f"/api/v1/offerings/{seed.offering_id}/progress",
        params={"assignment_id": str(seed.assignment_id)},
    ).json()["assignments"][str(seed.assignment_id)]["questions"][q]
    # Alice's answer is under way, Bob's untouched; both still to grade.
    assert marks["counts"]["draft"] == 1 and marks["counts"]["waiting"] == 1

    r = client.post(
        f"/api/v1/offerings/{seed.offering_id}/questions/{q}/publish-drafts",
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"published": 1, "netids": ["f00abc1"]}
    items = {i["netid"]: i for i in _queue(client, seed, "glm-q05")}
    assert items["f00abc1"]["score"]["is_final"] and not items["f00abc1"]["needs_grading"]
    assert items["f00xyz9"]["score"] is None
    # Published as the TA left it, by the TA; the instructor is the actor on record.
    rows = _rows(alice["id"])
    final = next(r for r in rows if r.is_final)
    assert float(final.manual_points) == 2.0 and final.feedback == "Alice draft"
    with dbmod.get_sessionmaker()() as db:
        a = db.query(GradeAudit).filter(GradeAudit.entity == "score").one()
        assert a.reason == "published with the other drafts"
    mine, _ = _student_view(client, seed)
    assert mine["score"]["feedback"] == "Alice draft"


def test_course_can_reserve_publishing_for_instructors(client, seed):
    sub = _submit(client, notebook_token(client, "f00abc1"), seed, "glm-q05")
    csrf = login(client, "ta1")
    r = client.patch(
        f"/api/v1/offerings/{seed.offering_id}/settings",
        json={"ta_can_finalize": False},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 403  # instructors only
    client.cookies.clear()
    csrf = login(client, "prof")
    r = client.patch(
        f"/api/v1/offerings/{seed.offering_id}/settings",
        json={"ta_can_finalize": False},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 200 and r.json()["settings"]["ta_can_finalize"] is False
    q = _qid(client, seed, "glm-q05")
    queue = client.get(
        f"/api/v1/offerings/{seed.offering_id}/queue", params={"question_id": q}
    ).json()
    assert queue["can_publish"] is True

    client.cookies.clear()
    csrf = login(client, "ta1")
    queue = client.get(
        f"/api/v1/offerings/{seed.offering_id}/queue", params={"question_id": q}
    ).json()
    assert queue["can_publish"] is False
    # The TA still drafts; publishing, one by one or all at once, is refused.
    _score(client, csrf, sub["id"], manual_points=3, final=False)
    r = client.post(
        f"/api/v1/submissions/{sub['id']}/score",
        json={"manual_points": 3, "final": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 403
    r = client.post(
        f"/api/v1/offerings/{seed.offering_id}/questions/{q}/publish-drafts",
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 403
