"""``grader`` command line: publish assignments and seed a dev database.

    grader publish glm.py --server https://grader.dartbrains.org \
        --offering <uuid> --slug glm --title "GLM" [--student glm_student.py]

The instructor signs in through the same device handshake the notebook uses.
When ``mograder`` is installed the student version is generated from the
instructor notebook (solutions stripped, hidden tests removed, cell hashes
injected). Otherwise pass ``--student`` with a pre-generated file.

Questions come from MoGrader's marks cell (``_marks = {"glm-q01": 5, ...}``);
by default a question is ``auto`` if a ``check("<qid>: ...")`` call exists for
it in the instructor notebook and ``manual`` otherwise. Override with
``--manual qid`` / ``--hybrid qid=auto_points``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import webbrowser
from pathlib import Path

import httpx

CHECK_RE = re.compile(r"""check\(\s*[rf]?["']([^"':]+)\s*:""")
MARKS_RE = re.compile(r"_marks\s*=\s*(\{[^}]*\})", re.S)


def _device_login(client: httpx.Client, server: str) -> str:
    r = client.post(f"{server}/api/v1/auth/device", json={"client": "grader-cli"})
    r.raise_for_status()
    d = r.json()
    print(f"Sign in at: {d['verification_url']}\n(code {d['user_code']})")
    webbrowser.open(d["verification_url"])
    while True:
        time.sleep(d["interval"])
        t = client.post(
            f"{server}/api/v1/auth/device/token", json={"device_code": d["device_code"]}
        ).json()
        if t["status"] == "approved":
            print(f"Signed in as {t['netid']}")
            return t["access_token"]
        if t["status"] == "expired":
            sys.exit("Sign-in code expired; try again.")


def _generate_student(source: Path) -> str:
    try:
        from mograder.grading import cells
    except ImportError:
        sys.exit(
            "mograder is not installed; pass --student with a generated notebook, or `uv pip install mograder`."
        )
    lines = source.read_text().splitlines(keepends=True)
    errors = cells.validate_markers(lines, str(source))
    if errors:
        sys.exit("\n".join(f"ERROR: {e}" for e in errors))
    out = cells.strip_solutions(lines)
    out = cells.strip_hidden_tests(out)
    out = cells.convert_markdown_cells(out)
    text = "".join(out)
    if hasattr(cells, "_inject_cell_hashes"):
        text = cells._inject_cell_hashes(text)
    return text


def _inject_metadata(student_text: str, **kv: str) -> str:
    """Add ``# grader-<key> = "<value>"`` lines inside the PEP 723 block (create one if absent)."""
    lines = [f'# grader-{k.replace("_", "-")} = "{v}"' for k, v in kv.items() if v]
    if "# /// script" in student_text:
        return student_text.replace("# ///\n", "\n".join(lines) + "\n# ///\n", 1)
    block = "# /// script\n" + "\n".join(lines) + "\n# ///\n"
    return block + student_text


def _questions(source_text: str, manual: set[str], hybrid: dict[str, float]) -> list[dict]:
    m = MARKS_RE.search(source_text)
    if not m:
        sys.exit("No `_marks = {...}` cell found in the instructor notebook.")
    import ast

    marks = ast.literal_eval(m.group(1))
    keys_with_checks = {k.strip() for k in CHECK_RE.findall(source_text)}
    qs = []
    for qid, pts in marks.items():
        if qid in hybrid:
            mode, auto_max = "hybrid", hybrid[qid]
        elif qid in manual or qid not in keys_with_checks:
            mode, auto_max = "manual", 0.0
        else:
            mode, auto_max = "auto", float(pts)
        qs.append(
            {
                "qid": qid,
                "title": qid,
                "max_points": float(pts),
                "auto_points_max": auto_max,
                "grading_mode": mode,
                "check_keys": [qid] if mode != "manual" else [],
            }
        )
    return qs


def cmd_publish(a: argparse.Namespace) -> None:
    server = a.server.rstrip("/")
    source = Path(a.notebook)
    source_text = source.read_text()
    student_text = Path(a.student).read_text() if a.student else _generate_student(source)
    hybrid = dict((kv.split("=")[0], float(kv.split("=")[1])) for kv in a.hybrid)
    questions = _questions(source_text, set(a.manual), hybrid)

    with httpx.Client(timeout=60) as client:
        token = a.token or _device_login(client, server)
        h = {"Authorization": f"Bearer {token}"}
        # Find or create the assignment.
        r = client.get(f"{server}/api/v1/offerings/{a.offering}/assignments", headers=h)
        r.raise_for_status()
        existing = next((x for x in r.json() if x["slug"] == a.slug), None)
        if existing is None:
            r = client.post(
                f"{server}/api/v1/offerings/{a.offering}/assignments",
                headers=h,
                json={"slug": a.slug, "title": a.title or a.slug},
            )
            r.raise_for_status()
            existing = r.json()
        assignment_id = existing["id"]
        # The version id is not known until publish; embed the ids we do know, then
        # re-publish the student text with the version id (two-step so the file is self-describing).
        pre = _inject_metadata(
            student_text, server=server, offering_id=a.offering, assignment_id=assignment_id
        )
        cell_hashes = {"sha256": hashlib.sha256(pre.encode()).hexdigest()}
        r = client.post(
            f"{server}/api/v1/offerings/{a.offering}/assignments/{assignment_id}/versions",
            headers=h,
            files={
                "instructor_notebook": (source.name, source_text.encode(), "text/x-python"),
                "student_notebook": (source.name, pre.encode(), "text/x-python"),
            },
            data={"questions": json.dumps(questions), "cell_hashes": json.dumps(cell_hashes)},
        )
        if r.status_code >= 400:
            sys.exit(f"publish failed: {r.status_code} {r.text}")
        v = r.json()
        final = _inject_metadata(
            student_text,
            server=server,
            offering_id=a.offering,
            assignment_id=assignment_id,
            assignment_version=v["id"],
        )
        out = Path(a.out or f"{source.stem}_student.py")
        out.write_text(final)
        print(f"Published {a.slug} v{v['version']} ({len(questions)} questions)")
        print(
            f"Student notebook written to {out} — distribute this file (it embeds the version id)."
        )
        print(f"Also served at {server}{v['student_url']}")


def cmd_seed(a: argparse.Namespace) -> None:
    """Create a course/offering with an instructor and students in the dev database."""
    from sqlalchemy import select

    from grader.db import get_engine, get_sessionmaker
    from grader.models import Base, Course, Enrollment, Offering, Role, User

    Base.metadata.create_all(get_engine())
    with get_sessionmaker()() as db:
        course = db.scalar(select(Course).where(Course.slug == a.course)) or Course(
            slug=a.course, title=a.title or a.course
        )
        db.add(course)
        db.flush()
        off = db.scalar(
            select(Offering).where(Offering.course_id == course.id, Offering.term == a.term)
        )
        if off is None:
            off = Offering(course_id=course.id, term=a.term, title=f"{course.title} ({a.term})")
            db.add(off)
            db.flush()

        def user(netid: str, admin: bool = False) -> User:
            u = db.scalar(select(User).where(User.netid == netid)) or User(netid=netid)
            u.platform_admin = u.platform_admin or admin
            db.add(u)
            db.flush()
            return u

        def enroll(u: User, role: Role) -> None:
            e = db.scalar(
                select(Enrollment).where(
                    Enrollment.offering_id == off.id, Enrollment.user_id == u.id
                )
            )
            if e is None:
                db.add(Enrollment(offering_id=off.id, user_id=u.id, role=role))

        enroll(user(a.instructor, admin=True), Role.instructor)
        for s in a.students:
            enroll(user(s), Role.student)
        db.commit()
        print(f"offering_id={off.id}")
        print(f"instructor={a.instructor} (also platform admin); students={', '.join(a.students)}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="grader")
    sub = p.add_subparsers(dest="cmd", required=True)
    pub = sub.add_parser("publish", help="publish an assignment version")
    pub.add_argument("notebook")
    pub.add_argument("--server", required=True)
    pub.add_argument("--offering", required=True, help="offering id")
    pub.add_argument("--slug", required=True)
    pub.add_argument("--title")
    pub.add_argument("--student", help="pre-generated student notebook (skip mograder generation)")
    pub.add_argument("--manual", action="append", default=[], help="qid to grade manually")
    pub.add_argument("--hybrid", action="append", default=[], help="qid=auto_points")
    pub.add_argument("--token", help="notebook token (skip interactive sign-in)")
    pub.add_argument("--out")
    pub.set_defaults(fn=cmd_publish)
    seed = sub.add_parser(
        "seed", help="seed a dev database with a course, offering, instructor, students"
    )
    seed.add_argument("--course", default="neuroimaging")
    seed.add_argument("--title", default="Introduction to Neuroimaging Analysis")
    seed.add_argument("--term", default="2026-fall")
    seed.add_argument("--instructor", default="prof")
    seed.add_argument("--students", nargs="*", default=["f00abc1", "f00xyz9"])
    seed.set_defaults(fn=cmd_seed)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
