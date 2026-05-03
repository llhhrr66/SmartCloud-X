from __future__ import annotations

from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.store import get_auth_store


SERVICE_NAME = "auth-user-service"


def _backend_record(
    *,
    kind: str,
    role: str,
    configured: bool,
    active: bool,
    restart_durable: bool,
    required_for_release: bool,
    evidence: str,
    fallback: str | None,
    notes: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": kind,
        "role": role,
        "configured": configured,
        "active": active,
        "restart_durable": restart_durable,
        "required_for_release": required_for_release,
        "evidence": evidence,
        "fallback": fallback,
    }
    if notes:
        payload["notes"] = notes
    return payload


def _database_backend_records(settings: Any) -> tuple[dict[str, Any], str, list[str]]:
    database_url = settings.database_url
    using_sqlite = database_url.startswith("sqlite")
    mysql_configured = bool(__import__("os").getenv("SMARTCLOUD_MYSQL_DSN")) or database_url.startswith(("mysql://", "mysql+pymysql://"))
    mysql_active = not using_sqlite and database_url.startswith(("mysql://", "mysql+pymysql://"))

    runtime_mode = "shared-backend"
    if using_sqlite and mysql_configured:
        runtime_mode = "mixed"
    elif using_sqlite:
        runtime_mode = "local-fallback"

    mysql_notes: str | None = None
    if using_sqlite:
        mysql_notes = "set SMARTCLOUD_MYSQL_DSN or AUTH_USER_SERVICE_DATABASE_URL to promote the shared backend"
    elif not mysql_active:
        mysql_notes = "configured database_url is not using the shared MySQL backend"

    sqlite_fallback = str(settings.bootstrap_path) if settings.bootstrap_path else None
    sqlite_notes = "local/test compatibility database derived from owner config"
    if runtime_mode == "mixed":
        sqlite_notes = (
            "sqlite fallback remains configured while the shared MySQL backend is not active in the current runtime"
        )

    backends = {
        "mysql": _backend_record(
            kind="mysql",
            role="primary",
            configured=mysql_configured,
            active=mysql_active,
            restart_durable=mysql_active,
            required_for_release=True,
            evidence="engine-dialect" if mysql_active else "config-only",
            fallback="sqlite://local-fallback",
            notes=mysql_notes,
        ),
        "sqlite": _backend_record(
            kind="sqlite",
            role="fallback",
            configured=using_sqlite,
            active=using_sqlite,
            restart_durable=using_sqlite,
            required_for_release=False,
            evidence="engine-dialect" if using_sqlite else "config-only",
            fallback=sqlite_fallback,
            notes=sqlite_notes,
        ),
        "redis": _backend_record(
            kind="redis",
            role="optional",
            configured=bool(settings.redis_url),
            active=False,
            restart_durable=False,
            required_for_release=False,
            evidence="config-only",
            fallback=None,
            notes="declared config only; current auth runtime persists revocation and session state in database tables",
        ),
    }

    not_ready_components: list[str] = []
    if runtime_mode != "shared-backend":
        not_ready_components.append("mysql")
    return backends, runtime_mode, not_ready_components


def _database_probe() -> dict[str, Any]:
    store = get_auth_store()
    session_factory = getattr(store, "_session_factory", None)
    if session_factory is None:
        raise RuntimeError("auth store session factory is unavailable")
    with session_factory() as session:
        session.execute(__import__("sqlalchemy").text("SELECT 1"))
    return {
        "ready": True,
        "status": "ready",
        "mode": "sql",
        "service": SERVICE_NAME,
        "notReadyComponents": [],
    }


def build_runtime_health_payload(settings: Any | None = None) -> dict[str, Any]:
    """Build the auth runtime health payload with backend evidence."""
    resolved_settings = settings or get_settings()
    backends, runtime_mode, _ = _database_backend_records(resolved_settings)
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "runtime_mode": runtime_mode,
        "backends": backends,
    }


def build_runtime_readiness_payload(settings: Any | None = None) -> tuple[int, dict[str, Any]]:
    """Build the auth readiness payload and matching HTTP status code."""
    resolved_settings = settings or get_settings()
    backends, runtime_mode, not_ready_components = _database_backend_records(resolved_settings)
    runtime: dict[str, Any] = {
        "backends": backends,
    }

    try:
        runtime["database"] = _database_probe()
    except (RuntimeError, SQLAlchemyError, OSError, ValueError) as exc:
        runtime["database"] = {
            "ready": False,
            "status": "not_ready",
            "mode": "sql",
            "service": SERVICE_NAME,
            "notReadyComponents": ["database"],
            "error": str(exc),
        }
        if "database" not in not_ready_components:
            not_ready_components.append("database")

    status = "ready" if not not_ready_components else "not_ready"
    payload = {
        "status": status,
        "service": SERVICE_NAME,
        "runtime_mode": runtime_mode,
        "not_ready_components": not_ready_components,
        "runtime": runtime,
        "backends": backends,
    }
    return (200 if status == "ready" else 503), payload
