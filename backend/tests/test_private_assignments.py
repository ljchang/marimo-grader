"""Private (enrolled-only) assignments: the window, the deadline, autograde off,
whole-notebook submission, and storage credentials that stop at close_at."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from grader import db as dbmod
from grader.models import Assignment, GraderRun, GradingMode, Question, RunKind, Submission
from tests.conftest import login, notebook_token
from tests.test_publish_public import Q2, _publish
from tests.test_storage import _mounts, _session, fake_cf, storage_on  # noqa: F401

BASE = "/a/neuroimaging/2026-fall/glm"


def _at(**delta) -> str:
    return (datetime.now(UTC) + timedelta(**delta)).isoformat()


def _patch(client, seed, **settings):
    csrf = login(client, "prof")
    r = client.patch(
        f"/api/v1/offerings/{seed.offering_id}/assignments/{seed.assignment_id}",
        json={"settings": settings},
        headers={"X-CSRF-Token": csrf},
    )
    client.cookies.clear()
    return r


def _set(seed, **settings):
    """Write settings straight to the row, bypassing validation (e.g. a past window)."""
    with dbmod.get_sessionmaker()() as db:
        a = db.get(Assignment, seed.assignment_id)
        a.settings = {**(a.settings or {}), **settings}
        db.commit()


def _submit(client, seed, netid, qid="glm-q01"):
    return client.post(
        "/api/v1/submissions",
        headers={"Authorization": f"Bearer {notebook_token(client, netid)}"},
        json={
            "assignment_version_id": str(seed.version_id),
            "question_id": qid,
            "notebook": "# student\nx = 1\n",
        },
    )


def _runs(sub_id: str) -> set[RunKind]:
    sub_id = uuid.UUID(sub_id)
    with dbmod.get_sessionmaker()() as db:
        return {
            r.kind for r in db.scalars(select(GraderRun).where(GraderRun.submission_id == sub_id))
        }


# -- settings ------------------------------------------------------------------


@pytest.mark.parametrize(
    "settings, code",
    [
        ({"visibility": "secret"}, "bad_visibility"),
        ({"late_policy": "maybe"}, "bad_late_policy"),
        ({"due_at": "next tuesday"}, "bad_date"),
        ({"release_at": _at(days=2), "due_at": _at(days=1)}, "bad_window"),
        ({"due_at": _at(days=2), "close_at": _at(days=1)}, "bad_window"),
        ({"release_at": (same := _at(days=1)), "close_at": same}, "bad_window"),
        ({"autograde": "no"}, "bad_autograde"),
        ({"notebook_points": -1}, "bad_points"),
        ({"render_timeout": 5}, "bad_timeout"),
    ],
)
def test_settings_are_validated(client, seed, settings, code):
    r = _patch(client, seed, **settings)
    assert r.status_code == 422 and r.json()["error"]["code"] == code, r.text


def test_due_may_equal_close_and_availability_is_reported(client, seed):
    due = _at(days=3)
    r = _patch(
        client, seed, visibility="enrolled", release_at=_at(days=-1), due_at=due, close_at=due
    )
    assert r.status_code == 200, r.text
    av = r.json()["availability"]
    assert av["state"] == "open" and av["visibility"] == "enrolled" and not av["past_due"]


# -- who can fetch the notebook --------------------------------------------------


def test_private_assignment_is_invisible_to_the_public(client, seed):
    csrf = login(client, "prof")
    _publish(client, csrf, seed, questions=Q2)
    client.cookies.clear()
    assert _patch(client, seed, visibility="enrolled").status_code == 200

    meta = client.get("/a/neuroimaging/2026-fall/assignments.json").json()
    assert [a["slug"] for a in meta["assignments"]] == []
    # Signed out, a private slug and a missing one are indistinguishable.
    other = "/a/neuroimaging/2026-fall/no-such-exam"
    for suffix in ("student.py", "molab"):
        mine = client.get(f"{BASE}/{suffix}", follow_redirects=False)
        missing = client.get(f"{other}/{suffix}", follow_redirects=False)
        assert mine.status_code == missing.status_code == 404
        assert mine.json() == missing.json()
    mine = client.get(f"{BASE}/launch", follow_redirects=False)
    missing = client.get(f"{other}/launch", follow_redirects=False)
    assert mine.status_code == missing.status_code == 302
    assert mine.headers["location"] == missing.headers["location"]
    assert "/api/v1/auth/login?next=" in mine.headers["location"]

    # An outsider with a valid sign-in learns nothing more than a stranger.
    from grader.models import User

    with dbmod.get_sessionmaker()() as db:
        db.add(User(netid="outsider"))
        db.commit()
    login(client, "outsider")
    assert client.get(f"{BASE}/student.py").status_code == 404
    assert client.get(f"{BASE}/launch", follow_redirects=False).status_code == 404


def test_window_applies_to_students_not_staff(client, seed):
    csrf = login(client, "prof")
    _publish(client, csrf, seed, questions=Q2)
    client.cookies.clear()
    _set(seed, visibility="enrolled", release_at=_at(hours=1), close_at=_at(days=1))

    login(client, "f00abc1")
    r = client.get(f"{BASE}/student.py")
    assert r.status_code == 403 and r.json()["error"]["code"] == "not_released"
    # A notebook token works the same as the browser session.
    client.cookies.clear()
    tok = notebook_token(client, "f00abc1")
    assert (
        client.get(f"{BASE}/student.py", headers={"Authorization": f"Bearer {tok}"}).status_code
        == 403
    )

    login(client, "ta1")
    assert client.get(f"{BASE}/student.py").status_code == 200
    client.cookies.clear()

    _set(seed, release_at=_at(hours=-1))
    login(client, "f00abc1")
    assert client.get(f"{BASE}/student.py").status_code == 200
    r = client.get(f"{BASE}/molab", follow_redirects=False)
    assert r.headers["location"].startswith("https://molab.marimo.io/new/#code/")
    r = client.get(f"{BASE}/launch", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].endswith(f"/me/{seed.offering_id}#glm")

    _set(seed, close_at=_at(minutes=-1))
    r = client.get(f"{BASE}/student.py")
    assert r.status_code == 403 and r.json()["error"]["code"] == "closed"
    r = client.get(f"/api/v1/assignment-versions/{seed.version_id}/student.py")
    assert r.status_code == 403


def test_public_assignment_is_unchanged(client, seed):
    csrf = login(client, "prof")
    _publish(client, csrf, seed, questions=Q2)
    client.cookies.clear()
    _set(seed, release_at=_at(days=1))  # a window alone does not hide a public notebook
    assert client.get(f"{BASE}/student.py").status_code == 200


# -- submissions -------------------------------------------------------------------


def test_submission_window_and_late_policy(client, seed):
    _set(seed, release_at=_at(hours=1))
    r = _submit(client, seed, "f00abc1")
    assert r.status_code == 403 and r.json()["error"]["code"] == "not_released"
    assert _submit(client, seed, "prof").status_code == 201, "staff are exempt"

    # Past due, default policy: accepted and marked late.
    _set(seed, release_at=_at(days=-2), due_at=_at(hours=-1), close_at=_at(days=1))
    r = _submit(client, seed, "f00abc1")
    assert r.status_code == 201, r.text
    login(client, "f00abc1")
    mine = client.get(
        f"/api/v1/offerings/{seed.offering_id}/me/submissions",
        params={"assignment_id": str(seed.assignment_id)},
    ).json()
    client.cookies.clear()
    assert [s["late"] for s in mine] == [True]

    _set(seed, late_policy="reject")
    r = _submit(client, seed, "f00abc1")
    assert r.status_code == 403 and r.json()["error"]["code"] == "past_due"

    _set(seed, late_policy=None, close_at=_at(minutes=-1))
    r = _submit(client, seed, "f00abc1")
    assert r.status_code == 403 and r.json()["error"]["code"] == "closed"


def test_autograde_off_still_renders(client, seed):
    assert _patch(client, seed, autograde=False).status_code == 200
    r = _submit(client, seed, "f00abc1")
    assert r.status_code == 201
    assert _runs(r.json()["id"]) == {RunKind.render}


# -- whole-notebook submission ------------------------------------------------------


def _notebook_q(seed) -> Question | None:
    with dbmod.get_sessionmaker()() as db:
        return db.scalar(
            select(Question).where(
                Question.assignment_id == seed.assignment_id, Question.qid == "notebook"
            )
        )


def test_notebook_question_graded(client, seed):
    r = _patch(client, seed, notebook_submission=True, notebook_points=40)
    assert r.status_code == 200, r.text
    assert "notebook" in [q["qid"] for q in r.json()["questions"]]
    q = _notebook_q(seed)
    assert q.grading_mode == GradingMode.manual and float(q.max_points) == 40 and q.order == 2

    # Accepted by a copy published before the question existed.
    r = _submit(client, seed, "f00abc1", qid="notebook")
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "received"
    assert _runs(r.json()["id"]) == {RunKind.render}

    login(client, "prof")
    tri = client.get(f"/api/v1/offerings/{seed.offering_id}/triage").json()
    assert "notebook" in [a["qid"] for a in tri["awaiting_manual"]]
    client.cookies.clear()

    _patch(client, seed, notebook_submission=False)
    assert _notebook_q(seed).active is False
    r = _submit(client, seed, "f00abc1", qid="notebook")
    assert r.status_code == 404


def test_notebook_question_receipt(client, seed):
    _patch(client, seed, notebook_submission=True)
    assert _notebook_q(seed).grading_mode == GradingMode.auto
    r = _submit(client, seed, "f00abc1", qid="notebook")
    assert r.status_code == 201 and r.json()["status"] == "graded"
    login(client, "prof")
    tri = client.get(f"/api/v1/offerings/{seed.offering_id}/triage").json()
    assert "notebook" not in [a["qid"] for a in tri["awaiting_manual"]]


def test_publish_without_questions_needs_notebook_submission(client, seed):
    csrf = login(client, "prof")
    r = _publish(client, csrf, seed, questions=[])
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_questions"
    r = _publish(client, csrf, seed, questions=[{"qid": "notebook", "title": "x"}])
    assert r.json()["error"]["code"] == "reserved_qid"
    client.cookies.clear()

    _patch(client, seed, notebook_submission=True, notebook_points=10)
    csrf = login(client, "prof")
    r = _publish(client, csrf, seed, questions=[])
    assert r.status_code == 201, r.text
    # The publish deactivated glm-q01/q05 (not sent) but kept the notebook question.
    assert [q["qid"] for q in r.json()["assignment"]["questions"]] == ["notebook"]
    with dbmod.get_sessionmaker()() as db:
        assert db.scalar(select(Submission)) is None


# -- storage credentials stop at close_at --------------------------------------------


def test_credentials_expire_at_close(client, seed, storage_on, fake_cf):  # noqa: F811
    _set(seed, release_at=_at(hours=-1), close_at=_at(minutes=10))
    p = _session(client, seed, "f00abc1")
    assert "/assignments/glm" in _mounts(p)
    ro = next(c for c in fake_cf if c["permission"] == "object-read-only")
    assert 540 <= ro["ttl"] <= 600, ro

    # Staff keep the full hour.
    fake_cf.clear()
    _session(client, seed, "ta1")
    assert all(c["ttl"] == 3600 for c in fake_cf)

    # In the final minute the assignment is treated as closed.
    fake_cf.clear()
    _set(seed, close_at=_at(seconds=30))
    p = _session(client, seed, "f00abc1")
    assert "/assignments/glm" not in _mounts(p)
    assert all(c["ttl"] == 3600 for c in fake_cf)


def test_presign_expires_at_close(client, seed, storage_on, fake_cf):  # noqa: F811
    _set(seed, release_at=_at(hours=-1), close_at=_at(minutes=5))
    tok = notebook_token(client, "f00abc1")
    r = client.post(
        f"/api/v1/offerings/{seed.offering_id}/storage/presign",
        json={"path": "/assignments/glm/data.csv", "expires": 3600},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200, r.text
    assert 240 <= r.json()["expires_in"] <= 300
