"""Authentication routes: SAML login/ACS/metadata, sessions, and the device handshake."""

from __future__ import annotations

import html
import logging
import re
from datetime import UTC, datetime
from urllib.parse import quote, urlencode, urlparse

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from grader.auth import device, saml
from grader.auth.deps import Principal, api_error, current_principal, optional_principal
from grader.auth.sessions import (
    clear_session_cookie,
    create_session,
    destroy_session,
    load_session,
    set_session_cookie,
)
from grader.config import get_settings
from grader.db import get_db
from grader.models import Enrollment, EnrollmentStatus, User, utcnow
from grader.services import audit, mail

router = APIRouter(prefix="/auth", tags=["auth"])

log = logging.getLogger("grader.auth")


def _safe_next(next_url: str | None) -> str:
    """Only allow same-site relative paths as post-login targets."""
    if not next_url or not next_url.startswith("/") or next_url.startswith("//"):
        return "/"
    return next_url


def _frontend(path: str) -> str:
    return get_settings().frontend_url.rstrip("/") + path


def _upsert_user(db: Session, netid: str, display_name: str | None) -> User:
    user = db.scalar(select(User).where(User.netid == netid))
    if user is None:
        user = User(netid=netid, display_name=display_name)
        db.add(user)
        db.flush()
    elif display_name and display_name != user.display_name:
        user.display_name = display_name
    user.last_login_at = utcnow()
    return user


# --- browser sessions -------------------------------------------------------


@router.get("/login")
async def login(request: Request, next: str | None = None):
    s = get_settings()
    target = _safe_next(next)
    if s.auth_mode == "disabled":
        return HTMLResponse(_VERIFY_PAGE.format(body=_DISABLED_BODY), status_code=503)
    if s.auth_mode == "dev":
        return RedirectResponse(f"{s.base_url}/api/v1/auth/dev-login?{urlencode({'next': target})}")
    url = await saml.login_url(request, relay_state=target)
    return RedirectResponse(url, status_code=302)


@router.post("/saml/acs")
async def saml_acs(request: Request, db: Session = Depends(get_db)):
    try:
        ident = await saml.process_response(request)
    except ValueError as e:
        raise api_error(401, "saml_failed", str(e)) from e
    user = _upsert_user(db, ident.netid, ident.display_name)
    sess = create_session(
        db, user, saml_name_id=ident.name_id, saml_session_index=ident.session_index
    )
    form = await request.form()
    target = _safe_next(str(form.get("RelayState") or "/"))
    resp = RedirectResponse(_frontend(target), status_code=303)
    set_session_cookie(resp, sess)
    return resp


@router.get("/saml/metadata")
def saml_metadata():
    try:
        xml = saml.metadata_xml()
    except Exception as e:  # noqa: BLE001
        raise api_error(500, "saml_metadata", str(e)) from e
    return Response(content=xml, media_type="application/samlmetadata+xml")


@router.get("/dev-login")
def dev_login(netid: str = "dev", next: str | None = None, db: Session = Depends(get_db)):
    s = get_settings()
    if s.auth_mode != "dev":
        raise api_error(404, "not_found", "not found")
    netid = netid.strip().lower()
    user = _upsert_user(db, netid, None)
    sess = create_session(db, user)
    resp = RedirectResponse(_frontend(_safe_next(next)), status_code=303)
    set_session_cookie(resp, sess)
    return resp


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    sess = load_session(db, request)
    if sess is not None:
        destroy_session(db, sess)
    resp = JSONResponse(
        {"ok": True, "redirect": s.saml_idp_logout_url if s.auth_mode == "saml" else _frontend("/")}
    )
    clear_session_cookie(resp)
    return resp


@router.get("/me")
def me(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    user = p.user
    enrollments = db.scalars(
        select(Enrollment).where(
            Enrollment.user_id == user.id, Enrollment.status == EnrollmentStatus.active
        )
    ).all()
    return {
        "netid": user.netid,
        "display_name": user.name,
        "platform_admin": user.platform_admin,
        "via": p.via,
        "enrollments": [
            {
                "offering_id": str(e.offering_id),
                "course_slug": e.offering.course.slug,
                "term": e.offering.term,
                "title": e.offering.title,
                "role": e.role.value,
            }
            for e in enrollments
        ],
    }


class ProfileIn(BaseModel):
    preferred_name: str | None = None


@router.patch("/me")
def update_me(
    body: ProfileIn, p: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    """Set the name you want to be called.

    Only ever edits the caller's own row -- there is no netid parameter, so this
    cannot be pointed at anyone else. It writes preferred_name and never
    display_name, which belongs to the IdP and is overwritten at every login;
    a name typed here would otherwise vanish the next time you signed in.

    Sending null or blank clears it and falls back to the IdP's name.
    """
    name = (body.preferred_name or "").strip()
    if len(name) > 200:
        raise api_error(422, "too_long", "preferred name must be 200 characters or fewer")
    p.user.preferred_name = name or None
    db.flush()
    return {"netid": p.user.netid, "preferred_name": p.user.preferred_name, "name": p.user.name}


@router.get("/csrf")
def csrf(p: Principal = Depends(current_principal)):
    if p.via != "session":
        raise api_error(400, "not_session", "CSRF tokens only apply to cookie sessions")
    return {"csrf_token": p.session_csrf}


# --- operator login link ---------------------------------------------------


@router.get("/exchange")
def exchange_login_code(code: str, next: str | None = None, db: Session = Depends(get_db)):
    """Sign in with a one-time code minted by ``grader login-link`` on the server.

    Works in every auth mode, including ``disabled``: the code can only be created by
    an operator with shell access, so this is the break-glass path when SSO is not yet
    (or no longer) available. Codes are single-use and expire in minutes.
    """
    user = device.consume_login_code(db, code)
    if user is None:
        return HTMLResponse(
            _VERIFY_PAGE.format(
                body="<h1 class='err'>That sign-in link is not valid</h1>"
                "<p>It may have expired or already been used. Ask the operator for a new one.</p>"
            ),
            status_code=400,
        )
    sess = create_session(db, user)
    resp = RedirectResponse(_frontend(_safe_next(next)), status_code=303)
    set_session_cookie(resp, sess)
    return resp


# --- email sign-in links ----------------------------------------------------

_ADDRESS_RE = re.compile(r"^[^@\s]+@[^@\s]+$")
_LOCAL_PART_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

# One answer for every outcome. Whether an address belongs to an enrolled
# student is roster information, and a different response for "sent" and "not
# found" would publish it to anyone with a form and a word list.
_ACCEPTED = {
    "ok": True,
    "message": (
        "If that address belongs to an enrolled account, a sign-in link is on its way. "
        "The link works once and expires after seven days."
    ),
}

_MAIL_TEXT = """\
Hello{name},

Here is your sign-in link for {site}:

{link}

It works once and expires in {days} days. Opening it signs this browser in; you
can then press "Sign in" inside an assignment notebook to connect it.

If you did not ask for this link you can ignore this message -- nothing has
changed on your account.
"""

_MAIL_HTML = """\
<p>Hello{name},</p>
<p>Here is your sign-in link for {site}:</p>
<p><a href="{link}">Sign in to the grader</a></p>
<p>It works once and expires in {days} days. Opening it signs this browser in; you
can then press <b>Sign in</b> inside an assignment notebook to connect it.</p>
<p>If you did not ask for this link you can ignore this message &mdash; nothing has
changed on your account.</p>
"""


class EmailLoginRequest(BaseModel):
    email: str
    next: str | None = None


def netid_from_address(address: str, domain: str) -> str | None:
    """Return the NetID an address stands for, or ``None`` if it is not one.

    The rule matches ``roster.py._netid_from_email``: at the campus domain, the
    local part *is* the NetID. Keeping it in one shape means the address is
    never stored -- it is a lookup key, not a new column on ``users``.
    """
    e = (address or "").strip().lower()
    if not _ADDRESS_RE.match(e):
        return None
    local, _, host = e.partition("@")
    if host != domain.strip().lower() or not _LOCAL_PART_RE.match(local):
        return None
    return local


def _enrolled(db: Session, user: User) -> bool:
    return (
        db.scalar(
            select(Enrollment).where(
                Enrollment.user_id == user.id,
                Enrollment.status == EnrollmentStatus.active,
            )
        )
        is not None
    )


@router.post("/email-login", status_code=202)
def email_login(body: EmailLoginRequest, db: Session = Depends(get_db)):
    """Mail a one-time sign-in link to an enrolled student's campus address.

    Unauthenticated by necessity, so it is fenced in four ways: the feature is
    off unless an operator turns it on, only addresses at the configured domain
    are considered, only NetIDs that already have an active enrollment receive
    anything (this route never creates a user), and each NetID is rate limited.
    Every outcome returns the same body.
    """
    s = get_settings()
    if not s.email_login_enabled:
        raise api_error(404, "not_found", "not found")

    netid = netid_from_address(body.email, s.email_login_domain)
    if netid is None:
        return _ACCEPTED
    user = db.scalar(select(User).where(User.netid == netid))
    if user is None or not _enrolled(db, user):
        return _ACCEPTED

    sent_today, latest = device.login_code_rate(
        db, user, device.EMAIL_LOGIN_CLIENT, window_seconds=24 * 3600
    )
    too_soon = (
        latest is not None
        and (datetime.now(UTC) - latest).total_seconds() < s.email_login_min_interval_seconds
    )
    if sent_today >= s.email_login_max_per_day or too_soon:
        log.info("email login link rate limited netid=%s sent_today=%d", netid, sent_today)
        return _ACCEPTED

    code = device.mint_login_code(
        db,
        user,
        client=device.EMAIL_LOGIN_CLIENT,
        ttl_seconds=s.email_login_ttl_seconds,
    )
    link = f"{s.base_url}/api/v1/auth/exchange?code={quote(code, safe='')}"
    target = _safe_next(body.next)
    if target != "/":
        link += "&next=" + quote(target, safe="")

    fields = {
        "name": f" {user.name}" if user.name else "",
        "site": urlparse(s.frontend_url).hostname or "DartBrains",
        "link": link,
        "days": max(1, s.email_login_ttl_seconds // 86400),
    }
    try:
        mail.send(
            mail.Message(
                to=f"{netid}@{s.email_login_domain}",
                subject="Your sign-in link for the DartBrains grader",
                text=_MAIL_TEXT.format(**fields),
                html=_MAIL_HTML.format(**fields),
            )
        )
    except mail.MailError:
        # Drop the code we just minted so a delivery outage does not burn the
        # student's daily allowance, and keep the response indistinguishable.
        log.exception("email login link could not be delivered netid=%s", netid)
        db.rollback()
        return _ACCEPTED

    audit.record(
        db,
        actor_id=user.id,
        offering_id=None,
        entity="user",
        entity_id=user.id,
        action="email_login_sent",
        after={"client": device.EMAIL_LOGIN_CLIENT, "ttl_seconds": s.email_login_ttl_seconds},
        reason="self-service sign-in link",
    )
    return _ACCEPTED


# --- device handshake -------------------------------------------------------


class DeviceStart(BaseModel):
    client: str | None = None


class DevicePoll(BaseModel):
    device_code: str


@router.post("/device")
def device_start(body: DeviceStart, db: Session = Depends(get_db)):
    return device.start(db, body.client)


@router.post("/device/token")
def device_token(body: DevicePoll, db: Session = Depends(get_db)):
    return device.poll(db, body.device_code)


_DISABLED_BODY = (
    "<h1>Sign-in is not available yet</h1>"
    "<p>Dartmouth single sign-on for this grader is still being set up. "
    "You can keep working in the notebook: <b>Check</b> runs locally. "
    "Submitting will open once sign-in is enabled.</p>"
)

_VERIFY_PAGE = """<!doctype html><meta charset="utf-8"><title>Grader sign-in</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem;color:#171C19}}
h1{{font-size:1.4rem}} code{{font-size:1.3rem;letter-spacing:.08em}} .ok{{color:#00693E}} .err{{color:#8A2A00}}
form{{margin-top:1rem}} button{{font:inherit;padding:.5rem 1rem;background:#00693E;color:#fff;border:0;border-radius:4px}}
input{{font:inherit;padding:.4rem;width:10rem}}</style>{body}"""


@router.get("/device/verify", response_class=HTMLResponse)
def device_verify(
    request: Request,
    code: str | None = None,
    p: Principal | None = Depends(optional_principal),
    db: Session = Depends(get_db),
):
    s = get_settings()
    if p is None or p.via != "session":
        here = f"/api/v1/auth/device/verify?{urlencode({'code': code or ''})}"
        # After SAML the ACS redirects to the frontend; the frontend forwards
        # any path under /api/v1/auth/device/verify back to us unchanged.
        return RedirectResponse(f"{s.base_url}/api/v1/auth/login?next={quote(here, safe='')}")
    if not code:
        body = (
            "<h1>Connect a notebook</h1><p>Enter the code shown in your notebook.</p>"
            "<form method='get'><input name='code' placeholder='ABCD-1234' autofocus> "
            "<button>Continue</button></form>"
        )
        return HTMLResponse(_VERIFY_PAGE.format(body=body))
    row = device.approve(db, code, p.user)
    if row is None:
        body = (
            "<h1 class='err'>That code is not valid</h1>"
            "<p>It may have expired or already been used. Click <b>Sign in</b> in the notebook again.</p>"
        )
        return HTMLResponse(_VERIFY_PAGE.format(body=body), status_code=400)
    body = (
        f"<h1 class='ok'>Signed in as {html.escape(p.user.netid)}</h1>"
        f"<p>Code <code>{html.escape(row.user_code)}</code> is connected. You can close this tab and return to your notebook.</p>"
    )
    return HTMLResponse(_VERIFY_PAGE.format(body=body))
