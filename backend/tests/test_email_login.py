"""Self-service sign-in links: who gets one, who silently does not, and what
the response reveals (nothing)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from grader import config
from grader.api.auth import netid_from_address
from grader.auth import device
from grader.db import get_sessionmaker
from grader.models import DeviceCode, User
from grader.services import mail

ACCEPTED = 202


@pytest.fixture
def outbox(monkeypatch):
    """Turn the feature on with an in-memory transport and hand back the outbox."""
    monkeypatch.setenv("GRADER_EMAIL_LOGIN_ENABLED", "true")
    monkeypatch.setenv("GRADER_MAIL_TRANSPORT", "memory")
    monkeypatch.setenv("GRADER_MAIL_FROM", "grader@dartbrains.org")
    config.get_settings.cache_clear()
    mail.reset_mailer()
    box = mail.mailer()
    yield box.outbox
    config.get_settings.cache_clear()
    mail.reset_mailer()


def post(client, email, **kw):
    return client.post("/api/v1/auth/email-login", json={"email": email, **kw})


# --- address parsing --------------------------------------------------------


@pytest.mark.parametrize(
    "address,expected",
    [
        ("F00abc1@Dartmouth.edu", "f00abc1"),
        ("  f00abc1@dartmouth.edu  ", "f00abc1"),
        ("f00abc1@gmail.com", None),
        ("f00abc1@evil.dartmouth.edu", None),
        ("f00abc1@dartmouth.edu.attacker.test", None),
        ("not-an-address", None),
        ("two@parts@dartmouth.edu", None),
        ("", None),
        ("a b@dartmouth.edu", None),
    ],
)
def test_netid_from_address(address, expected):
    assert netid_from_address(address, "dartmouth.edu") == expected


# --- the endpoint -----------------------------------------------------------


def test_disabled_by_default(client, seed):
    assert post(client, "f00abc1@dartmouth.edu").status_code == 404


def test_enrolled_student_gets_a_link(client, seed, outbox):
    r = post(client, "f00abc1@dartmouth.edu")
    assert r.status_code == ACCEPTED and r.json()["ok"]
    assert len(outbox) == 1
    msg = outbox[0]
    assert msg.to == "f00abc1@dartmouth.edu"
    assert "/api/v1/auth/exchange?code=" in msg.text
    assert "Alice Student" in msg.text


def test_link_signs_the_browser_in(client, seed, outbox):
    post(client, "f00abc1@dartmouth.edu")
    link = [w for w in outbox[0].text.split() if "exchange?code=" in w][0]
    r = client.get(link.replace("http://testserver", ""), follow_redirects=False)
    assert r.status_code == 303
    assert client.get("/api/v1/auth/me").json()["netid"] == "f00abc1"


def test_link_is_single_use(client, seed, outbox):
    post(client, "f00abc1@dartmouth.edu")
    link = [w for w in outbox[0].text.split() if "exchange?code=" in w][0]
    path = link.replace("http://testserver", "")
    assert client.get(path, follow_redirects=False).status_code == 303
    client.post("/api/v1/auth/logout")
    assert client.get(path, follow_redirects=False).status_code == 400


def test_unknown_and_unenrolled_look_identical(client, seed, outbox):
    """No response, timing aside, distinguishes these three cases."""
    with get_sessionmaker()() as db:
        db.add(User(netid="stranger"))  # exists, but enrolled in nothing
        db.commit()

    bodies = [
        post(client, "f00abc1@dartmouth.edu").json(),  # enrolled
        post(client, "nobody-here@dartmouth.edu").json(),  # no such user
        post(client, "stranger@dartmouth.edu").json(),  # user, no enrollment
        post(client, "f00abc1@gmail.com").json(),  # wrong domain
    ]
    assert len({str(b) for b in bodies}) == 1
    assert len(outbox) == 1  # only the enrolled one was mailed


def test_never_creates_a_user(client, seed, outbox):
    post(client, "brand-new-person@dartmouth.edu")
    with get_sessionmaker()() as db:
        assert db.scalar(select(User).where(User.netid == "brand-new-person")) is None
    assert outbox == []


# --- rate limiting ----------------------------------------------------------


def test_second_request_is_throttled(client, seed, outbox):
    assert post(client, "f00abc1@dartmouth.edu").status_code == ACCEPTED
    assert post(client, "f00abc1@dartmouth.edu").status_code == ACCEPTED
    assert len(outbox) == 1  # the minimum interval swallowed the second


def test_daily_cap(client, seed, outbox, monkeypatch):
    monkeypatch.setenv("GRADER_EMAIL_LOGIN_MIN_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("GRADER_EMAIL_LOGIN_MAX_PER_DAY", "3")
    config.get_settings.cache_clear()
    for _ in range(5):
        post(client, "f00abc1@dartmouth.edu")
    assert len(outbox) == 3


# --- delivery failure -------------------------------------------------------


def test_failed_delivery_does_not_burn_the_allowance(client, seed, outbox, monkeypatch):
    def boom(_msg):
        raise mail.MailError("relay refused")

    monkeypatch.setattr(mail.mailer(), "send", boom)
    assert post(client, "f00abc1@dartmouth.edu").status_code == ACCEPTED
    with get_sessionmaker()() as db:
        codes = db.scalars(
            select(DeviceCode).where(DeviceCode.client == device.EMAIL_LOGIN_CLIENT)
        ).all()
        assert codes == []


# --- operator links still work ---------------------------------------------


def test_operator_and_email_codes_are_both_accepted(client, seed):
    with get_sessionmaker()() as db:
        user = db.scalar(select(User).where(User.netid == "f00abc1"))
        code = device.mint_login_code(db, user)
        db.commit()
    r = client.get(f"/api/v1/auth/exchange?code={code}", follow_redirects=False)
    assert r.status_code == 303


def test_unknown_client_is_refused():
    with get_sessionmaker()() as db:
        db.add(User(netid="x"))
        db.commit()
        user = db.scalar(select(User).where(User.netid == "x"))
        with pytest.raises(ValueError):
            device.mint_login_code(db, user, client="something-else")
