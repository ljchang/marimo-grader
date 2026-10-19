"""Stable, human-readable assignment URLs for the course book and launch buttons.

    /a/{course}/{term}/assignments.json         metadata for every published assignment
    /a/{course}/{term}/{slug}/student.py[?v=N]  the distributed student notebook (exact bytes)
    /a/{course}/{term}/{slug}/molab             302 → MoLab with the notebook in the URL fragment
    /a/{course}/{term}/{slug}/launch            302 → the student portal (sign-in first if needed)

These are unauthenticated when the offering allows it (``settings.public_student_notebooks``,
default on: student versions contain no solutions and the public book republishes them).
Instructor artifacts are never reachable from here.

An assignment with ``visibility: enrolled`` (an exam) is the exception: it is left out
of ``assignments.json`` and its notebook is served only to a signed-in member of the
offering -- by session cookie or notebook Bearer token -- and to students only inside
the ``release_at``..``close_at`` window (services/availability.py). To anyone else it
does not exist.
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote

import lzstring
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from grader.auth.deps import Principal, api_error, optional_principal
from grader.config import get_settings
from grader.db import get_db
from grader.models import Artifact, Assignment, AssignmentVersion, Course, Offering
from grader.services import availability
from grader.services.artifacts import store
from grader.util import iso

router = APIRouter(tags=["public"])

MOLAB_TEMPLATE = "https://molab.marimo.io/new/#code/{content_lz}"


def resolve_offering(db: Session, course: str, term: str) -> Offering:
    o = db.scalar(select(Offering).join(Course).where(Course.slug == course, Offering.term == term))
    if o is None or not (o.settings or {}).get("public_student_notebooks", True):
        raise api_error(404, "not_found", "offering not found")
    return o


def _assignment(db: Session, o: Offering, slug: str) -> Assignment:
    a = db.scalar(select(Assignment).where(Assignment.offering_id == o.id, Assignment.slug == slug))
    if a is None or not a.versions:
        raise api_error(404, "not_found", "assignment not found")
    return a


_REFUSALS = {
    "sign_in": (401, "unauthenticated", "sign in to open this assignment"),
    "not_found": (404, "not_found", "assignment not found"),
    "upcoming": (403, "not_released", "this assignment is not open yet"),
    "closed": (403, "closed", "this assignment has closed"),
}


def _gate(db: Session, p: Principal | None, a: Assignment) -> str | None:
    return availability.fetch_refusal(db, p.user if p else None, a, datetime.now(UTC))


def _refuse(reason: str):
    status, code, message = _REFUSALS[reason]
    return api_error(status, code, message)


def _sign_in_to_portal(o: Offering) -> RedirectResponse:
    nxt = quote(f"/me/{o.id}", safe="")
    return RedirectResponse(f"{get_settings().base_url}/api/v1/auth/login?next={nxt}", 302)


def _version(a: Assignment, v: int | None) -> AssignmentVersion:
    if v is None:
        return a.versions[-1]
    for row in a.versions:
        if row.version == v:
            return row
    raise api_error(404, "not_found", f"version {v} not found")


def _student_bytes(db: Session, version: AssignmentVersion) -> bytes:
    art = db.get(Artifact, version.student_artifact_id)
    assert art is not None
    return store().get(art)


def alias_base(course: str, term: str, slug: str) -> str:
    return f"{get_settings().base_url}/a/{course}/{term}/{slug}"


def assignment_meta(a: Assignment, course: str, term: str) -> dict:
    latest = a.versions[-1]
    base = alias_base(course, term, a.slug)
    settings = a.settings or {}
    return {
        "slug": a.slug,
        "title": a.title,
        "assignment_id": str(a.id),
        "version": latest.version,
        "version_id": str(latest.id),
        "published_at": iso(latest.created_at),
        "due_at": settings.get("due_at"),
        "points": float(sum(float(q.max_points) for q in a.questions if q.active)),
        "environments": settings.get("environments", ["molab"]),
        "questions": [
            {
                "qid": q.qid,
                "title": q.title,
                "max_points": float(q.max_points),
                "grading_mode": q.grading_mode.value,
            }
            for q in a.questions
            if q.active
        ],
        "student_url": f"{base}/student.py",
        "molab_url": f"{base}/molab",
    }


@router.get("/a/{course}/{term}/assignments.json")
def list_public_assignments(course: str, term: str, db: Session = Depends(get_db)):
    o = resolve_offering(db, course, term)
    rows = db.scalars(
        select(Assignment).where(Assignment.offering_id == o.id).order_by(Assignment.created_at)
    ).all()
    return {
        "course": course,
        "term": term,
        "offering_id": str(o.id),
        "title": o.title,
        "assignments": [
            assignment_meta(a, course, term)
            for a in rows
            if a.versions and not availability.is_private(a)
        ],
    }


@router.get("/a/{course}/{term}/{slug}/student.py")
def public_student_notebook(
    course: str,
    term: str,
    slug: str,
    v: int | None = None,
    db: Session = Depends(get_db),
    p: Principal | None = Depends(optional_principal),
):
    o = resolve_offering(db, course, term)
    a = _assignment(db, o, slug)
    if (reason := _gate(db, p, a)) is not None:
        raise _refuse(reason)
    version = _version(a, v)
    return Response(
        content=_student_bytes(db, version),
        media_type="text/x-python",
        headers={
            "Content-Disposition": f'inline; filename="{slug}.py"',
            "X-Grader-Version": str(version.version),
            "X-Grader-Version-Id": str(version.id),
            "Cache-Control": "no-cache",
        },
    )


@router.get("/a/{course}/{term}/{slug}/molab")
def molab_redirect(
    course: str,
    term: str,
    slug: str,
    v: int | None = None,
    db: Session = Depends(get_db),
    p: Principal | None = Depends(optional_principal),
):
    o = resolve_offering(db, course, term)
    a = _assignment(db, o, slug)
    if (reason := _gate(db, p, a)) is not None:
        # A browser following a link: send a signed-out reader to sign in rather
        # than to a JSON error page.
        if reason == "sign_in":
            return _sign_in_to_portal(o)
        raise _refuse(reason)
    version = _version(a, v)
    content = _student_bytes(db, version).decode("utf-8", "replace")
    compressed = lzstring.LZString().compressToEncodedURIComponent(content)
    return RedirectResponse(MOLAB_TEMPLATE.format(content_lz=compressed), status_code=302)


@router.get("/a/{course}/{term}/{slug}/launch")
def launch(
    course: str,
    term: str,
    slug: str,
    db: Session = Depends(get_db),
    p: Principal | None = Depends(optional_principal),
):
    """The stable link a course page gives for a private assignment.

    It lands on the student portal, which shows the window and offers *Open in
    molab* and *Download*. A signed-out reader is sent through sign-in first. The
    link reveals nothing by itself: an outsider who follows it reaches a sign-in
    page and then an offering they are not enrolled in.
    """
    o = resolve_offering(db, course, term)
    a = _assignment(db, o, slug)
    if p is None:
        return _sign_in_to_portal(o)
    if availability.fetch_refusal(db, p.user, a, datetime.now(UTC)) == "not_found":
        raise _refuse("not_found")
    return RedirectResponse(f"{get_settings().frontend_url}/me/{o.id}#{a.slug}", 302)
