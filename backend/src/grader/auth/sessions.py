"""Web sessions for the Svelte UI.

The cookie carries only an opaque, signed session id. Everything else lives
in ``web_sessions`` so a session can be revoked server-side. A per-session
CSRF token must be echoed in ``X-CSRF-Token`` on mutating requests.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Request, Response
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy.orm import Session

from grader.config import get_settings
from grader.models import User, WebSession, utcnow


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().session_secret, salt="grader-session")


def create_session(
    db: Session,
    user: User,
    *,
    saml_name_id: str | None = None,
    saml_session_index: str | None = None,
) -> WebSession:
    s = get_settings()
    sess = WebSession(
        id=secrets.token_urlsafe(32),
        user_id=user.id,
        csrf_token=secrets.token_urlsafe(24),
        expires_at=datetime.now(UTC) + timedelta(seconds=s.session_ttl_seconds),
        saml_name_id=saml_name_id,
        saml_session_index=saml_session_index,
    )
    db.add(sess)
    user.last_login_at = utcnow()
    db.flush()
    return sess


def set_session_cookie(response: Response, sess: WebSession) -> None:
    s = get_settings()
    response.set_cookie(
        s.session_cookie,
        _serializer().dumps(sess.id),
        max_age=s.session_ttl_seconds,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(get_settings().session_cookie, path="/")


def load_session(db: Session, request: Request) -> WebSession | None:
    raw = request.cookies.get(get_settings().session_cookie)
    if not raw:
        return None
    try:
        sid = _serializer().loads(raw)
    except BadSignature:
        return None
    sess = db.get(WebSession, sid)
    if sess is None:
        return None
    expires = sess.expires_at if sess.expires_at.tzinfo else sess.expires_at.replace(tzinfo=UTC)
    if expires < datetime.now(UTC):
        db.delete(sess)
        return None
    return sess


def destroy_session(db: Session, sess: WebSession) -> None:
    db.delete(sess)
