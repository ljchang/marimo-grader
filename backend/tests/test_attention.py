"""Needs attention: failures grouped by cause, said in words, and a retry
whose outcome can be followed."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from grader import db as dbmod
from grader.models import GraderRun, RunKind, RunStatus, Submission, SubmissionStatus
from grader.services.failures import classify
from tests.conftest import login, notebook_token

SAFETY = "RuntimeError: notebook execution failed: safety check failed: denied import: os"
TWICE = "RuntimeError: marimo export failed: MultipleDefinitionError: The variable 'pd' was defined by another cell"


def test_classify_says_whose_move_it_is():
    c = classify(SAFETY)
    assert (c.kind, c.retry_helps) == ("safety", False) and "denied import: os" in c.summary
    c = classify(TWICE)
    assert (c.kind, c.retry_helps) == ("notebook", False) and "`pd`" in c.summary
    assert classify("RuntimeError: timed out after 180s: python -m marimo").retry_helps
    assert classify("no check cell ran (x; 0 cell error(s)) -- ...").kind == "data"
    c = classify("KeyError: 'boom'")
    assert (c.kind, c.retry_helps) == ("grader", True) and "KeyError" in c.summary
    assert classify(None).retry_helps


def _failed(client, seed, netid, error, qid="glm-q01"):
    r = client.post(
        "/api/v1/submissions",
        headers={"Authorization": f"Bearer {notebook_token(client, netid)}"},
        json={
            "assignment_version_id": str(seed.version_id),
            "question_id": qid,
            "notebook": "x = 1\n",
        },
    )
    sid = uuid.UUID(r.json()["id"])
    with dbmod.get_sessionmaker()() as db:
        sub = db.get(Submission, sid)
        for run in sub.runs:
            run.status = RunStatus.succeeded
        db.add(
            GraderRun(
                submission_id=sid, kind=RunKind.autograde, status=RunStatus.failed, error=error
            )
        )
        sub.status = SubmissionStatus.failed
        db.commit()
    return str(sid)


def _triage(client, seed):
    login(client, "prof")
    t = client.get(f"/api/v1/offerings/{seed.offering_id}/triage").json()
    client.cookies.clear()
    return t


def test_failures_are_grouped_by_cause(client, seed):
    a = _failed(client, seed, "f00abc1", SAFETY)
    b = _failed(client, seed, "f00xyz9", SAFETY, qid="glm-q05")
    c = _failed(client, seed, "f00abc1", TWICE)
    groups = _triage(client, seed)["failure_groups"]
    assert [len(g["submissions"]) for g in groups] == [2, 1]
    safety, twice = groups
    assert safety["kind"] == "safety" and not safety["retry_helps"]
    assert sorted(safety["qids"]) == ["glm-q01", "glm-q05"]
    assert {r["submission_id"] for r in safety["submissions"]} == {a, b}
    assert twice["submissions"][0]["submission_id"] == c and "`pd`" in twice["summary"]


def _csrf(client):
    return login(client, "prof")


def _status(client, seed, ids):
    login(client, "prof")
    r = client.get(
        f"/api/v1/offerings/{seed.offering_id}/retry-status", params={"ids": ",".join(ids)}
    )
    client.cookies.clear()
    return {row["submission_id"]: row for row in r.json()}


def test_retry_all_and_follow_the_outcome(client, seed):
    a = _failed(client, seed, "f00abc1", SAFETY)
    b = _failed(client, seed, "f00xyz9", SAFETY)
    csrf = _csrf(client)
    r = client.post(
        f"/api/v1/offerings/{seed.offering_id}/retry",
        json={"submission_ids": [a, b, str(uuid.uuid4())]},
        headers={"X-CSRF-Token": csrf},
    )
    client.cookies.clear()
    assert sorted(r.json()["requeued"]) == sorted([a, b])
    st = _status(client, seed, [a, b])
    assert st[a]["state"] == st[b]["state"] == "queued"

    with dbmod.get_sessionmaker()() as db:
        runs = {
            str(r.submission_id): r
            for r in db.scalars(
                select(GraderRun).where(
                    GraderRun.status == RunStatus.queued, GraderRun.kind == RunKind.autograde
                )
            )
        }
        runs[a].status = RunStatus.running
        runs[b].status, runs[b].error = RunStatus.failed, SAFETY
        db.get(Submission, uuid.UUID(b)).status = SubmissionStatus.failed
        db.commit()
    st = _status(client, seed, [a, b])
    assert st[a]["state"] == "running"
    assert st[b]["state"] == "failed" and st[b]["cause"]["kind"] == "safety"

    with dbmod.get_sessionmaker()() as db:
        runs[a] = db.get(GraderRun, runs[a].id)
        runs[a].status = RunStatus.succeeded
        db.get(Submission, uuid.UUID(a)).status = SubmissionStatus.graded
        db.commit()
    assert _status(client, seed, [a])[a]["state"] == "graded"


def test_hand_graded_question_waits_after_its_run(client, seed):
    a = _failed(client, seed, "f00abc1", "KeyError: 'boom'", qid="glm-q05")
    csrf = _csrf(client)
    client.post(
        f"/api/v1/offerings/{seed.offering_id}/retry",
        json={"submission_ids": [a]},
        headers={"X-CSRF-Token": csrf},
    )
    client.cookies.clear()
    with dbmod.get_sessionmaker()() as db:
        for r in db.scalars(select(GraderRun).where(GraderRun.status == RunStatus.queued)):
            r.status = RunStatus.succeeded
        db.commit()  # the submission stays 'received': it now waits for a person
    assert _status(client, seed, [a])[a]["state"] == "waiting_for_grade"


def test_students_cannot_retry_or_watch(client, seed):
    a = _failed(client, seed, "f00abc1", SAFETY)
    csrf = login(client, "f00abc1")
    r = client.post(
        f"/api/v1/offerings/{seed.offering_id}/retry",
        json={"submission_ids": [a]},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 403
    assert (
        client.get(f"/api/v1/offerings/{seed.offering_id}/retry-status?ids={a}").status_code == 403
    )
