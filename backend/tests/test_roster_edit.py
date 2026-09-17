"""Adding and removing one person, without a CSV round-trip.

Import stays the bulk path and the source of truth. These routes cover what it
cannot: the late add, and removing someone import will not touch (it only ever
drops students, never staff).

Drops are soft. Submissions reference the enrollment, so the record of someone
who withdraws has to survive them leaving.
"""

from __future__ import annotations

from sqlalchemy import select

from grader import db as dbmod
from grader.models import Enrollment, EnrollmentStatus, Role, User
from tests.conftest import login


def _roster(client, seed):
    return client.get(f"/api/v1/offerings/{seed.offering_id}/roster").json()


def test_add_student(client, seed):
    csrf = login(client, "prof")
    r = client.post(
        f"/api/v1/offerings/{seed.offering_id}/roster/students",
        headers={"X-CSRF-Token": csrf},
        json={"netid": "F00NEW1", "display_name": "Late Arrival", "section": "01"},
    )
    assert r.status_code == 201, r.text
    assert r.json() == {"netid": "f00new1", "role": "student", "status": "active"}

    with dbmod.get_sessionmaker()() as db:
        u = db.scalar(select(User).where(User.netid == "f00new1"))
        assert u is not None and u.display_name == "Late Arrival"
        e = db.scalar(select(Enrollment).where(Enrollment.user_id == u.id))
        assert e.role == Role.student and e.status == EnrollmentStatus.active
        assert e.section is not None and e.section.name == "01"


def test_add_student_reinstates_a_dropped_row(client, seed):
    """Re-adding must not make a second enrollment; grades hang off the first."""
    csrf = login(client, "prof")
    client.delete(
        f"/api/v1/offerings/{seed.offering_id}/roster/f00abc1", headers={"X-CSRF-Token": csrf}
    )
    r = client.post(
        f"/api/v1/offerings/{seed.offering_id}/roster/students",
        headers={"X-CSRF-Token": csrf},
        json={"netid": "f00abc1"},
    )
    assert r.status_code == 201
    with dbmod.get_sessionmaker()() as db:
        u = db.scalar(select(User).where(User.netid == "f00abc1"))
        rows = db.scalars(select(Enrollment).where(Enrollment.user_id == u.id)).all()
        assert len(rows) == 1
        assert rows[0].status == EnrollmentStatus.active


def test_add_student_refuses_to_demote_staff(client, seed):
    csrf = login(client, "prof")
    r = client.post(
        f"/api/v1/offerings/{seed.offering_id}/roster/students",
        headers={"X-CSRF-Token": csrf},
        json={"netid": "ta1"},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "is_staff"


def test_drop_is_soft(client, seed):
    csrf = login(client, "prof")
    r = client.delete(
        f"/api/v1/offerings/{seed.offering_id}/roster/f00abc1", headers={"X-CSRF-Token": csrf}
    )
    assert r.status_code == 200 and r.json()["status"] == "dropped"
    with dbmod.get_sessionmaker()() as db:
        u = db.scalar(select(User).where(User.netid == "f00abc1"))
        e = db.scalar(select(Enrollment).where(Enrollment.user_id == u.id))
        assert e is not None, "the row must survive: submissions reference it"
        assert e.status == EnrollmentStatus.dropped
    # The listing has to say so too: a soft drop leaves the row in place, so
    # "status" is the only thing that tells the roster page anything happened.
    row = next(r for r in _roster(client, seed) if r["netid"] == "f00abc1")
    assert row["status"] == "dropped"


def test_drop_works_on_staff_too(client, seed):
    """The gap import cannot fill -- it only ever drops students."""
    csrf = login(client, "prof")
    r = client.delete(
        f"/api/v1/offerings/{seed.offering_id}/roster/ta1", headers={"X-CSRF-Token": csrf}
    )
    assert r.status_code == 200 and r.json()["status"] == "dropped"


def test_cannot_drop_yourself(client, seed):
    csrf = login(client, "prof")
    r = client.delete(
        f"/api/v1/offerings/{seed.offering_id}/roster/prof", headers={"X-CSRF-Token": csrf}
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "self_drop"


def test_cannot_drop_the_last_instructor(client, seed):
    """One click must not be able to lock everyone out of an offering."""
    with dbmod.get_sessionmaker()() as db:
        u = User(netid="prof2")
        db.add(u)
        db.flush()
        db.add(Enrollment(offering_id=seed.offering_id, user_id=u.id, role=Role.instructor))
        db.commit()

    csrf = login(client, "prof2")
    # Two instructors: dropping the other one is allowed.
    assert (
        client.delete(
            f"/api/v1/offerings/{seed.offering_id}/roster/prof", headers={"X-CSRF-Token": csrf}
        ).status_code
        == 200
    )
    # Now prof2 is the last one, and cannot be removed by anyone.
    with dbmod.get_sessionmaker()() as db:
        u = User(netid="prof3")
        db.add(u)
        db.flush()
        db.add(Enrollment(offering_id=seed.offering_id, user_id=u.id, role=Role.instructor))
        db.commit()
    csrf = login(client, "prof3")
    client.delete(
        f"/api/v1/offerings/{seed.offering_id}/roster/prof2", headers={"X-CSRF-Token": csrf}
    )
    r = client.delete(
        f"/api/v1/offerings/{seed.offering_id}/roster/prof3", headers={"X-CSRF-Token": csrf}
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "self_drop"


def test_unknown_netid_is_404(client, seed):
    csrf = login(client, "prof")
    r = client.delete(
        f"/api/v1/offerings/{seed.offering_id}/roster/nobody", headers={"X-CSRF-Token": csrf}
    )
    assert r.status_code == 404


def test_students_and_tas_cannot_edit_the_roster(client, seed):
    for netid in ("f00abc1", "ta1"):
        csrf = login(client, netid)
        assert (
            client.post(
                f"/api/v1/offerings/{seed.offering_id}/roster/students",
                headers={"X-CSRF-Token": csrf},
                json={"netid": "sneaky"},
            ).status_code
            == 403
        )
        assert (
            client.delete(
                f"/api/v1/offerings/{seed.offering_id}/roster/f00xyz9",
                headers={"X-CSRF-Token": csrf},
            ).status_code
            == 403
        )
