"""Notebook access tokens: short-lived EdDSA JWTs minted after the device handshake.

Claims: ``sub`` (NetID), ``scope`` ("notebook"), ``iat``, ``exp``, ``jti``.
Only the server holds the private key. Revocation is by ``jti`` in
``revoked_tokens`` (checked on every request; rows expire with the token).
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from grader.config import get_settings

ALGORITHM = "EdDSA"
SCOPE_NOTEBOOK = "notebook"


class TokenError(Exception):
    pass


@lru_cache
def _private_key() -> Ed25519PrivateKey:
    pem = get_settings().jwt_private_key_pem
    if pem:
        key = serialization.load_pem_private_key(pem.encode(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise TokenError("GRADER_JWT_PRIVATE_KEY_PEM must be an Ed25519 key")
        return key
    s = get_settings()
    if s.env == "prod":  # pragma: no cover - config validator catches this
        raise TokenError("No JWT key configured")
    if s.env == "test":
        return Ed25519PrivateKey.generate()  # ephemeral per process
    # Dev: persist a generated key next to the artifacts so tokens survive reloads.
    from pathlib import Path

    path = Path(s.artifact_dir).parent / "dev-jwt-key.pem"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(generate_private_key_pem())
        path.chmod(0o600)
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    assert isinstance(key, Ed25519PrivateKey)
    return key


def generate_private_key_pem() -> str:
    """Helper for operators: ``python -c 'from grader.auth.tokens import *; print(generate_private_key_pem())'``."""
    key = Ed25519PrivateKey.generate()
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def _public_key_pem() -> bytes:
    return (
        _private_key()
        .public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )


def mint_notebook_token(netid: str) -> tuple[str, int, str]:
    """Return (token, expires_in_seconds, jti)."""
    ttl = get_settings().notebook_token_ttl_seconds
    now = datetime.now(UTC)
    jti = secrets.token_urlsafe(16)
    payload = {
        "sub": netid,
        "scope": SCOPE_NOTEBOOK,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
        "jti": jti,
    }
    token = jwt.encode(payload, _private_key(), algorithm=ALGORITHM)
    return token, ttl, jti


def verify_notebook_token(token: str) -> dict:
    try:
        claims = jwt.decode(token, _public_key_pem(), algorithms=[ALGORITHM])
    except jwt.PyJWTError as e:
        raise TokenError(f"invalid token: {e}") from e
    if claims.get("scope") != SCOPE_NOTEBOOK or not claims.get("sub"):
        raise TokenError("wrong scope")
    return claims
