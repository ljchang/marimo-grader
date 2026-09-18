"""Storage broker routes (docs/storage-architecture.md §5.1).

    GET  /offerings/{id}/storage/me        what the caller may reach; no credentials
    POST /offerings/{id}/storage/session   prefix-scoped R2 credentials for one hour
    POST /offerings/{id}/storage/presign   one presigned URL, for runtimes without SigV4

All three resolve the caller's enrollment first, like every other offering
route. Storage is off (404) until the operator sets GRADER_STORAGE_ENABLED and
the Cloudflare values in deploy/README.md.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from grader.auth.deps import Membership, api_error, require_member
from grader.config import get_settings
from grader.db import get_db
from grader.services import storage

router = APIRouter(tags=["storage"])


def _enabled() -> None:
    if not get_settings().storage_enabled:
        raise api_error(404, "storage_disabled", "storage is not enabled on this server")


class SessionIn(BaseModel):
    client: str | None = Field(default=None, max_length=120)


class PresignIn(BaseModel):
    path: str = Field(min_length=2, max_length=1024)
    method: Literal["GET", "HEAD", "PUT"] = "GET"
    expires: int = Field(default=900, ge=60)


@router.get("/offerings/{offering_id}/storage/me")
def storage_me(m: Membership = Depends(require_member), db: Session = Depends(get_db)):
    _enabled()
    return {
        "bucket": get_settings().r2_bucket,
        "mounts": [mt.json() for mt in storage.grants_for(db, m)],
        "public": storage.public_json(),
    }


@router.post("/offerings/{offering_id}/storage/session")
def storage_session(
    body: SessionIn | None = None,
    m: Membership = Depends(require_member),
    db: Session = Depends(get_db),
):
    _enabled()
    try:
        return storage.open_session(db, m, client=(body.client if body else None))
    except storage.StorageError as e:
        raise api_error(e.status, e.code, str(e)) from e


@router.post("/offerings/{offering_id}/storage/presign")
def storage_presign(
    body: PresignIn, m: Membership = Depends(require_member), db: Session = Depends(get_db)
):
    _enabled()
    s = get_settings()
    expires = min(body.expires, s.storage_presign_max_seconds)
    try:
        mount, key = storage.resolve(
            storage.grants_for(db, m), body.path, write=body.method == "PUT"
        )
        url = storage.CloudflareR2(s).presign(key=key, method=body.method, expires=expires)
    except storage.StorageError as e:
        raise api_error(e.status, e.code, str(e)) from e
    return {"url": url, "key": key, "mount": mount.logical, "expires_in": expires}
