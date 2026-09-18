"""Storage broker: who gets which prefixes, and nothing else."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from grader import config
from grader import db as dbmod
from grader.models import Assignment, Enrollment, Group, GroupMember, StorageGrant, User
from grader.services import storage
from tests.conftest import notebook_token

OFF = "neuroimaging-2026-fall"


@pytest.fixture
def storage_on(monkeypatch):
    monkeypatch.setenv("GRADER_STORAGE_ENABLED", "true")
    monkeypatch.setenv("GRADER_CF_ACCOUNT_ID", "acct")
    monkeypatch.setenv("GRADER_CF_API_TOKEN", "cf-token")
    monkeypatch.setenv("GRADER_R2_ENDPOINT", "https://acct.r2.cloudflarestorage.com")
    monkeypatch.setenv("GRADER_R2_PARENT_ACCESS_KEY_ID", "parent-ak")
    monkeypatch.setenv("GRADER_R2_PARENT_SECRET_ACCESS_KEY", "parent-sk")
    monkeypatch.setenv("GRADER_STORAGE_UID_SECRET", "uid-secret")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


@pytest.fixture
def fake_cf(monkeypatch):
    """Record every mint instead of calling Cloudflare."""
    calls: list[dict] = []

    def temp_credentials(self, *, prefixes, permission, ttl):
        calls.append({"prefixes": list(prefixes), "permission": permission, "ttl": ttl})
        return {
            "access_key_id": f"ak-{permission}",
            "secret_access_key": "sk",
            "session_token": "tok",
        }

    def presign(self, *, key, method, expires):
        return f"https://signed.example/{key}?method={method}&exp={expires}"

    monkeypatch.setattr(storage.CloudflareR2, "temp_credentials", temp_credentials)
    monkeypatch.setattr(storage.CloudflareR2, "presign", presign)
    return calls


def _auth(client, netid):
    return {"Authorization": f"Bearer {notebook_token(client, netid)}"}


def _session(tc, seed, netid, **body):
    r = tc.post(
        f"/api/v1/offerings/{seed.offering_id}/storage/session", json=body, headers=_auth(tc, netid)
    )
    assert r.status_code == 200, r.text
    return r.json()


def _mounts(payload):
    return {m["logical"]: m for m in payload["mounts"]}


# --------------------------------------------------------------------------


def test_disabled_is_404(client, seed):
    r = client.post(
        f"/api/v1/offerings/{seed.offering_id}/storage/session", headers=_auth(client, "f00abc1")
    )
    assert r.status_code == 404 and r.json()["error"]["code"] == "storage_disabled"


def test_student_gets_own_prefixes_and_nothing_else(client, seed, storage_on, fake_cf):
    p = _session(client, seed, "f00abc1", client="pytest")
    m = _mounts(p)

    assert m["/course"]["prefix"] == f"course/{OFF}/" and m["/course"]["mode"] == "r"
    assert m["/cache/shared"]["mode"] == "r"
    assert m["/private"]["mode"] == "rw" and m["/private"]["prefix"].startswith(f"users/{OFF}/")
    assert m["/cache/private"]["mode"] == "rw"
    # The seeded assignment has no release_at, so it is released.
    assert m["/assignments/glm"]["mode"] == "r"
    # Never anything that spans other students.
    assert "/students" not in m and "/groups" not in m
    for mt in p["mounts"]:
        assert not mt["prefix"].startswith(f"users/{OFF}/") or mt["logical"] == "/private"

    # The uid is opaque: not the NetID, and stable across sessions.
    uid = m["/private"]["prefix"].split("/")[2]
    assert uid != "f00abc1" and len(uid) == 16
    assert (
        _mounts(_session(client, seed, "f00abc1"))["/private"]["prefix"] == m["/private"]["prefix"]
    )
    # ...and different from the other student's.
    assert (
        _mounts(_session(client, seed, "f00xyz9"))["/private"]["prefix"] != m["/private"]["prefix"]
    )

    # Two credentials, each covering exactly its mounts' prefixes.
    ro, rw = fake_cf[0], fake_cf[1]
    assert ro["permission"] == "object-read-only" and rw["permission"] == "object-read-write"
    assert set(ro["prefixes"]) == {mt["prefix"] for mt in p["mounts"] if mt["cred"] == "ro"}
    assert set(rw["prefixes"]) == {mt["prefix"] for mt in p["mounts"] if mt["cred"] == "rw"}
    assert not set(ro["prefixes"]) & set(rw["prefixes"])
    assert p["credentials"]["ro"]["access_key_id"] == "ak-object-read-only"
    assert p["public"][0] == {
        "logical": "/data/localizer",
        "backend": "hf",
        "repo": "dartbrains/localizer",
    }
    assert p["expires_at"] > datetime.now(UTC).isoformat()


def test_release_gating(client, seed, storage_on, fake_cf):
    with dbmod.get_sessionmaker()() as db:
        a = db.scalar(select(Assignment).where(Assignment.id == seed.assignment_id))
        a.settings = {
            **a.settings,
            "release_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        }
        db.commit()
    assert "/assignments/glm" not in _mounts(_session(client, seed, "f00abc1"))
    # Staff see it regardless.
    assert "/assignments/glm" in _mounts(_session(client, seed, "ta1"))

    with dbmod.get_sessionmaker()() as db:
        a = db.scalar(select(Assignment).where(Assignment.id == seed.assignment_id))
        a.settings = {
            **a.settings,
            "release_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
            "close_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        }
        db.commit()
    assert "/assignments/glm" not in _mounts(_session(client, seed, "f00abc1")), "closed"


def test_staff_prefixes(client, seed, storage_on, fake_cf):
    inst = _mounts(_session(client, seed, "prof"))
    assert inst["/course"]["mode"] == "rw"
    assert inst["/cache/shared"]["mode"] == "rw"
    assert inst["/students"] == {
        "logical": "/students",
        "prefix": f"users/{OFF}/",
        "mode": "r",
        "cred": "ro",
    }
    assert inst["/groups"]["mode"] == "rw"

    ta = _mounts(_session(client, seed, "ta1"))
    assert ta["/course"]["mode"] == "r"
    assert ta["/students"]["mode"] == "r"  # unscoped TA
    assert "/groups" not in ta


def test_group_mount(client, seed, storage_on, fake_cf):
    with dbmod.get_sessionmaker()() as db:
        alice = db.scalar(select(User).where(User.netid == "f00abc1"))
        enr = db.scalar(select(Enrollment).where(Enrollment.user_id == alice.id))
        g = Group(offering_id=seed.offering_id, slug="group-07", name="Group 7")
        db.add(g)
        db.flush()
        db.add(GroupMember(group_id=g.id, enrollment_id=enr.id))
        db.commit()
    m = _mounts(_session(client, seed, "f00abc1"))
    assert m["/group"] == {
        "logical": "/group",
        "prefix": f"groups/{OFF}/group-07/",
        "mode": "rw",
        "cred": "rw",
    }
    assert "/group" not in _mounts(_session(client, seed, "f00xyz9"))


def test_non_member_404(client, seed, storage_on, fake_cf):
    with dbmod.get_sessionmaker()() as db:
        db.add(User(netid="f00none", display_name="Nobody"))
        db.commit()
    r = client.post(
        f"/api/v1/offerings/{seed.offering_id}/storage/session", headers=_auth(client, "f00none")
    )
    assert r.status_code == 404
    assert fake_cf == []


def test_grant_is_recorded(client, seed, storage_on, fake_cf):
    _session(client, seed, "f00abc1", client="molab")
    with dbmod.get_sessionmaker()() as db:
        g = db.scalar(select(StorageGrant))
        assert g.role == "student" and g.client == "molab" and g.ttl_seconds == 3600
        assert any(p.startswith(f"users/{OFF}/") for p in g.prefixes_rw)
        assert f"course/{OFF}/" in g.prefixes_ro


def test_me_has_no_credentials(client, seed, storage_on, fake_cf):
    r = client.get(
        f"/api/v1/offerings/{seed.offering_id}/storage/me", headers=_auth(client, "f00abc1")
    )
    assert r.status_code == 200
    assert "credentials" not in r.json() and "/private" in _mounts(r.json())
    assert fake_cf == []


@pytest.mark.parametrize(
    "path,method,status",
    [
        ("/course/sub-01/bold.nii.gz", "GET", 200),
        ("/private/results/model.pkl", "PUT", 200),
        ("/course/new.txt", "PUT", 403),  # read-only mount
        ("/students/f00xyz9/x", "GET", 403),  # not a student's mount
        ("/private/../course/x", "GET", 400),
        ("/private//x", "GET", 400),
        ("/nope/x", "GET", 403),
        ("relative/x", "GET", 400),
    ],
)
def test_presign_scope(client, seed, storage_on, fake_cf, path, method, status):
    r = client.post(
        f"/api/v1/offerings/{seed.offering_id}/storage/presign",
        json={"path": path, "method": method, "expires": 99999},
        headers=_auth(client, "f00abc1"),
    )
    assert r.status_code == status, r.text
    if status == 200:
        body = r.json()
        assert body["expires_in"] == 3600  # capped
        assert body["key"].startswith(("course/", f"users/{OFF}/"))
        assert body["key"] in body["url"]


def test_resolve_prefers_longest_mount():
    mounts = [
        storage.Mount("/course", "course/x/", "r"),
        storage.Mount("/assignments/glm", "assignments/x/glm/", "r"),
        storage.Mount("/assignments/glm-2", "assignments/x/glm-2/", "r"),
    ]
    assert storage.resolve(mounts, "/assignments/glm-2/a.txt")[1] == "assignments/x/glm-2/a.txt"
    assert storage.resolve(mounts, "/assignments/glm/a.txt")[1] == "assignments/x/glm/a.txt"
    with pytest.raises(storage.StorageError):
        storage.resolve(mounts, "/assignments/glmx/a.txt")  # not a child of /assignments/glm
