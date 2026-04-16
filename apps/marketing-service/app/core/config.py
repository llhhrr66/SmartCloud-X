from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


DEFAULT_CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def _service_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _parse_csv_env(name: str, default: list[str]) -> list[str]:
    raw_value = os.getenv(name)
    if not raw_value:
        return default
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _resolve_path_env_aliases(names: tuple[str, ...], default: Path | None) -> Path | None:
    for name in names:
        raw_value = os.getenv(name)
        if raw_value:
            return Path(raw_value).expanduser()
    return default


def _legacy_sqlite_database_url(names: tuple[str, ...]) -> str | None:
    path = _resolve_path_env_aliases(names, None)
    if path is None:
        return None
    return f"sqlite:///{path.with_suffix('.db').as_posix()}"


def _optional_env(name: str) -> str | None:
    raw_value = os.getenv(name)
    if raw_value is None:
        return None
    normalized = raw_value.strip()
    return normalized or None


def _default_database_url() -> str:
    return (
        os.getenv("MARKETING_SERVICE_DATABASE_URL")
        or _legacy_sqlite_database_url(("MARKETING_SERVICE_BOOTSTRAP_PATH", "MARKETING_SERVICE_DATA_PATH"))
        or os.getenv("SMARTCLOUD_MYSQL_DSN")
        or f"sqlite:///{(_service_root() / 'data' / 'marketing-service.db').as_posix()}"
    )


class Settings(BaseModel):
    app_name: str = "smartcloud-x-marketing-service"
    app_version: str = "0.2.0"
    api_prefix: str = "/api/v1"
    env: str = Field(default_factory=lambda: os.getenv("SMARTCLOUD_ENV", "local"))
    log_level: str = Field(default_factory=lambda: os.getenv("SMARTCLOUD_LOG_LEVEL", "INFO"))
    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: _parse_csv_env(
            "SMARTCLOUD_CORS_ALLOWED_ORIGINS",
            DEFAULT_CORS_ALLOWED_ORIGINS,
        )
    )
    request_id_header: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_REQUEST_ID_HEADER", "X-Request-Id")
    )
    trace_id_header: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_TRACE_ID_HEADER", "X-Trace-Id")
    )
    conversation_id_header: str = Field(
        default_factory=lambda: os.getenv(
            "SMARTCLOUD_CONVERSATION_ID_HEADER",
            "X-Conversation-Id",
        )
    )
    tenant_id_header: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_TENANT_ID_HEADER", "X-Tenant-Id")
    )
    caller_service_header: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_CALLER_SERVICE_HEADER", "X-Caller-Service")
    )
    auth_issuer: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_AUTH_ISSUER", "smartcloud-x")
    )
    auth_audience: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_AUTH_AUDIENCE", "smartcloud-x-clients")
    )
    internal_auth_audience: str = Field(
        default_factory=lambda: os.getenv(
            "SMARTCLOUD_INTERNAL_AUTH_AUDIENCE",
            "smartcloud-x-internal",
        )
    )
    jwt_secret: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_JWT_SECRET", "smartcloud-x-dev-secret")
    )
    jwt_algorithm: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_JWT_ALGORITHM", "HS256")
    )
    access_token_ttl_minutes: int = Field(
        default_factory=lambda: int(os.getenv("SMARTCLOUD_TOKEN_TTL_MINUTES", "120"))
    )
    auth_validation_mode: Literal["local", "strict"] = Field(
        default_factory=lambda: os.getenv("MARKETING_SERVICE_AUTH_VALIDATION_MODE", "local")
    )
    auth_validate_token_url: str | None = Field(
        default_factory=lambda: _optional_env("MARKETING_SERVICE_AUTH_VALIDATE_TOKEN_URL")
    )
    auth_validate_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("MARKETING_SERVICE_AUTH_VALIDATE_TIMEOUT_SECONDS", "3"))
    )
    internal_service_name: str = Field(
        default_factory=lambda: os.getenv("MARKETING_SERVICE_INTERNAL_SERVICE_NAME", "marketing-service")
    )
    database_url: str = Field(default_factory=_default_database_url)
    bootstrap_path: Path | None = Field(
        default_factory=lambda: _resolve_path_env_aliases(
            ("MARKETING_SERVICE_BOOTSTRAP_PATH", "MARKETING_SERVICE_DATA_PATH"),
            _service_root() / "data" / "marketing-store.json",
        )
    )
    redis_url: str | None = Field(
        default_factory=lambda: os.getenv("MARKETING_SERVICE_REDIS_URL")
        or os.getenv("SMARTCLOUD_REDIS_URL")
    )
    redis_namespace: str = Field(
        default_factory=lambda: os.getenv("MARKETING_SERVICE_REDIS_NAMESPACE", "smartcloud-x:marketing")
    )
    minio_endpoint: str | None = Field(
        default_factory=lambda: os.getenv("MARKETING_SERVICE_MINIO_ENDPOINT")
        or os.getenv("SMARTCLOUD_MINIO_ENDPOINT")
    )
    minio_bucket: str | None = Field(
        default_factory=lambda: os.getenv("MARKETING_SERVICE_MINIO_BUCKET")
        or os.getenv("SMARTCLOUD_MINIO_BUCKET")
        or "marketing-artifacts"
    )
    minio_access_key: str | None = Field(
        default_factory=lambda: os.getenv("MARKETING_SERVICE_MINIO_ACCESS_KEY")
        or os.getenv("SMARTCLOUD_MINIO_ACCESS_KEY")
    )
    minio_secret_key: str | None = Field(
        default_factory=lambda: os.getenv("MARKETING_SERVICE_MINIO_SECRET_KEY")
        or os.getenv("SMARTCLOUD_MINIO_SECRET_KEY")
    )
    poster_public_base_url: str = Field(
        default_factory=lambda: os.getenv(
            "MARKETING_SERVICE_POSTER_PUBLIC_BASE_URL",
            "https://cdn.smartcloud.local/posters",
        )
    )
    promotion_short_link_base_url: str = Field(
        default_factory=lambda: os.getenv(
            "MARKETING_SERVICE_SHORT_LINK_BASE_URL",
            "https://go.smartcloud.local",
        )
    )
    default_estimated_seconds: int = Field(
        default_factory=lambda: int(os.getenv("MARKETING_SERVICE_ESTIMATED_SECONDS", "30"))
    )
    task_auto_complete_seconds: int = Field(
        default_factory=lambda: int(os.getenv("MARKETING_SERVICE_AUTO_COMPLETE_SECONDS", "0"))
    )

    model_config = {"arbitrary_types_allowed": True}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
