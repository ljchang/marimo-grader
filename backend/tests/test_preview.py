"""Student preview: staff see an offering exactly as a student does, except that
an assignment's release date does not apply."""

from __future__ import annotations

import pytest

from tests.conftest import login
from tests.test_private_assignments import BASE, _at, _set, _student_list, _submit
from tests.test_publish_public import Q2, _publish
from tests.test_storage import _mounts, _session, fake_cf, storage_on  # noqa: F401


def _preview(client, seed, netid, on=True):
    csrf = login(client, netid)
    r = client.put(
        f"/api/v1/offerings/{seed.offering_id}/preview",
        json={"on": on},
        headers={"X-CSRF-Token": csrf},
    )
    client.cookies.clear()
    return r


def _private_unreleased(client, seed, **extra):
    csrf = login(client, "prof")
    _publish(client, csrf, seed, questions=Q2)
    client.cookies.clear()
    _set(seed, visibility="enrolled", **extra)  # no release_at: still being built


@pytest.mark.parametrize("netid, role", [("prof", "instructor"), ("ta1", "ta")])
def test_staff_switch_preview_on_and_off(client, seed, netid, role):
    r = _preview(client, seed, netid)
    assert r.status_code == 200, r.text
    assert (r.json()["role"], r.json()["staff_role"], r.json()["preview"]) == (
        "student",
        role,
        True,
    )

    login(client, netid)
    (e,) = client.get("/api/v1/auth/me").json()["enrollments"]
    assert (e["role"], e["staff_role"], e["preview"]) == ("student", role, True)
    client.cookies.clear()

    # The way out is not a staff page, so preview cannot lock anyone in.
    r = _preview(client, seed, netid, on=False)
    assert r.status_code == 200 and (r.json()["role"], r.json()["preview"]) == (role, False)


def test_students_cannot_preview(client, seed):
    r = _preview(client, seed, "f00abc1")
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"


def test_preview_refuses_staff_pages(client, seed):
    _preview(client, seed, "prof")
    login(client, "prof")
    assert client.get(f"/api/v1/offerings/{seed.offering_id}/roster").status_code == 403
    assert (
        client.get(
            f"/api/v1/offerings/{seed.offering_id}/queue?question_id={seed.q_manual_id}"
        ).status_code
        == 403
    )
    client.cookies.clear()
    _preview(client, seed, "prof", on=False)
    login(client, "prof")
    assert client.get(f"/api/v1/offerings/{seed.offering_id}/roster").status_code == 200


def test_preview_opens_an_unreleased_assignment(client, seed, storage_on, fake_cf):  # noqa: F811
    _private_unreleased(client, seed)
    # A real student sees nothing yet.
    assert _student_list(client, seed) == []

    _preview(client, seed, "ta1")
    assert _student_list(client, seed, "ta1") == ["glm"]
    login(client, "ta1")
    (a,) = client.get(f"/api/v1/offerings/{seed.offering_id}/assignments").json()
    assert a["availability"]["state"] == "open"
    assert client.get(f"{BASE}/student.py").status_code == 200
    client.cookies.clear()

    mounts = _mounts(_session(client, seed, "ta1"))
    assert "/assignments/glm" in mounts
    assert not any(k.startswith("/students") for k in mounts)  # student-scoped credentials

    r = _submit(client, seed, "ta1")
    assert r.status_code == 201, r.text
    assert r.json()["test"] is True  # a staff attempt: never in the gradebook


def test_preview_holds_staff_to_close_and_deadline(client, seed, storage_on, fake_cf):  # noqa: F811
    _private_unreleased(client, seed, close_at=_at(hours=-1))
    _preview(client, seed, "prof")
    assert _student_list(client, seed, "prof") == ["glm"]  # listed, but closed
    login(client, "prof")
    assert client.get(f"{BASE}/student.py").json()["error"]["code"] == "closed"
    client.cookies.clear()
    assert "/assignments/glm" not in _mounts(_session(client, seed, "prof"))
    r = _submit(client, seed, "prof")
    assert r.status_code == 403 and r.json()["error"]["code"] == "closed"

    _set(seed, close_at=None, due_at=_at(hours=-1), late_policy="reject")
    r = _submit(client, seed, "prof")
    assert r.status_code == 403 and r.json()["error"]["code"] == "past_due"

    # Out of preview, staff are exempt again.
    _preview(client, seed, "prof", on=False)
    assert _submit(client, seed, "prof").status_code == 201


def test_preview_is_per_person(client, seed):
    _preview(client, seed, "prof")
    login(client, "ta1")
    assert client.get(f"/api/v1/offerings/{seed.offering_id}/roster").status_code == 200
