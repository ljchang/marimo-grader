"""Platform-admin routes: courses, offerings, instructors. No student data here."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from grader.auth.deps import api_error, require_platform_admin
from grader.db import get_db
from grader.models import Course, Enrollment, EnrollmentStatus, Offering, Role, User
from grader.services import audit

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_platform_admin)])


def _course(c: Course) -> dict:
    return {
        "id": str(c.id),
        "slug": c.slug,
        "title": c.title,
        "offerings": [
            {
                "id": str(o.id),
                "term": o.term,
                "title": o.title,
                "instructors": [
                    e.user.netid
                    for e in o.enrollments
                    if e.role == Role.instructor and e.status == EnrollmentStatus.active
                ],
            }
            for o in c.offerings
        ],
    }


@router.get("/courses")
def list_courses(db: Session = Depends(get_db)):
    return [_course(c) for c in db.scalars(select(Course).order_by(Course.slug))]


class CourseIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    title: str


@router.post("/courses", status_code=201)
def create_course(
    body: CourseIn, admin: User = Depends(require_platform_admin), db: Session = Depends(get_db)
):
    if db.scalar(select(Course).where(Course.slug == body.slug)):
        raise api_error(409, "exists", "course slug exists")
    c = Course(slug=body.slug, title=body.title)
    db.add(c)
    db.flush()
    audit.record(
        db,
        actor_id=admin.id,
        offering_id=None,
        entity="course",
        entity_id=c.id,
        action="create",
        after=body.model_dump(),
    )
    return _course(c)


class OfferingIn(BaseModel):
    term: str = Field(pattern=r"^[0-9]{4}-[a-z]+$")
    title: str
    settings: dict = Field(default_factory=dict)


@router.post("/courses/{course_id}/offerings", status_code=201)
def create_offering(
    course_id: uuid.UUID,
    body: OfferingIn,
    admin: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    c = db.get(Course, course_id)
    if c is None:
        raise api_error(404, "not_found", "course not found")
    if db.scalar(select(Offering).where(Offering.course_id == c.id, Offering.term == body.term)):
        raise api_error(409, "exists", "offering exists for that term")
    o = Offering(course_id=c.id, term=body.term, title=body.title, settings=body.settings)
    db.add(o)
    db.flush()
    audit.record(
        db,
        actor_id=admin.id,
        offering_id=o.id,
        entity="offering",
        entity_id=o.id,
        action="create",
        after=body.model_dump(),
    )
    return {"id": str(o.id), "term": o.term, "title": o.title}


class InstructorIn(BaseModel):
    netid: str
    display_name: str | None = None


@router.post("/offerings/{offering_id}/instructors", status_code=201)
def add_instructor(
    offering_id: uuid.UUID,
    body: InstructorIn,
    admin: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    o = db.get(Offering, offering_id)
    if o is None:
        raise api_error(404, "not_found", "offering not found")
    netid = body.netid.strip().lower()
    user = db.scalar(select(User).where(User.netid == netid))
    if user is None:
        user = User(netid=netid, display_name=body.display_name)
        db.add(user)
        db.flush()
    e = db.scalar(
        select(Enrollment).where(Enrollment.offering_id == o.id, Enrollment.user_id == user.id)
    )
    if e is None:
        e = Enrollment(offering_id=o.id, user_id=user.id, role=Role.instructor)
        db.add(e)
    else:
        e.role, e.status = Role.instructor, EnrollmentStatus.active
    db.flush()
    audit.record(
        db,
        actor_id=admin.id,
        offering_id=o.id,
        entity="enrollment",
        entity_id=e.id,
        action="instructor",
        after={"netid": netid},
    )
    return {"netid": netid, "role": "instructor"}


class AdminIn(BaseModel):
    netid: str
    platform_admin: bool = True


@router.post("/admins")
def set_admin(
    body: AdminIn, admin: User = Depends(require_platform_admin), db: Session = Depends(get_db)
):
    netid = body.netid.strip().lower()
    user = db.scalar(select(User).where(User.netid == netid))
    if user is None:
        user = User(netid=netid)
        db.add(user)
    user.platform_admin = body.platform_admin
    db.flush()
    audit.record(
        db,
        actor_id=admin.id,
        offering_id=None,
        entity="user",
        entity_id=user.id,
        action="platform_admin",
        after={"platform_admin": body.platform_admin},
    )
    return {"netid": netid, "platform_admin": user.platform_admin}
