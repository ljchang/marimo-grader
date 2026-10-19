"""When an assignment is open, and to whom.

Three instants in ``Assignment.settings``, all ISO 8601 and all optional:

    release_at   the notebook can be opened and its storage data read
    due_at       the submission deadline (``late_policy`` decides what happens after)
    close_at     the hard end: no data, no notebook download, no submissions

``visibility`` decides who may fetch the student notebook at all: ``public``
(anyone, the default -- student notebooks carry no solutions and the course
book republishes them) or ``enrolled`` (members of the offering only, inside
the window; staff at any time). An exam is ``enrolled``.

A private assignment opens only once it has a ``release_at``: until then it is
``upcoming`` -- not listed for students, not downloadable, its data not granted,
not submittable -- however long it is being built. Staff are never held to the
window, so an instructor can open, run and submit their own assignment before
students see it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from grader.auth.deps import membership_for
from grader.models import Assignment, User

VISIBILITIES = ("public", "enrolled")
LATE_POLICIES = (None, "accept", "reject")


def parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@dataclass(frozen=True)
class Window:
    release_at: datetime | None
    due_at: datetime | None
    close_at: datetime | None
    private: bool = False

    @classmethod
    def of(cls, a: Assignment) -> Window:
        s = a.settings or {}
        return cls(
            parse(s.get("release_at")),
            parse(s.get("due_at")),
            parse(s.get("close_at")),
            is_private(a),
        )

    def state(self, now: datetime) -> str:
        """``upcoming`` before release (and, for a private assignment, until it has a
        release date at all), ``closed`` from close, otherwise ``open``."""
        if self.private and self.release_at is None:
            return "upcoming"
        if self.release_at and now < self.release_at:
            return "upcoming"
        if self.close_at and now >= self.close_at:
            return "closed"
        return "open"

    def is_open(self, now: datetime) -> bool:
        return self.state(now) == "open"

    def is_late(self, at: datetime) -> bool:
        if at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        return bool(self.due_at and at > self.due_at)


def is_private(a: Assignment) -> bool:
    return (a.settings or {}).get("visibility", "public") == "enrolled"


def submission_refusal(a: Assignment, now: datetime) -> tuple[str, str] | None:
    """``(code, message)`` when a student may not submit right now, else None."""
    w = Window.of(a)
    state = w.state(now)
    if state == "upcoming":
        when = f"opens at {w.release_at.isoformat()}" if w.release_at else "is not open yet"
        return "not_released", f"this assignment {when}"
    if state == "closed":
        return "closed", f"this assignment closed at {w.close_at.isoformat()}"
    if (a.settings or {}).get("late_policy") == "reject" and w.is_late(now):
        return "past_due", f"the deadline was {w.due_at.isoformat()}"
    return None


def json_for(a: Assignment, now: datetime) -> dict:
    """What a notebook or the portal needs to explain the window to a student."""
    w = Window.of(a)
    return {
        "state": w.state(now),
        "visibility": (a.settings or {}).get("visibility", "public"),
        "release_at": w.release_at.isoformat() if w.release_at else None,
        "due_at": w.due_at.isoformat() if w.due_at else None,
        "close_at": w.close_at.isoformat() if w.close_at else None,
        "past_due": w.is_late(now),
    }


def fetch_refusal(db: Session, user: User | None, a: Assignment, now: datetime) -> str | None:
    """Why ``user`` may not download a private assignment's student notebook now.

    Returns ``sign_in`` (nobody is signed in), ``not_found`` (not a member -- the
    assignment's existence is not confirmed to outsiders), ``upcoming`` or
    ``closed`` (a student outside the window), or None when the fetch may go
    ahead. Public assignments are always None: their gate is the offering's
    ``public_student_notebooks`` flag, checked by the caller as before.
    """
    if not is_private(a):
        return None
    if user is None:
        return "sign_in"
    m = membership_for(db, user, a.offering_id)
    if m is None:
        return "not_found"
    if m.is_staff():
        return None
    state = Window.of(a).state(now)
    return None if state == "open" else state
