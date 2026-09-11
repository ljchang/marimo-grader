"""Database engine and session management.

Sync SQLAlchemy 2.0 with psycopg 3. FastAPI runs sync endpoints in a
threadpool, which keeps the code straightforward and lets Alembic, the
worker, and tests share one engine configuration.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from grader.config import get_settings


@lru_cache
def get_engine() -> Engine:
    url = get_settings().database_url
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        # Dev/tests only. Keep foreign keys on so cascade behaviour matches Postgres.
        # An in-memory database must share one connection across threads (StaticPool);
        # a file-backed one gets a normal pool so concurrent requests do not share a cursor.
        kwargs.update(connect_args={"check_same_thread": False})
        if ":memory:" in url:
            from sqlalchemy.pool import StaticPool

            kwargs["poolclass"] = StaticPool
        engine = create_engine(url, **kwargs)

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _record):  # pragma: no cover - trivial
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return engine
    return create_engine(url, **kwargs)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, committed on success."""
    db = get_sessionmaker()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
