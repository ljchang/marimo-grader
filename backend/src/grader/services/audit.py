"""Append-only audit trail for grade, roster, settings, and export actions."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from grader.models import GradeAudit


def record(
    db: Session,
    *,
    actor_id: uuid.UUID | None,
    offering_id: uuid.UUID | None,
    entity: str,
    entity_id: Any,
    action: str,
    before: dict | None = None,
    after: dict | None = None,
    reason: str | None = None,
) -> GradeAudit:
    row = GradeAudit(
        actor_user_id=actor_id,
        offering_id=offering_id,
        entity=entity,
        entity_id=str(entity_id),
        action=action,
        before=before,
        after=after,
        reason=reason,
    )
    db.add(row)
    db.flush()
    return row
