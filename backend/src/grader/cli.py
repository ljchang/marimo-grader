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
import json
import re
import sys
import time
import webbrowser
from pathlib import Path

import httpx

CHECK_RE = re.compile(r"""check\(\s*[rf]?["']([^"':]+)\s*:\s*([^"']*)["']""")
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


def _questions(source_text: str, manual: set[str], hybrid: dict[str, float]) -> list[dict]:
    m = MARKS_RE.search(source_text)
    if not m:
        sys.exit("No `_marks = {...}` cell found in the instructor notebook.")
    import ast

    marks = ast.literal_eval(m.group(1))
    titles = {k.strip(): t.strip() for k, t in CHECK_RE.findall(source_text)}
    keys_with_checks = set(titles)
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
                "title": titles.get(qid) or qid,
                "max_points": float(pts),
                "auto_points_max": auto_max,
                "grading_mode": mode,
                "check_keys": [qid] if mode != "manual" else [],
            }
        )
    return qs


def _resolve_offering(
    client: httpx.Client, server: str, offering: str, h: dict
) -> tuple[str, str, str]:
    """Accept an offering uuid or a ``course/term`` alias; return (offering_id, course, term)."""
    if "/" in offering:
        course, term = offering.split("/", 1)
        r = client.get(f"{server}/a/{course}/{term}/assignments.json")
        if r.status_code != 200:
            sys.exit(f"offering {offering!r} not found on {server} ({r.status_code})")
        return r.json()["offering_id"], course, term
    r = client.get(f"{server}/api/v1/offerings/{offering}", headers=h)
    if r.status_code != 200:
        sys.exit(f"offering {offering!r} not found or not a member ({r.status_code})")
    j = r.json()
    return offering, j["course_slug"], j["term"]


def cmd_publish(a: argparse.Namespace) -> None:
    from grader.services.notebook_meta import leaked_markers

    server = a.server.rstrip("/")
    source = Path(a.notebook)
    source_text = source.read_text()
    student_text = Path(a.student).read_text() if a.student else _generate_student(source)
    leaked = leaked_markers(student_text)
    if leaked:
        sys.exit(f"refusing to publish: student notebook still contains {', '.join(leaked)}")
    hybrid = dict((kv.split("=")[0], float(kv.split("=")[1])) for kv in a.hybrid)
    questions = _questions(source_text, set(a.manual), hybrid)

    with httpx.Client(timeout=60) as client:
        token = a.token or _device_login(client, server)
        h = {"Authorization": f"Bearer {token}"}
        offering_id, course, term = _resolve_offering(client, server, a.offering, h)
        r = client.get(f"{server}/api/v1/offerings/{offering_id}/assignments", headers=h)
        r.raise_for_status()
        existing = next((x for x in r.json() if x["slug"] == a.slug), None)
        if existing is None:
            r = client.post(
                f"{server}/api/v1/offerings/{offering_id}/assignments",
                headers=h,
                json={"slug": a.slug, "title": a.title or a.slug},
            )
            r.raise_for_status()
            existing = r.json()
        assignment_id = existing["id"]
        # The server finalizes the student notebook (injects ids + version) and stores
        # exactly the bytes it will serve; we download those rather than writing our own.
        r = client.post(
            f"{server}/api/v1/offerings/{offering_id}/assignments/{assignment_id}/versions",
            headers=h,
            files={
                "instructor_notebook": (source.name, source_text.encode(), "text/x-python"),
                "student_notebook": (source.name, student_text.encode(), "text/x-python"),
            },
            data={"questions": json.dumps(questions), "cell_hashes": "{}"},
        )
        if r.status_code >= 400:
            sys.exit(f"publish failed: {r.status_code} {r.text}")
        v = r.json()
        if v.get("unchanged"):
            print(f"{a.slug} v{v['version']} unchanged (same instructor notebook and questions)")
        else:
            print(f"Published {a.slug} v{v['version']} ({len(questions)} questions)")
        dl = client.get(v["download_url"], headers=h)
        dl.raise_for_status()
        out = Path(a.out or f"{source.stem}_student.py")
        out.write_bytes(dl.content)
        print(f"Student notebook written to {out}")
        print(
            f"Served at {v['student_url']}  (MoLab: {v.get('molab_url', v['student_url'].replace('/student.py', '/molab'))})"
        )


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


def cmd_token(a: argparse.Namespace) -> None:
    """Mint a notebook/CLI token for a NetID directly from the server's signing key.

    Operator use only (run inside the web container). Lets an instructor publish
    while sign-in is disabled, e.g. before SAML approval. The user must exist or
    is created; an enrollment is added when --offering is given.
    """
    from sqlalchemy import select

    from grader.auth.tokens import mint_notebook_token
    from grader.db import get_sessionmaker
    from grader.models import Course, Enrollment, Offering, Role, User

    netid = a.netid.strip().lower()
    with get_sessionmaker()() as db:
        user = db.scalar(select(User).where(User.netid == netid))
        if user is None:
            user = User(netid=netid, display_name=a.display_name)
            db.add(user)
            db.flush()
        if a.admin:
            user.platform_admin = True
        if a.offering:
            course_slug, term = a.offering.split("/", 1)
            off = db.scalar(
                select(Offering)
                .join(Course)
                .where(Course.slug == course_slug, Offering.term == term)
            )
            if off is None:
                sys.exit(f"offering {a.offering!r} not found; run `grader seed` first")
            e = db.scalar(
                select(Enrollment).where(
                    Enrollment.offering_id == off.id, Enrollment.user_id == user.id
                )
            )
            if e is None:
                db.add(Enrollment(offering_id=off.id, user_id=user.id, role=Role(a.role)))
            else:
                e.role = Role(a.role)
        db.commit()
    token, ttl, _ = mint_notebook_token(netid)
    print(token)
    print(f"# token for {netid}, valid {ttl // 3600} h", file=sys.stderr)


def cmd_login_link(a: argparse.Namespace) -> None:
    """Print a one-time browser sign-in URL for a NetID (operator use, any auth mode)."""
    from sqlalchemy import select

    from grader.auth.device import LOGIN_LINK_TTL, mint_login_code
    from grader.config import get_settings
    from grader.db import get_sessionmaker
    from grader.models import User

    netid = a.netid.strip().lower()
    with get_sessionmaker()() as db:
        user = db.scalar(select(User).where(User.netid == netid))
        if user is None:
            sys.exit(f"no user {netid!r}; run `grader token {netid} --offering ...` first")
        code = mint_login_code(db, user)
        db.commit()
    base = get_settings().base_url
    print(f"{base}/api/v1/auth/exchange?code={code}")
    print(f"# one-time sign-in link for {netid}, valid {LOGIN_LINK_TTL // 60} min", file=sys.stderr)


def cmd_warm_cache(a: argparse.Namespace) -> None:
    """Warm the worker's HuggingFace cache; see grader.warm_cache for why it is needed."""
    from grader.warm_cache import warm

    raise SystemExit(warm(a))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="grader")
    sub = p.add_subparsers(dest="cmd", required=True)
    pub = sub.add_parser("publish", help="publish an assignment version")
    pub.add_argument("notebook")
    pub.add_argument("--server", required=True)
    pub.add_argument(
        "--offering",
        required=True,
        help="offering id or course/term alias, e.g. neuroimaging/2026-fall",
    )
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
    tok = sub.add_parser(
        "token", help="mint a token for a NetID (operator use; works while sign-in is disabled)"
    )
    tok.add_argument("netid")
    tok.add_argument("--offering", help="course/term alias to enroll the user in")
    tok.add_argument("--role", default="instructor", choices=["student", "ta", "instructor"])
    tok.add_argument("--admin", action="store_true", help="also make the user a platform admin")
    tok.add_argument("--display-name")
    tok.set_defaults(fn=cmd_token)
    warm = sub.add_parser(
        "warm-cache",
        help="pre-download the datasets published assignments need (the sandbox has no network)",
    )
    warm.add_argument("--check", action="store_true", help="report gaps without downloading")
    warm.add_argument("--slug", help="warm only this assignment")
    warm.set_defaults(fn=cmd_warm_cache)
    ll = sub.add_parser(
        "login-link", help="print a one-time browser sign-in link for a NetID (operator use)"
    )
    ll.add_argument("netid")
    ll.set_defaults(fn=cmd_login_link)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
