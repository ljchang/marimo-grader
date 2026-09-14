"""The name a person is called.

display_name comes from the IdP and _upsert_user overwrites it from the SAML
assertion on every login, so a name typed into it would vanish at the next
sign-in. preferred_name belongs to the person and login never touches it.
Everything that renders a name shows User.name -- preferred, else the IdP's.
"""

from __future__ import annotations

from sqlalchemy import select

from grader import db as dbmod
from grader.api.auth import _upsert_user
from grader.models import User
from tests.conftest import login


def _set(client, csrf, value):
    return client.patch(
        "/api/v1/auth/me", headers={"X-CSRF-Token": csrf}, json={"preferred_name": value}
    )


def test_set_and_clear(client, seed):
    csrf = login(client, "f00abc1")
    r = _set(client, csrf, "  Ali  ")
    assert r.status_code == 200, r.text
    assert r.json()["preferred_name"] == "Ali"
    assert client.get("/api/v1/auth/me").json()["display_name"] == "Ali"

    # Blank clears it and the IdP's name comes back.
    assert _set(client, csrf, "   ").json()["preferred_name"] is None
    assert client.get("/api/v1/auth/me").json()["display_name"] == "Alice Student"


def test_signing_in_again_does_not_clobber_it(client, seed):
    """The whole reason for a separate column."""
    csrf = login(client, "f00abc1")
    _set(client, csrf, "Ali")

    with dbmod.get_sessionmaker()() as db:
        # Exactly what the SAML ACS does on every login.
        _upsert_user(db, "f00abc1", "Alice Student")
        db.commit()
        u = db.scalar(select(User).where(User.netid == "f00abc1"))
        assert u.preferred_name == "Ali", "login must not touch the person's own name"
        assert u.display_name == "Alice Student", "but it does keep the IdP's fresh"
        assert u.name == "Ali"


def test_it_only_ever_edits_your_own_row(client, seed):
    """There is no netid parameter; this cannot be pointed at anyone else."""
    csrf = login(client, "f00abc1")
    _set(client, csrf, "Ali")
    with dbmod.get_sessionmaker()() as db:
        assert db.scalar(select(User).where(User.netid == "f00xyz9")).preferred_name is None


def test_staff_views_show_the_preferred_name(client, seed):
    csrf = login(client, "f00abc1")
    _set(client, csrf, "Ali")
    login(client, "prof")
    rows = client.get(f"/api/v1/offerings/{seed.offering_id}/roster").json()
    rows = rows if isinstance(rows, list) else rows.get("rows", [])
    got = {r["netid"]: r["display_name"] for r in rows}
    assert got["f00abc1"] == "Ali"
    assert got["f00xyz9"] == "Bob Student", "others are unaffected"


def test_anonymous_cannot_set_a_name(client, seed):
    assert client.patch("/api/v1/auth/me", json={"preferred_name": "x"}).status_code == 401


def test_too_long_is_refused(client, seed):
    csrf = login(client, "f00abc1")
    assert _set(client, csrf, "x" * 201).status_code == 422
