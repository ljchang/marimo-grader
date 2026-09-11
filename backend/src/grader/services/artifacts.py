"""Content-addressed artifact store.

v1 stores bytes on a local (encrypted) volume under ``<artifact_dir>/<aa>/<bb>/<sha256>``.
The interface is deliberately S3-shaped (put/get by key) so an object-store
backend can replace it without touching callers.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy.orm import Session

from grader.config import get_settings
from grader.models import Artifact


class ArtifactStore:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or get_settings().artifact_dir)

    def _path(self, key: str) -> Path:
        return self.root / key

    def put(self, db: Session, data: bytes, *, kind: str, content_type: str) -> Artifact:
        sha = hashlib.sha256(data).hexdigest()
        key = f"{sha[:2]}/{sha[2:4]}/{sha}"
        p = self._path(key)
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(p)
        art = Artifact(
            sha256=sha, size=len(data), content_type=content_type, kind=kind, storage_key=key
        )
        db.add(art)
        db.flush()
        return art

    def get(self, art: Artifact) -> bytes:
        return self._path(art.storage_key).read_bytes()

    def path(self, art: Artifact) -> Path:
        return self._path(art.storage_key)


def store() -> ArtifactStore:
    return ArtifactStore()
