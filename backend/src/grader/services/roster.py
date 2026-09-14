"""Roster import adapters.

One internal shape — ``RosterRow(netid, display_name, section)`` — and one
adapter per source. Every import is a preview (adds / drops / moves /
unmatched) that the instructor confirms before it is applied.

Sources:
* ``canvas_csv`` — the gradebook export from Canvas. Columns include
  ``Student``, ``ID``, ``SIS User ID``, ``SIS Login ID``, ``Section`` and then
  one column per assignment. Login ID is the NetID at Dartmouth (verify: spike 6).
* ``banner`` — a class-list download from Banner self-service. Column names
  vary; we look for anything that resembles NetID, email, name, and section.
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from grader.models import Enrollment, EnrollmentStatus, Offering, Role, Section, User, utcnow

SOURCES = ("canvas_csv", "banner", "simple")

_CANVAS_SKIP_ROWS = ("points possible", "student, test", "test student")


@dataclass(frozen=True)
class RosterRow:
    netid: str
    display_name: str | None
    section: str | None
    raw_id: str | None = None  # source id when no netid could be derived


def _norm(s: str | None) -> str:
    return (s or "").strip()


def _netid_from_email(email: str | None) -> str | None:
    e = _norm(email).lower()
    if "@" in e and e.endswith("dartmouth.edu"):
        return e.split("@", 1)[0]
    return None


def parse_canvas_csv(text: str) -> list[RosterRow]:
    reader = csv.DictReader(io.StringIO(text))
    rows: list[RosterRow] = []
    for r in reader:
        student = _norm(r.get("Student"))
        if not student or student.lower() in _CANVAS_SKIP_ROWS:
            continue
        login = _norm(r.get("SIS Login ID")).lower()
        netid = _netid_from_email(login) or (login.split("@", 1)[0] if login else "")
        section = _norm(r.get("Section")) or None
        # Canvas names are "Last, First"
        if "," in student:
            last, first = [x.strip() for x in student.split(",", 1)]
            display = f"{first} {last}".strip()
        else:
            display = student
        rows.append(
            RosterRow(
                netid=netid,
                display_name=display or None,
                section=section,
                raw_id=_norm(r.get("SIS User ID")) or _norm(r.get("ID")) or None,
            )
        )
    return rows


_BANNER_NETID = re.compile(r"net\s*id|user\s*name|login", re.I)
_BANNER_EMAIL = re.compile(r"e-?mail", re.I)
_BANNER_NAME = re.compile(r"^name$|student\s*name|full\s*name", re.I)
_BANNER_FIRST = re.compile(r"first", re.I)
_BANNER_LAST = re.compile(r"last|surname", re.I)
_BANNER_SECTION = re.compile(r"section|crn", re.I)
_BANNER_ID = re.compile(r"^id$|banner|student\s*id", re.I)


def parse_banner(text: str) -> list[RosterRow]:
    """Banner class list as CSV (Excel exports should be saved as CSV first)."""
    sample = text[:4096]
    dialect = csv.Sniffer().sniff(sample, delimiters=",\t;") if sample.strip() else csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = reader.fieldnames or []

    def find(pat: re.Pattern) -> str | None:
        for h in headers:
            if h and pat.search(h):
                return h
        return None

    h_netid, h_email = find(_BANNER_NETID), find(_BANNER_EMAIL)
    h_name, h_first, h_last = find(_BANNER_NAME), find(_BANNER_FIRST), find(_BANNER_LAST)
    h_section, h_id = find(_BANNER_SECTION), find(_BANNER_ID)
    rows: list[RosterRow] = []
    for r in reader:
        netid = _norm(r.get(h_netid)).lower() if h_netid else ""
        if "@" in netid:
            netid = netid.split("@", 1)[0]
        if not netid and h_email:
            netid = _netid_from_email(r.get(h_email)) or ""
        if h_name and _norm(r.get(h_name)):
            name = _norm(r.get(h_name))
            if "," in name:
                last, first = [x.strip() for x in name.split(",", 1)]
                name = f"{first} {last}"
        else:
            name = " ".join(
                x
                for x in (
                    _norm(r.get(h_first)) if h_first else "",
                    _norm(r.get(h_last)) if h_last else "",
                )
                if x
            )
        if not netid and not name:
            continue
        rows.append(
            RosterRow(
                netid=netid,
                display_name=name or None,
                section=_norm(r.get(h_section)) or None if h_section else None,
                raw_id=_norm(r.get(h_id)) or None if h_id else None,
            )
        )
    return rows


def parse_simple(text: str) -> list[RosterRow]:
    """``netid,display_name,section`` with an optional header line."""
    reader = csv.reader(io.StringIO(text))
    rows: list[RosterRow] = []
    for i, r in enumerate(reader):
        if not r or not _norm(r[0]):
            continue
        if i == 0 and r[0].strip().lower() in ("netid", "net id"):
            continue
        rows.append(
            RosterRow(
                netid=_norm(r[0]).lower(),
                display_name=_norm(r[1]) or None if len(r) > 1 else None,
                section=_norm(r[2]) or None if len(r) > 2 else None,
            )
        )
    return rows


PARSERS = {"canvas_csv": parse_canvas_csv, "banner": parse_banner, "simple": parse_simple}


def preview(db: Session, offering: Offering, rows: list[RosterRow]) -> dict:
    """Diff parsed rows against active student enrollments."""
    current = {
        e.user.netid: e
        for e in db.scalars(
            select(Enrollment).where(
                Enrollment.offering_id == offering.id, Enrollment.role == Role.student
            )
        )
    }
    seen: set[str] = set()
    adds, moves, unmatched = [], [], []
    for r in rows:
        if not r.netid:
            unmatched.append(asdict(r))
            continue
        seen.add(r.netid)
        e = current.get(r.netid)
        if e is None or e.status == EnrollmentStatus.dropped:
            adds.append(asdict(r))
        else:
            cur_section = e.section.name if e.section else None
            if (r.section or None) != cur_section:
                moves.append({**asdict(r), "from_section": cur_section})
    drops = [
        {
            "netid": n,
            "display_name": e.user.display_name,
            "section": e.section.name if e.section else None,
        }
        for n, e in current.items()
        if e.status == EnrollmentStatus.active and n not in seen
    ]
    return {"adds": adds, "drops": drops, "moves": moves, "unmatched": unmatched}


def section_for(db: Session, offering: Offering, name: str | None) -> Section | None:
    """Resolve a section by name, creating it on first use. ``None`` for no section."""
    return _section(db, offering, name)


def _section(db: Session, offering: Offering, name: str | None) -> Section | None:
    if not name:
        return None
    sec = db.scalar(select(Section).where(Section.offering_id == offering.id, Section.name == name))
    if sec is None:
        sec = Section(offering_id=offering.id, name=name)
        db.add(sec)
        db.flush()
    return sec


def _user(db: Session, netid: str, display_name: str | None) -> User:
    u = db.scalar(select(User).where(User.netid == netid))
    if u is None:
        u = User(netid=netid, display_name=display_name)
        db.add(u)
        db.flush()
    elif display_name and not u.display_name:
        u.display_name = display_name
    return u


def apply(db: Session, offering: Offering, plan: dict) -> dict:
    counts = {"added": 0, "dropped": 0, "moved": 0}
    for r in plan.get("adds", []):
        u = _user(db, r["netid"].lower(), r.get("display_name"))
        e = db.scalar(
            select(Enrollment).where(
                Enrollment.offering_id == offering.id, Enrollment.user_id == u.id
            )
        )
        sec = _section(db, offering, r.get("section"))
        if e is None:
            db.add(
                Enrollment(
                    offering_id=offering.id, user_id=u.id, section_id=sec.id if sec else None
                )
            )
        else:
            e.status = EnrollmentStatus.active
            e.section_id = sec.id if sec else None
            e.updated_at = utcnow()
        counts["added"] += 1
    for r in plan.get("drops", []):
        e = _enrollment_by_netid(db, offering.id, r["netid"])
        if e is not None and e.role == Role.student:
            e.status = EnrollmentStatus.dropped
            e.updated_at = utcnow()
            counts["dropped"] += 1
    for r in plan.get("moves", []):
        e = _enrollment_by_netid(db, offering.id, r["netid"])
        if e is not None:
            sec = _section(db, offering, r.get("section"))
            e.section_id = sec.id if sec else None
            e.updated_at = utcnow()
            counts["moved"] += 1
    db.flush()
    return counts


def _enrollment_by_netid(db: Session, offering_id: uuid.UUID, netid: str) -> Enrollment | None:
    return db.scalar(
        select(Enrollment)
        .join(User)
        .where(Enrollment.offering_id == offering_id, User.netid == netid.lower())
    )
