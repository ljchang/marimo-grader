from grader.auth.tokens import verify_notebook_token
from grader.cli import main


def test_token_command_creates_user_and_enrollment(seed, capsys):
    main(
        [
            "token",
            "newprof",
            "--offering",
            "neuroimaging/2026-fall",
            "--role",
            "instructor",
            "--admin",
        ]
    )
    out = capsys.readouterr().out.strip()
    claims = verify_notebook_token(out)
    assert claims["sub"] == "newprof"
    from sqlalchemy import select

    from grader import db as dbmod
    from grader.models import Enrollment, Role, User

    with dbmod.get_sessionmaker()() as db:
        u = db.scalar(select(User).where(User.netid == "newprof"))
        assert u is not None and u.platform_admin
        e = db.scalar(select(Enrollment).where(Enrollment.user_id == u.id))
        assert e is not None and e.role == Role.instructor


def test_login_link_signs_in_once(client, seed, capsys):
    main(["login-link", "prof"])
    url = capsys.readouterr().out.strip()
    assert "/api/v1/auth/exchange?code=" in url
    path = url.split("http://testserver", 1)[1]
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 303 and "grader_session" in r.headers.get("set-cookie", "")
    assert client.get("/api/v1/auth/me").json()["netid"] == "prof"
    client.cookies.clear()
    assert client.get(path, follow_redirects=False).status_code == 400  # single use


def test_question_titles_come_from_check_labels():
    from grader.cli import _questions

    src = '_marks = {"a-q01": 5, "a-q02": 5}\ng.check("a-q01: Build the boxcar", [(True, "x")])\n'
    qs = {q["qid"]: q for q in _questions(src, set(), {})}
    assert qs["a-q01"]["title"] == "Build the boxcar" and qs["a-q01"]["grading_mode"] == "auto"
    assert qs["a-q02"]["title"] == "a-q02" and qs["a-q02"]["grading_mode"] == "manual"
