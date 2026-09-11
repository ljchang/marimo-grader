"""Tenant isolation: no staff access across offerings, no student access to other students.

Two offerings, each with its own instructor, TA, and student. Every route that can expose
student data is exercised from the wrong side and must refuse (403 or 404; 404 is used where
the existence of the resource itself should not be revealed).
"""

import pytest

from grader import db as dbmod
from grader.models import (
    Assignment,
    AssignmentVersion,
    Course,
    Enrollment,
    GradingMode,
    Offering,
    Question,
    Role,
    Section,
    User,
)
from grader.services.artifacts import ArtifactStore
from tests.conftest import login, notebook_token


@pytest.fixture
def two(seed):
    """Add a second course/offering ('stats/2026-fall') with its own people and assignment."""
    with dbmod.get_sessionmaker()() as db:
        c = Course(slug="stats", title="Stats")
        db.add(c)
        db.flush()
        o = Offering(course_id=c.id, term="2026-fall", title="Stats Fall")
        db.add(o)
        db.flush()
        people = {}
        for netid, role in (("prof2", Role.instructor), ("ta2", Role.ta), ("stu2", Role.student)):
            u = User(netid=netid, display_name=netid)
            db.add(u)
            db.flush()
            db.add(Enrollment(offering_id=o.id, user_id=u.id, role=role))
            people[netid] = u.id
        a = Assignment(offering_id=o.id, slug="hw1", title="HW1", settings={})
        db.add(a)
        db.flush()
        q = Question(
            assignment_id=a.id,
            qid="hw1-q01",
            title="Q1",
            max_points=5,
            auto_points_max=0,
            grading_mode=GradingMode.manual,
        )
        db.add(q)
        st = ArtifactStore()
        art = st.put(db, b"# x\n", kind="notebook", content_type="text/x-python")
        v = AssignmentVersion(
            assignment_id=a.id,
            version=1,
            instructor_artifact_id=art.id,
            student_artifact_id=art.id,
            published_by=people["prof2"],
            question_snapshot=[{"qid": "hw1-q01"}],
        )
        db.add(v)
        db.commit()
        seed.other_offering_id = o.id
        seed.other_assignment_id = a.id
        seed.other_version_id = v.id
        seed.other_question_id = q.id
    return seed


def _submit(client, token, version_id, qid):
    r = client.post(
        "/api/v1/submissions",
        headers={"Authorization": f"Bearer {token}"},
        json={"assignment_version_id": str(version_id), "question_id": qid, "notebook": "# nb\n"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_staff_cannot_reach_another_offering(client, two):
    # Data in offering 1 (neuroimaging): a submission by f00abc1.
    sid = _submit(client, notebook_token(client, "f00abc1"), two.version_id, "glm-q05")
    o1 = two.offering_id
    for who in ("prof2", "ta2"):
        client.cookies.clear()
        csrf = login(client, who)
        blocked = [
            client.get(f"/api/v1/offerings/{o1}"),
            client.get(f"/api/v1/offerings/{o1}/assignments"),
            client.get(f"/api/v1/offerings/{o1}/triage"),
            client.get(f"/api/v1/offerings/{o1}/grid"),
            client.get(f"/api/v1/offerings/{o1}/queue?question_id={two.q_manual_id}"),
            client.get(f"/api/v1/offerings/{o1}/students/f00abc1"),
            client.get(f"/api/v1/offerings/{o1}/roster"),
            client.get(f"/api/v1/offerings/{o1}/audit"),
            client.get(f"/api/v1/offerings/{o1}/export/canvas?assignment_ids={two.assignment_id}"),
            client.get(f"/api/v1/offerings/{o1}/me"),
            client.get(f"/api/v1/offerings/{o1}/me/submissions"),
            client.get(f"/api/v1/submissions/{sid}"),
            client.get(f"/api/v1/submissions/{sid}/notebook"),
            client.get(f"/api/v1/assignment-versions/{two.version_id}/student.py"),
            client.post(
                f"/api/v1/submissions/{sid}/score",
                json={"manual_points": 5},
                headers={"X-CSRF-Token": csrf},
            ),
            client.post(
                f"/api/v1/offerings/{o1}/roster/staff",
                json={"netid": "ta2", "role": "ta"},
                headers={"X-CSRF-Token": csrf},
            ),
            client.post(
                f"/api/v1/offerings/{o1}/assignments",
                json={"slug": "x", "title": "X"},
                headers={"X-CSRF-Token": csrf},
            ),
        ]
        for r in blocked:
            assert r.status_code in (403, 404), (who, r.request.url, r.status_code, r.text[:120])
        # The only offering they can see is their own.
        mine = client.get("/api/v1/offerings").json()
        assert [o["course_slug"] for o in mine] == ["stats"]


def test_ta_scoped_to_sections_cannot_see_other_sections(client, two):
    # Put f00abc1 in section 01 and f00xyz9 in section 02; scope ta1 to section 02.
    with dbmod.get_sessionmaker()() as db:
        o = db.get(Offering, two.offering_id)
        s1 = Section(offering_id=o.id, name="01")
        s2 = Section(offering_id=o.id, name="02")
        db.add_all([s1, s2])
        db.flush()
        for netid, sec in (("f00abc1", s1), ("f00xyz9", s2)):
            u = db.query(User).filter_by(netid=netid).one()
            e = db.query(Enrollment).filter_by(offering_id=o.id, user_id=u.id).one()
            e.section_id = sec.id
        ta = db.query(User).filter_by(netid="ta1").one()
        te = db.query(Enrollment).filter_by(offering_id=o.id, user_id=ta.id).one()
        te.ta_sections = [str(s2.id)]
        db.commit()
    sid1 = _submit(client, notebook_token(client, "f00abc1"), two.version_id, "glm-q05")
    sid2 = _submit(client, notebook_token(client, "f00xyz9"), two.version_id, "glm-q05")
    client.cookies.clear()
    csrf = login(client, "ta1")
    assert client.get(f"/api/v1/submissions/{sid1}").status_code == 404
    assert client.get(f"/api/v1/submissions/{sid2}").status_code == 200
    assert client.get(f"/api/v1/offerings/{two.offering_id}/students/f00abc1").status_code == 404
    assert client.get(f"/api/v1/offerings/{two.offering_id}/students/f00xyz9").status_code == 200
    grid = client.get(f"/api/v1/offerings/{two.offering_id}/grid").json()
    assert [s["netid"] for s in grid["students"]] == ["f00xyz9"]
    queue = client.get(
        f"/api/v1/offerings/{two.offering_id}/queue?question_id={two.q_manual_id}"
    ).json()
    assert [i["netid"] for i in queue["items"]] == ["f00xyz9"]
    roster = client.get(f"/api/v1/offerings/{two.offering_id}/roster").json()
    assert "f00abc1" not in [r["netid"] for r in roster if r["role"] == "student"]
    r = client.post(
        f"/api/v1/submissions/{sid1}/score",
        json={"manual_points": 1},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 404


def test_students_cannot_see_each_other(client, two):
    t1 = notebook_token(client, "f00abc1")
    t2 = notebook_token(client, "f00xyz9")
    sid1 = _submit(client, t1, two.version_id, "glm-q05")
    h2 = {"Authorization": f"Bearer {t2}"}
    for r in (
        client.get(f"/api/v1/submissions/{sid1}", headers=h2),
        client.get(f"/api/v1/submissions/{sid1}/notebook", headers=h2),
        client.get(f"/api/v1/submissions/{sid1}/render", headers=h2),
        client.get(f"/api/v1/offerings/{two.offering_id}/students/f00abc1", headers=h2),
        client.get(f"/api/v1/offerings/{two.offering_id}/grid", headers=h2),
        client.get(f"/api/v1/offerings/{two.offering_id}/triage", headers=h2),
        client.get(f"/api/v1/offerings/{two.offering_id}/roster", headers=h2),
        client.get(f"/api/v1/offerings/{two.offering_id}/audit", headers=h2),
        client.get(f"/api/v1/offerings/{two.offering_id}/events", headers=h2),
    ):
        assert r.status_code in (403, 404), (r.request.url, r.status_code)
    # Own submissions list never includes another student's attempts.
    login(client, "f00xyz9")
    mine = client.get(f"/api/v1/offerings/{two.offering_id}/me/submissions").json()
    assert all(s["netid"] == "f00xyz9" for s in mine) and sid1 not in [s["id"] for s in mine]
    # A student cannot submit into an offering they are not enrolled in.
    r = client.post(
        "/api/v1/submissions",
        headers={"Authorization": f"Bearer {t1}"},
        json={
            "assignment_version_id": str(two.other_version_id),
            "question_id": "hw1-q01",
            "notebook": "# nb\n",
        },
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "not_enrolled"


def test_dropped_student_loses_access(client, two):
    t1 = notebook_token(client, "f00abc1")
    with dbmod.get_sessionmaker()() as db:
        from grader.models import EnrollmentStatus

        u = db.query(User).filter_by(netid="f00abc1").one()
        e = db.query(Enrollment).filter_by(offering_id=two.offering_id, user_id=u.id).one()
        e.status = EnrollmentStatus.dropped
        db.commit()
    r = client.post(
        "/api/v1/submissions",
        headers={"Authorization": f"Bearer {t1}"},
        json={
            "assignment_version_id": str(two.version_id),
            "question_id": "glm-q01",
            "notebook": "# nb\n",
        },
    )
    assert r.status_code == 403
    assert (
        client.get(
            f"/api/v1/offerings/{two.offering_id}/me", headers={"Authorization": f"Bearer {t1}"}
        ).status_code
        == 404
    )
