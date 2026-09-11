"""Test fixtures: in-memory SQLite, dev auth mode, temp artifact dir, seeded offering."""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.update(
    {
        "GRADER_ENV": "test",
        "GRADER_AUTH_MODE": "dev",
        "GRADER_DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "GRADER_BASE_URL": "http://testserver",
        "GRADER_FRONTEND_URL": "http://testserver",
    }
)

from fastapi.testclient import TestClient  # noqa: E402

from grader import config  # noqa: E402
from grader import db as dbmod
from grader.main import create_app  # noqa: E402
from grader.models import (  # noqa: E402
    Assignment,
    AssignmentVersion,
    Base,
    Course,
    Enrollment,
    GradingMode,
    Offering,
    Question,
    Role,
    User,
)
from grader.services.artifacts import ArtifactStore  # noqa: E402


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("GRADER_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    config.get_settings.cache_clear()
    dbmod.get_engine.cache_clear()
    dbmod.get_sessionmaker.cache_clear()
    Base.metadata.create_all(dbmod.get_engine())
    yield
    Base.metadata.drop_all(dbmod.get_engine())


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app)


class Seed:
    def __init__(self, db):
        self.db = db
        self.course = Course(slug="neuroimaging", title="Introduction to Neuroimaging Analysis")
        db.add(self.course)
        db.flush()
        self.offering = Offering(course_id=self.course.id, term="2026-fall", title="Fall 2026")
        db.add(self.offering)
        db.flush()
        self.instructor = self.user("prof", "Prof Example")
        self.ta = self.user("ta1", "TA One")
        self.student = self.user("f00abc1", "Alice Student")
        self.other = self.user("f00xyz9", "Bob Student")
        self.admin = self.user("admin", "Site Admin", platform_admin=True)
        self.enroll(self.instructor, Role.instructor)
        self.enroll(self.ta, Role.ta)
        self.enroll(self.student)
        self.enroll(self.other)
        self.assignment = Assignment(
            offering_id=self.offering.id,
            slug="glm",
            title="GLM",
            settings={"grade_policy": "latest", "attempts_allowed": None, "log_checks": True},
        )
        db.add(self.assignment)
        db.flush()
        self.q_auto = Question(
            assignment_id=self.assignment.id,
            qid="glm-q01",
            title="Load data",
            order=0,
            max_points=5,
            auto_points_max=5,
            grading_mode=GradingMode.auto,
            check_keys=["glm-q01"],
        )
        self.q_manual = Question(
            assignment_id=self.assignment.id,
            qid="glm-q05",
            title="Interpret",
            order=1,
            max_points=5,
            auto_points_max=0,
            grading_mode=GradingMode.manual,
        )
        db.add_all([self.q_auto, self.q_manual])
        db.flush()
        st = ArtifactStore()
        inst = st.put(db, b"# instructor\n", kind="notebook", content_type="text/x-python")
        stud = st.put(db, b"# student\n", kind="notebook", content_type="text/x-python")
        self.version = AssignmentVersion(
            assignment_id=self.assignment.id,
            version=1,
            instructor_artifact_id=inst.id,
            student_artifact_id=stud.id,
            published_by=self.instructor.id,
        )
        db.add(self.version)
        db.commit()

    def user(self, netid, name, platform_admin=False):
        u = User(netid=netid, display_name=name, platform_admin=platform_admin)
        self.db.add(u)
        self.db.flush()
        return u

    def enroll(self, user, role=Role.student):
        e = Enrollment(offering_id=self.offering.id, user_id=user.id, role=role)
        self.db.add(e)
        self.db.flush()
        return e


@pytest.fixture
def seed():
    with dbmod.get_sessionmaker()() as db:
        s = Seed(db)
        # detach ids we need
        s.offering_id = s.offering.id
        s.version_id = s.version.id
        s.assignment_id = s.assignment.id
        s.q_auto_id = s.q_auto.id
        s.q_manual_id = s.q_manual.id
        yield s


def login(client: TestClient, netid: str) -> str:
    """Dev login; returns the CSRF token."""
    r = client.get(f"/api/v1/auth/dev-login?netid={netid}", follow_redirects=False)
    assert r.status_code == 303, r.text
    r = client.get("/api/v1/auth/csrf")
    assert r.status_code == 200, r.text
    return r.json()["csrf_token"]


def notebook_token(client: TestClient, netid: str) -> str:
    """Run the device handshake end to end and return a Bearer token."""
    start = client.post("/api/v1/auth/device", json={"client": "tests"}).json()
    pending = client.post(
        "/api/v1/auth/device/token", json={"device_code": start["device_code"]}
    ).json()
    assert pending["status"] == "pending"
    login(client, netid)
    r = client.get(f"/api/v1/auth/device/verify?code={start['user_code']}")
    assert r.status_code == 200, r.text
    client.cookies.clear()
    tok = client.post(
        "/api/v1/auth/device/token", json={"device_code": start["device_code"]}
    ).json()
    assert tok["status"] == "approved", tok
    return tok["access_token"]


__all__ = ["login", "notebook_token", "uuid"]
