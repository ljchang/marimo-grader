"""Staff test submissions.

An instructor has to be able to run their own assignment the way a student
will -- sign in from the notebook, Check, Submit -- before handing it out.
Those attempts are graded and returned like any other, but must never reach
the gradebook.

The isolation is structural, not a flag: a submission hangs off the
submitter's own enrollment, and every view that surfaces grades selects
student enrollments only.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from grader import db as dbmod
from grader.models import Enrollment, QuestionGrade, Role, Submission, User
from tests.conftest import login, notebook_token


def _submit(client, token, seed, qid="glm-q01"):
    return client.post(
        "/api/v1/submissions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "assignment_version_id": str(seed.version_id),
            "question_id": qid,
            "notebook": "# attempt\nx = 1\n",
            "check_results": [{"label": "glm-q01: Load", "status": "success"}],
            "client": {"package": "tests", "version": "0", "env": "pytest"},
        },
    )


@pytest.mark.parametrize("netid,role", [("prof", "instructor"), ("ta1", "ta")])
def test_staff_may_submit_and_attempt_is_flagged(client, seed, netid, role):
    r = _submit(client, notebook_token(client, netid), seed)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["attempt_no"] == 1
    assert body["test"] is True, f"{role} attempt should be marked as a test"


def test_student_attempt_is_not_flagged(client, seed):
    r = _submit(client, notebook_token(client, "f00abc1"), seed)
    assert r.status_code == 201, r.text
    assert r.json()["test"] is False


def test_someone_with_no_enrollment_still_refused(client, seed):
    with dbmod.get_sessionmaker()() as db:
        db.add(User(netid="stranger"))
        db.commit()
    r = _submit(client, notebook_token(client, "stranger"), seed)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "not_enrolled"


def test_staff_attempt_lands_on_the_staff_enrollment(client, seed):
    _submit(client, notebook_token(client, "prof"), seed)
    with dbmod.get_sessionmaker()() as db:
        sub = db.scalar(select(Submission))
        assert sub is not None
        assert sub.enrollment.role == Role.instructor
        # ... and not on any student's row
        student_ids = {
            e.id for e in db.scalars(select(Enrollment).where(Enrollment.role == Role.student))
        }
        assert sub.enrollment_id not in student_ids


def test_staff_attempt_is_absent_from_the_class_grid(client, seed):
    """The grid is the gradebook's view of the roster."""
    _submit(client, notebook_token(client, "prof"), seed)
    login(client, "prof")
    r = client.get(f"/api/v1/offerings/{seed.offering_id}/grid")
    assert r.status_code == 200, r.text
    netids = {row["netid"] for row in r.json()["students"]}
    assert "prof" not in netids
    assert "f00abc1" in netids


def test_no_grade_row_is_written_for_a_staff_attempt(client, seed):
    """The worker skips the rollup, so nothing can leak into an export."""
    from grader.api.submissions import is_test

    _submit(client, notebook_token(client, "prof"), seed)
    with dbmod.get_sessionmaker()() as db:
        sub = db.scalar(select(Submission))
        assert is_test(sub) is True
        # recompute_question_grade is what would create this row
        assert (
            db.scalar(select(QuestionGrade).where(QuestionGrade.enrollment_id == sub.enrollment_id))
            is None
        )
