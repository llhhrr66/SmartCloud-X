"""Database connection helper for business-tools service.

Reads ``SMARTCLOUD_MYSQL_DSN`` from settings and exposes a thread-local
session factory.  When the DSN is unset (local/dev), all query helpers
fall back to returning ``None`` so that the static baseline path remains
available.
"""

from __future__ import annotations

from functools import lru_cache
from threading import local as thread_local

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from business_tools_service.core.config import get_settings

_local = thread_local()


@lru_cache(maxsize=1)
def _engine():
    settings = get_settings()
    dsn = settings.database_url
    if not dsn:
        return None
    return create_engine(
        dsn,
        future=True,
        pool_pre_ping=True,
        pool_size=4,
        max_overflow=2,
    )


def get_session() -> Session | None:
    """Return a new SQLAlchemy Session, or *None* when no DSN is configured."""
    engine = _engine()
    if engine is None:
        return None
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return factory()


def query_one(sql: str, params: dict | None = None) -> dict | None:
    """Execute a SELECT that returns a single row.  Returns ``None`` on no match or no DB."""
    session = get_session()
    if session is None:
        return None
    try:
        row = session.execute(text(sql), params).mappings().first()
        return dict(row) if row else None
    finally:
        session.close()


def query_all(sql: str, params: dict | None = None) -> list[dict]:
    """Execute a SELECT that returns multiple rows.  Returns ``[]`` on no DB."""
    session = get_session()
    if session is None:
        return []
    try:
        rows = session.execute(text(sql), params).mappings().all()
        return [dict(r) for r in rows]
    finally:
        session.close()


def execute_write(sql: str, params: dict | None = None) -> int:
    """Execute an INSERT/UPDATE and return affected row count.  Returns ``0`` on no DB."""
    engine = _engine()
    if engine is None:
        return 0
    with engine.begin() as conn:
        result = conn.execute(text(sql), params)
        return result.rowcount
