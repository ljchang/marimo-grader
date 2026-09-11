"""Stable, human-readable assignment URLs for the course book and launch buttons.

    /a/{course}/{term}/assignments.json         metadata for every published assignment
    /a/{course}/{term}/{slug}/student.py[?v=N]  the distributed student notebook (exact bytes)
    /a/{course}/{term}/{slug}/molab             302 → MoLab with the notebook in the URL fragment

These are unauthenticated when the offering allows it (``settings.public_student_notebooks``,
default on: student versions contain no solutions and the public book republishes them).
Instructor artifacts are never reachable from here.
"""

from __future__ import annotations

import lzstring
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from grader.auth.deps import api_error
from grader.config import get_settings
from grader.db import get_db
from grader.models import Artifact, Assignment, AssignmentVersion, Course, Offering
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
        "assignments": [assignment_meta(a, course, term) for a in rows if a.versions],
    }


@router.get("/a/{course}/{term}/{slug}/student.py")
def public_student_notebook(
    course: str, term: str, slug: str, v: int | None = None, db: Session = Depends(get_db)
):
    o = resolve_offering(db, course, term)
    version = _version(_assignment(db, o, slug), v)
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
    course: str, term: str, slug: str, v: int | None = None, db: Session = Depends(get_db)
):
    o = resolve_offering(db, course, term)
    version = _version(_assignment(db, o, slug), v)
    content = _student_bytes(db, version).decode("utf-8", "replace")
    compressed = lzstring.LZString().compressToEncodedURIComponent(content)
    return RedirectResponse(MOLAB_TEMPLATE.format(content_lz=compressed), status_code=302)
