from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime

from sqlalchemy import or_


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(value)
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _normalize_database_url(database_url: str) -> str:
    return database_url


def _connect_args(database_url: str) -> dict[str, object]:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def _tenant_filter(column, tenant_id: str | None):
    if tenant_id is None:
        return column.is_(None)
    return or_(column == tenant_id, column.is_(None))


def _payload_hash(*, user_id: str, tenant_id: str | None, normalized_payload: str) -> str:
    digest = hashlib.sha256()
    digest.update(user_id.encode("utf-8"))
    digest.update(b"|")
    digest.update((tenant_id or "").encode("utf-8"))
    digest.update(b"|")
    digest.update(normalized_payload.encode("utf-8"))
    return digest.hexdigest()


def _run_coroutine_in_new_loop(awaitable):
    return asyncio.run(awaitable)
