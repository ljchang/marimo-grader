"""Authentication routes: SAML login/ACS/metadata, sessions, and the device handshake."""

from __future__ import annotations

import html
from urllib.parse import quote, urlencode

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

router = APIRouter(prefix="/auth", tags=["auth"])


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
        "display_name": user.display_name,
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


@router.get("/csrf")
def csrf(p: Principal = Depends(current_principal)):
    if p.via != "session":
        raise api_error(400, "not_session", "CSRF tokens only apply to cookie sessions")
    return {"csrf_token": p.session_csrf}


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
