"""Device-authorization handshake for notebooks (RFC 8628 shape).

1. Widget: POST /auth/device -> device_code (secret, returned once), user_code (short,
   shown to the human), verification_url.
2. Human: opens verification_url in a browser tab, signs in through SAML, and the
   server binds the user_code to their NetID.
3. Widget: polls POST /auth/device/token with the device_code until approved, then
   receives a notebook JWT. The device_code is single-use.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from grader.auth.tokens import mint_notebook_token
from grader.config import get_settings
from grader.models import DeviceCode, User, utcnow

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


def _user_code() -> str:
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def start(db: Session, client: str | None) -> dict:
    s = get_settings()
    device_code = secrets.token_urlsafe(32)
    for _ in range(5):
        user_code = _user_code()
        if not db.scalar(select(DeviceCode).where(DeviceCode.user_code == user_code)):
            break
    row = DeviceCode(
        device_code_hash=_hash(device_code),
        user_code=user_code,
        client=(client or "")[:120] or None,
        expires_at=datetime.now(UTC) + timedelta(seconds=s.device_code_ttl_seconds),
    )
    db.add(row)
    db.flush()
    return {
        "device_code": device_code,
        "user_code": user_code,
        "verification_url": f"{s.base_url}/api/v1/auth/device/verify?code={user_code}",
        "expires_in": s.device_code_ttl_seconds,
        "interval": s.device_poll_interval_seconds,
    }


def approve(db: Session, user_code: str, user: User) -> DeviceCode | None:
    code = user_code.strip().upper()
    if "-" not in code and len(code) == 8:
        code = f"{code[:4]}-{code[4:]}"
    row = db.scalar(select(DeviceCode).where(DeviceCode.user_code == code))
    if row is None or row.approved_at is not None or _aware(row.expires_at) < datetime.now(UTC):
        return None
    row.user_id = user.id
    row.approved_at = utcnow()
    db.flush()
    return row


def poll(db: Session, device_code: str) -> dict:
    row = db.scalar(select(DeviceCode).where(DeviceCode.device_code_hash == _hash(device_code)))
    if row is None or row.consumed_at is not None or row.client == "operator-login-link":
        return {"status": "expired"}  # login-link codes are for /auth/exchange only
    if _aware(row.expires_at) < datetime.now(UTC):
        return {"status": "expired"}
    if row.approved_at is None or row.user_id is None:
        return {"status": "pending"}
    user = db.get(User, row.user_id)
    assert user is not None
    token, ttl, _jti = mint_notebook_token(user.netid)
    row.consumed_at = utcnow()
    db.flush()
    return {
        "status": "approved",
        "access_token": token,
        "token_type": "bearer",
        "expires_in": ttl,
        "netid": user.netid,
    }


LOGIN_LINK_TTL = 1800


def mint_login_code(db: Session, user: User) -> str:
    """Operator-only: a pre-approved, single-use code that ``/auth/exchange`` turns into a session."""
    code = secrets.token_urlsafe(32)
    db.add(
        DeviceCode(
            device_code_hash=_hash(code),
            user_code="LOGIN-" + secrets.token_hex(4).upper(),
            client="operator-login-link",
            user_id=user.id,
            approved_at=utcnow(),
            expires_at=datetime.now(UTC) + timedelta(seconds=LOGIN_LINK_TTL),
        )
    )
    db.flush()
    return code


def consume_login_code(db: Session, code: str) -> User | None:
    row = db.scalar(select(DeviceCode).where(DeviceCode.device_code_hash == _hash(code)))
    if (
        row is None
        or row.client != "operator-login-link"
        or row.consumed_at is not None
        or row.user_id is None
        or _aware(row.expires_at) < datetime.now(UTC)
    ):
        return None
    row.consumed_at = utcnow()
    user = db.get(User, row.user_id)
    db.flush()
    return user
