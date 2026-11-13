"""CORS for the notebook widget.

MoLab runs a forked notebook inside a nested iframe served from a per-session
subdomain of molab.run (observed: sb-fb0578637b21faaa-session.sb.molab.run),
not from molab.marimo.io. The sandbox id changes every session, so the widget's
fetch is blocked unless the origin is matched by pattern.
"""

from __future__ import annotations

import re

import pytest

from grader.config import Settings

MOLAB_SANDBOX = "https://sb-fb0578637b21faaa-session.sb.molab.run"


@pytest.fixture
def rx():
    return Settings(env="test").cors_origin_regex


@pytest.mark.parametrize(
    "origin,allowed",
    [
        (MOLAB_SANDBOX, True),
        ("https://sb-0000000000000000-session.sb.molab.run", True),
        ("https://anything.molab.run", True),
        # Anchors: a lookalike registrable domain must not slip through.
        ("https://molab.run.attacker.test", False),
        ("https://notmolab.run", False),
        ("https://molab.run", False),  # bare apex is not a sandbox host
        ("http://sb-x.sb.molab.run", False),  # plaintext
        ("https://evil.test", False),
    ],
)
def test_origin_regex(rx, origin, allowed):
    assert bool(re.match(rx, origin)) is allowed


@pytest.mark.parametrize("env", ["test", "prod"])
@pytest.mark.parametrize(
    "origin,allowed",
    [
        ("http://localhost:2718", True),
        # marimo moves to the next free port when 2718 is taken.
        ("http://localhost:2720", True),
        ("http://127.0.0.1:2719", True),
        ("http://localhost", True),
        (MOLAB_SANDBOX, True),
        ("http://localhost.attacker.test", False),
        ("http://localhost:2718.attacker.test", False),
        ("https://evil.test", False),
    ],
)
def test_localhost_any_port_in_every_env(env, origin, allowed):
    """Students run notebooks locally against the production grader."""
    # Prod settings demand every secret, so switch env on a test instance.
    s = Settings(env="test")
    object.__setattr__(s, "env", env)
    assert bool(re.match(s.cors_regex, origin)) is allowed


def test_localhost_survives_custom_regex():
    """An operator-set GRADER_CORS_ORIGIN_REGEX must not drop localhost."""
    s = Settings(env="test", cors_origin_regex=r"^https://example\.test$")
    assert re.match(s.cors_regex, "http://localhost:2720")
    assert re.match(s.cors_regex, "https://example.test")


def test_widget_preflight_is_allowed(client):
    """The exact request the sign-in button makes before its POST."""
    r = client.options(
        "/api/v1/auth/device",
        headers={
            "Origin": MOLAB_SANDBOX,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == MOLAB_SANDBOX


def test_device_start_carries_cors_header(client):
    r = client.post("/api/v1/auth/device", json={}, headers={"Origin": MOLAB_SANDBOX})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == MOLAB_SANDBOX
    assert r.json()["user_code"]


def test_unrelated_origin_is_not_allowed(client):
    r = client.post("/api/v1/auth/device", json={}, headers={"Origin": "https://evil.test"})
    assert "access-control-allow-origin" not in r.headers
