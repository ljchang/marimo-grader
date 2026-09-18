"""Storage broker: turn an enrollment into prefix-scoped R2 credentials.

Design: docs/storage-architecture.md §4–5. The grader sits in the control
path only. It decides which bucket prefixes a caller may touch, asks Cloudflare
for temporary S3 credentials limited to exactly those prefixes, records the
grant, and hands the credentials to the notebook. Bytes flow between the
runtime and R2 directly; nothing large ever passes through here.

Two credentials per session, because an R2 temporary credential carries one
permission for all of its prefixes: ``ro`` covers course data, released
assignments and the shared cache; ``rw`` covers the caller's own prefixes.
A student who prints both learns nothing beyond what they were already
authorised to read -- neither credential can name a neighbour's prefix.

Prefix layout (one bucket, ``<off>`` = ``<course slug>-<term>``)::

    course/<off>/                private class datasets       student: ro
    assignments/<off>/<slug>/    exams; ro only once released
    users/<off>/<uid>/           private student storage      student: rw
    groups/<off>/<gslug>/        project groups               members: rw
    cache/shared/<off>/          instructor-warmed derivatives student: ro
    cache/users/<off>/<uid>/     student's own derivatives    student: rw

``<uid>`` is an HMAC of the NetID under a per-deployment secret, so a listing
never exposes the roster and a leaked credential names nobody.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from grader.auth.deps import Membership
from grader.config import Settings, get_settings
from grader.models import (
    Assignment,
    Enrollment,
    EnrollmentStatus,
    Group,
    GroupMember,
    Role,
    StorageGrant,
)
from grader.util import iso

CF_API = "https://api.cloudflare.com/client/v4"

# Public, unauthenticated datasets the library resolves to Hugging Face. Listed
# here so a notebook can ask one endpoint "where does everything live".
PUBLIC_DATASETS = {
    "localizer": "dartbrains/localizer",
    "sherlock": "dartbrains/sherlock",
    "paranoia": "dartbrains/paranoia",
}


class StorageError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class Mount:
    logical: str  # what the notebook addresses, e.g. "/private"
    prefix: str  # bucket prefix, always ends with "/"
    mode: str  # "r" | "rw"

    @property
    def cred(self) -> str:
        return "rw" if self.mode == "rw" else "ro"

    def json(self) -> dict:
        return {
            "logical": self.logical,
            "prefix": self.prefix,
            "mode": self.mode,
            "cred": self.cred,
        }


# --------------------------------------------------------------------------
# Naming
# --------------------------------------------------------------------------


def offering_slug(m: Membership) -> str:
    return f"{m.offering.course.slug}-{m.offering.term}"


def uid_for(settings: Settings, offering_id, netid: str) -> str:
    """Opaque per-offering student id. Stable, so the same student lands in the
    same prefix all term; unlinkable to the NetID without the secret."""
    secret = (settings.storage_uid_secret or "").encode()
    return hmac.new(secret, f"{offering_id}:{netid}".encode(), hashlib.sha256).hexdigest()[:16]


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def assignment_released(a: Assignment, now: datetime) -> bool:
    """Students may read an assignment's data from ``release_at`` until ``close_at``.
    Neither set means always released, matching how assignments behaved before
    storage existed."""
    s = a.settings or {}
    release, close = _parse(s.get("release_at")), _parse(s.get("close_at"))
    if release and now < release:
        return False
    if close and now >= close:
        return False
    return True


# --------------------------------------------------------------------------
# Authorization: which prefixes does this enrollment get?
# --------------------------------------------------------------------------


def grants_for(db: Session, m: Membership, now: datetime | None = None) -> list[Mount]:
    now = now or datetime.now(UTC)
    s = get_settings()
    off = offering_slug(m)
    uid = uid_for(s, m.offering.id, m.user.netid)
    instructor = m.role == Role.instructor
    staff = m.is_staff()

    # Instructors write course data and the shared cache (that is how they get
    # seeded and warmed); everyone else reads them.
    shared_mode = "rw" if instructor else "r"
    mounts = [
        Mount("/course", f"course/{off}/", shared_mode),
        Mount("/cache/shared", f"cache/shared/{off}/", shared_mode),
    ]

    assignments = db.scalars(
        select(Assignment).where(Assignment.offering_id == m.offering.id).order_by(Assignment.slug)
    ).all()
    for a in assignments:
        if staff or assignment_released(a, now):
            mounts.append(
                Mount(f"/assignments/{a.slug}", f"assignments/{off}/{a.slug}/", shared_mode)
            )

    mounts.append(Mount("/private", f"users/{off}/{uid}/", "rw"))
    mounts.append(Mount("/cache/private", f"cache/users/{off}/{uid}/", "rw"))

    groups = db.scalars(
        select(Group)
        .join(GroupMember, GroupMember.group_id == Group.id)
        .where(GroupMember.enrollment_id == m.enrollment.id)
        .order_by(Group.slug)
    ).all()
    for g in groups:
        logical = "/group" if len(groups) == 1 else f"/group/{g.slug}"
        mounts.append(Mount(logical, f"groups/{off}/{g.slug}/", "rw"))

    if staff:
        # Staff read every student's private area they are allowed to grade.
        # A section-scoped TA gets one prefix per student in their sections.
        scoped = m.enrollment.ta_sections or []
        if instructor or not scoped:
            mounts.append(Mount("/students", f"users/{off}/", "r"))
        else:
            rows = db.scalars(
                select(Enrollment).where(
                    Enrollment.offering_id == m.offering.id,
                    Enrollment.role == Role.student,
                    Enrollment.status == EnrollmentStatus.active,
                )
            ).all()
            for e in rows:
                if m.can_see_section(e.section_id):
                    u = uid_for(s, m.offering.id, e.user.netid)
                    mounts.append(Mount(f"/students/{e.user.netid}", f"users/{off}/{u}/", "r"))
        if instructor:
            mounts.append(Mount("/groups", f"groups/{off}/", "rw"))

    return mounts


def resolve(mounts: list[Mount], path: str, *, write: bool = False) -> tuple[Mount, str]:
    """Map a logical path onto (mount, object key); refuse anything outside the grants."""
    if not path.startswith("/"):
        raise StorageError("bad_path", "path must start with '/'")
    parts = path.split("/")[1:]
    if any(p in ("", ".", "..") for p in parts) or any("\\" in p or "\0" in p for p in parts):
        raise StorageError("bad_path", "path contains an empty, '.', or '..' segment")
    best: Mount | None = None
    for mt in mounts:
        root = mt.logical.rstrip("/") + "/"
        if path.startswith(root) and (best is None or len(mt.logical) > len(best.logical)):
            best = mt
    if best is None:
        raise StorageError("forbidden", f"no access to {path}", status=403)
    if write and best.mode != "rw":
        raise StorageError("forbidden", f"{best.logical} is read-only", status=403)
    rest = path[len(best.logical.rstrip("/")) + 1 :]
    return best, best.prefix + rest


# --------------------------------------------------------------------------
# Cloudflare
# --------------------------------------------------------------------------


class CloudflareR2:
    """The two calls the broker makes with the parent credentials.

    Tests replace ``temp_credentials`` and ``presign`` on this class; nothing
    else in the module talks to the network.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.s = settings or get_settings()

    def temp_credentials(self, *, prefixes: list[str], permission: str, ttl: int) -> dict:
        """POST r2/temp-access-credentials. Needs an account API token with the
        account-wide *Workers R2 Storage: Edit* permission (the bucket-scoped
        variant is refused with code 10000 -- see docs §5.4)."""
        url = f"{CF_API}/accounts/{self.s.cf_account_id}/r2/temp-access-credentials"
        body = {
            "bucket": self.s.r2_bucket,
            "parentAccessKeyId": self.s.r2_parent_access_key_id,
            "permission": permission,
            "ttlSeconds": ttl,
            "prefixes": prefixes,
        }
        r = httpx.post(
            url, json=body, headers={"Authorization": f"Bearer {self.s.cf_api_token}"}, timeout=30
        )
        payload = r.json() if r.content else {}
        if r.status_code != 200 or not payload.get("success"):
            raise StorageError(
                "cloudflare",
                f"credential mint failed: HTTP {r.status_code} {payload.get('errors')}",
                502,
            )
        res = payload["result"]
        return {
            "access_key_id": res["accessKeyId"],
            "secret_access_key": res["secretAccessKey"],
            "session_token": res["sessionToken"],
        }

    def presign(self, *, key: str, method: str, expires: int) -> str:
        """A presigned URL under the parent key, for runtimes that cannot SigV4
        (the in-browser WASM workbench)."""
        import obstore
        from obstore.store import S3Store

        store = S3Store(
            self.s.r2_bucket,
            endpoint=self.s.r2_endpoint,
            region="auto",
            virtual_hosted_style_request=False,
            access_key_id=self.s.r2_parent_access_key_id,
            secret_access_key=self.s.r2_parent_secret_access_key,
        )
        return obstore.sign(store, method, key, timedelta(seconds=expires))


# --------------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------------


def public_json() -> list[dict]:
    return [
        {"logical": f"/data/{name}", "backend": "hf", "repo": repo}
        for name, repo in PUBLIC_DATASETS.items()
    ]


def open_session(
    db: Session, m: Membership, *, client: str | None = None, cf: CloudflareR2 | None = None
) -> dict:
    """Mint the two credentials for this enrollment and record the grant."""
    s = get_settings()
    cf = cf or CloudflareR2(s)
    now = datetime.now(UTC)
    mounts = grants_for(db, m, now)
    ro = sorted({mt.prefix for mt in mounts if mt.cred == "ro"})
    rw = sorted({mt.prefix for mt in mounts if mt.cred == "rw"})
    ttl = s.storage_credential_ttl_seconds

    creds: dict[str, dict] = {}
    if ro:
        creds["ro"] = cf.temp_credentials(prefixes=ro, permission="object-read-only", ttl=ttl)
    if rw:
        creds["rw"] = cf.temp_credentials(prefixes=rw, permission="object-read-write", ttl=ttl)

    db.add(
        StorageGrant(
            user_id=m.user.id,
            offering_id=m.offering.id,
            role=m.role.value,
            prefixes_ro=ro,
            prefixes_rw=rw,
            ttl_seconds=ttl,
            client=(client or "")[:120] or None,
        )
    )
    db.commit()

    return {
        "backend": "r2",
        "endpoint": s.r2_endpoint,
        "bucket": s.r2_bucket,
        "region": "auto",
        "expires_at": iso(now + timedelta(seconds=ttl)),
        "mounts": [mt.json() for mt in mounts],
        "public": public_json(),
        "credentials": creds,
    }
