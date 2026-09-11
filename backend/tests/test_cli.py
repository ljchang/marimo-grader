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
