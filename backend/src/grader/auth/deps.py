"""FastAPI dependencies that resolve the caller and enforce offering-scoped roles.

Two principals:

* ``current_user`` — from the session cookie (web UI) or a notebook Bearer token.
* ``require(role, ...)`` — resolves the caller's enrollment in the offering named
  in the path and refuses unless its role is in the allowed set.

Platform admins are deliberately *not* granted access to student data by these
helpers; admin routes use ``require_platform_admin`` and never touch submissions.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from grader.auth.sessions import load_session
from grader.auth.tokens import TokenError, verify_notebook_token
from grader.db import get_db
from grader.models import Enrollment, EnrollmentStatus, Offering, RevokedToken, Role, User

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def api_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


@dataclass
class Principal:
    user: User
    via: str  # "session" | "token"
    session_csrf: str | None = None


def _bearer(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    if h.lower().startswith("bearer "):
        return h[7:].strip()
    return None


def optional_principal(request: Request, db: Session = Depends(get_db)) -> Principal | None:
    token = _bearer(request)
    if token:
        try:
            claims = verify_notebook_token(token)
        except TokenError as e:
            raise api_error(401, "invalid_token", str(e)) from e
        if db.get(RevokedToken, claims["jti"]):
            raise api_error(401, "revoked_token", "token revoked")
        user = db.scalar(select(User).where(User.netid == claims["sub"]))
        if user is None:
            raise api_error(401, "unknown_user", "no such user")
        return Principal(user=user, via="token")
    sess = load_session(db, request)
    if sess is None:
        return None
    user = db.get(User, sess.user_id)
    if user is None:
        return None
    if request.method in MUTATING and request.headers.get("x-csrf-token") != sess.csrf_token:
        raise api_error(403, "csrf", "missing or invalid X-CSRF-Token")
    return Principal(user=user, via="session", session_csrf=sess.csrf_token)


def current_principal(p: Principal | None = Depends(optional_principal)) -> Principal:
    if p is None:
        raise api_error(401, "unauthenticated", "sign in required")
    return p


def current_user(p: Principal = Depends(current_principal)) -> User:
    return p.user


def require_platform_admin(user: User = Depends(current_user)) -> User:
    if not user.platform_admin:
        raise api_error(403, "forbidden", "platform admin required")
    return user


@dataclass
class Membership:
    user: User
    offering: Offering
    enrollment: Enrollment

    @property
    def role(self) -> Role:
        return self.enrollment.role

    def is_staff(self) -> bool:
        return self.role in (Role.ta, Role.instructor)

    def can_see_section(self, section_id: uuid.UUID | None) -> bool:
        """TA scoping: instructors see everything; TAs see their sections (or all if unscoped)."""
        if self.role == Role.instructor:
            return True
        if self.role == Role.ta:
            scoped = self.enrollment.ta_sections or []
            return not scoped or (section_id is not None and str(section_id) in scoped)
        return False


def membership_for(db: Session, user: User, offering_id: uuid.UUID) -> Membership | None:
    offering = db.get(Offering, offering_id)
    if offering is None:
        return None
    enr = db.scalar(
        select(Enrollment).where(
            Enrollment.offering_id == offering_id,
            Enrollment.user_id == user.id,
            Enrollment.status == EnrollmentStatus.active,
        )
    )
    if enr is None:
        return None
    return Membership(user=user, offering=offering, enrollment=enr)


def require(*roles: Role) -> Callable[..., Membership]:
    allowed = set(roles) or set(Role)

    def dep(
        offering_id: uuid.UUID,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ) -> Membership:
        m = membership_for(db, user, offering_id)
        if m is None:
            # 404 rather than 403 so non-members cannot probe offering ids.
            raise api_error(404, "not_found", "offering not found")
        if m.role not in allowed:
            raise api_error(
                403, "forbidden", f"requires one of: {', '.join(r.value for r in allowed)}"
            )
        return m

    return dep


require_member = require()
require_staff = require(Role.ta, Role.instructor)
require_instructor = require(Role.instructor)
