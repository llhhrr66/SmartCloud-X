from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings
from app.services import runtime_mysql


TABLE_NAME = "orchestrator_llm_providers"


def _ensure_schema(cursor) -> None:
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS `{TABLE_NAME}` (
            provider_id VARCHAR(128) PRIMARY KEY,
            name VARCHAR(128) NOT NULL,
            api_key TEXT NOT NULL,
            api_url VARCHAR(512) NOT NULL,
            model_name VARCHAR(128) NOT NULL,
            provider_type VARCHAR(64) NOT NULL DEFAULT 'openai-compatible',
            is_active TINYINT NOT NULL DEFAULT 0,
            created_at VARCHAR(128) NOT NULL,
            updated_at VARCHAR(128) NOT NULL
        )
        """
    )
    runtime_mysql.create_index_if_missing(
        cursor,
        table_name=TABLE_NAME,
        index_name=f"idx_{TABLE_NAME}_active",
        columns=("is_active",),
    )


def _connect():
    settings = get_settings()
    if not settings.mysql_dsn:
        raise RuntimeError("MySQL DSN not configured for LLM provider store")
    return runtime_mysql.connect(settings.mysql_dsn)


def list_providers() -> list[dict[str, Any]]:
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            _ensure_schema(cursor)
            cursor.execute(f"SELECT * FROM `{TABLE_NAME}` ORDER BY created_at DESC")
            rows = cursor.fetchall() or []
    finally:
        conn.close()
    return rows


def get_provider(provider_id: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            _ensure_schema(cursor)
            cursor.execute(f"SELECT * FROM `{TABLE_NAME}` WHERE provider_id = %s", (provider_id,))
            return cursor.fetchone()
    finally:
        conn.close()


def get_active_provider() -> dict[str, Any] | None:
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            _ensure_schema(cursor)
            cursor.execute(f"SELECT * FROM `{TABLE_NAME}` WHERE is_active = 1 LIMIT 1")
            return cursor.fetchone()
    finally:
        conn.close()


def create_provider(data: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    provider_id = data.get("provider_id") or f"llm-{uuid.uuid4().hex[:12]}"
    row = {
        "provider_id": provider_id,
        "name": data["name"],
        "api_key": data["api_key"],
        "api_url": data["api_url"],
        "model_name": data["model_name"],
        "provider_type": data.get("provider_type", "openai-compatible"),
        "is_active": 1 if data.get("is_active", False) else 0,
        "created_at": now,
        "updated_at": now,
    }
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            _ensure_schema(cursor)
            if row["is_active"]:
                cursor.execute(f"UPDATE `{TABLE_NAME}` SET is_active = 0 WHERE is_active = 1")
            cols = ", ".join(row.keys())
            placeholders = ", ".join(["%s"] * len(row))
            cursor.execute(
                f"INSERT INTO `{TABLE_NAME}` ({cols}) VALUES ({placeholders})",
                tuple(row.values()),
            )
        conn.commit()
    finally:
        conn.close()
    return row


def update_provider(provider_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    current = get_provider(provider_id)
    if not current:
        return None
    now = datetime.now(timezone.utc).isoformat()
    updates: dict[str, Any] = {"updated_at": now}
    for key in ("name", "api_key", "api_url", "model_name", "provider_type"):
        if key in data and data[key] is not None:
            updates[key] = data[key]
    if "is_active" in data and data["is_active"] is not None:
        updates["is_active"] = 1 if data["is_active"] else 0
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            _ensure_schema(cursor)
            if updates.get("is_active") == 1:
                cursor.execute(
                    f"UPDATE `{TABLE_NAME}` SET is_active = 0 WHERE is_active = 1 AND provider_id != %s",
                    (provider_id,),
                )
            set_clause = ", ".join(f"{k} = %s" for k in updates)
            values = list(updates.values()) + [provider_id]
            cursor.execute(f"UPDATE `{TABLE_NAME}` SET {set_clause} WHERE provider_id = %s", tuple(values))
        conn.commit()
    finally:
        conn.close()
    return get_provider(provider_id)


def delete_provider(provider_id: str) -> bool:
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            _ensure_schema(cursor)
            cursor.execute(f"DELETE FROM `{TABLE_NAME}` WHERE provider_id = %s", (provider_id,))
            affected = cursor.rowcount
        conn.commit()
    finally:
        conn.close()
    return affected > 0
