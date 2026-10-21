"""Rubrics: items an instructor scores one by one in the grading queue.

A rubric hangs off one question. Its item scores add up to the manual points,
and the whole-notebook question is worth exactly what its rubric adds up to.
Only staff ever see it: the assignment list students read carries no items.
"""

from __future__ import annotations

from tests.conftest import login
from tests.test_private_assignments import _notebook_q, _patch, _submit

ITEMS = [
    {"key": "1", "label": "Short answer", "points": 5, "group": "Short answer"},
    {"key": "2.1", "label": "Load the data", "points": 1, "group": "Analysis"},
    {"key": "2.2", "label": "Fit the model", "points": 2, "group": "Analysis"},
]


def _url(seed, question_id) -> str:
    return f"/api/v1/offerings/{seed.offering_id}/questions/{question_id}/rubric"


def _put(client, seed, question_id, items, netid="prof"):
    csrf = login(client, netid)
    r = client.put(_url(seed, question_id), json={"items": items}, headers={"X-CSRF-Token": csrf})
    client.cookies.clear()
    return r


def _queue(client, seed, question_id):
    login(client, "prof")
    r = client.get(
        f"/api/v1/offerings/{seed.offering_id}/queue", params={"question_id": str(question_id)}
    )
    client.cookies.clear()
    return r.json()


def _score(client, sub_id, rubric_scores, netid="prof"):
    csrf = login(client, netid)
    r = client.post(
        f"/api/v1/submissions/{sub_id}/score",
        json={"rubric_scores": rubric_scores},
        headers={"X-CSRF-Token": csrf},
    )
    client.cookies.clear()
    return r


def test_notebook_rubric_sets_the_points(client, seed):
    _patch(client, seed, notebook_submission=True, notebook_points=100)
    q = _notebook_q(seed)
    r = _put(client, seed, q.id, ITEMS)
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 8
    assert float(_notebook_q(seed).max_points) == 8

    rubric = _queue(client, seed, q.id)["question"]["rubric"]
    assert [i["key"] for i in rubric["items"]] == ["1", "2.1", "2.2"]
    assert rubric["items"][1]["group"] == "Analysis"

    # The points now come from the rubric, not from Settings.
    r = _patch(client, seed, notebook_submission=True, notebook_points=100)
    assert r.status_code == 422 and r.json()["error"]["code"] == "points_set_by_rubric"
    assert _patch(client, seed, notebook_submission=True, notebook_points=8).status_code == 200


def test_scores_add_up_and_stay_inside_each_item(client, seed):
    _patch(client, seed, notebook_submission=True, notebook_points=10)
    q = _notebook_q(seed)
    _put(client, seed, q.id, ITEMS)
    sub = _submit(client, seed, "f00abc1", qid="notebook").json()

    r = _score(client, sub["id"], {"1": 4, "2.1": 1, "2.2": 1.5})
    assert r.status_code == 200, r.text
    assert r.json()["score"]["manual_points"] == 6.5

    r = _score(client, sub["id"], {"2.2": 3})
    assert r.status_code == 422 and r.json()["error"]["code"] == "out_of_range"
    r = _score(client, sub["id"], {"9": 1})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_rubric_item"


def test_rubric_on_another_question_must_fit(client, seed):
    r = _put(client, seed, seed.q_manual_id, ITEMS)
    assert r.status_code == 422 and r.json()["error"]["code"] == "rubric_over"
    r = _put(client, seed, seed.q_manual_id, ITEMS[1:])
    assert r.status_code == 200, r.text


def test_empty_list_removes_the_rubric(client, seed):
    _patch(client, seed, notebook_submission=True, notebook_points=10)
    q = _notebook_q(seed)
    _put(client, seed, q.id, ITEMS)
    r = _put(client, seed, q.id, [])
    assert r.status_code == 200 and r.json()["items"] == []
    assert _queue(client, seed, q.id)["question"]["rubric"] is None
    # With the rubric gone, Settings sets the points again.
    assert _patch(client, seed, notebook_submission=True, notebook_points=20).status_code == 200


def test_bad_rubrics_refused(client, seed):
    dup = [ITEMS[1], {**ITEMS[2], "key": "2.1"}]
    assert _put(client, seed, seed.q_manual_id, dup).json()["error"]["code"] == "duplicate_key"
    zero = [{"key": "a", "label": "Nothing", "points": 0}]
    assert _put(client, seed, seed.q_manual_id, zero).status_code == 422


def test_only_instructors_edit_or_read_it(client, seed):
    _put(client, seed, seed.q_manual_id, ITEMS[1:])
    assert _put(client, seed, seed.q_manual_id, [], netid="ta1").status_code == 403
    for netid in ("ta1", "f00abc1"):
        login(client, netid)
        assert client.get(_url(seed, seed.q_manual_id)).status_code == 403
        client.cookies.clear()

    # Students see no rubric items in the assignment list.
    login(client, "f00abc1")
    body = client.get(f"/api/v1/offerings/{seed.offering_id}/assignments").text
    assert "Fit the model" not in body
