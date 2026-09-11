"""Small shared helpers."""

from __future__ import annotations

from datetime import UTC, datetime


def iso(dt: datetime | None) -> str | None:
    """ISO 8601 with an explicit UTC offset. SQLite returns naive datetimes; treat them as UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()
