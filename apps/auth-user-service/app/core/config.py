from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field


DEFAULT_CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
DEFAULT_INTERNAL_CALLERS = [
    "gateway-service",
    "orchestrator-service",
    "tool-hub-service",
    "business-tools",
    "business-tools-service",
    "knowledge-service",
    "rag-service",
    "research-service",
    "marketing-service",
    "auth-user-service",
]


def _service_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _parse_csv_env(name: str, default: list[str]) -> list[str]:
    raw_value = os.getenv(name)
    if not raw_value:
        return default
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _parse_csv_env_aliases(names: tuple[str, ...], default: list[str]) -> list[str]:
    for name in names:
        raw_value = os.getenv(name)
        if raw_value:
            return [item.strip() for item in raw_value.split(",") if item.strip()]
    return default


def _resolve_path_env(name: str, default: Path) -> Path:
    raw_value = os.getenv(name)
    if not raw_value:
        return default
    return Path(raw_value).expanduser()


class Settings(BaseModel):
    app_name: str = "smartcloud-x-auth-user-service"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    internal_api_prefix: str = "/internal/v1"
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
    jwt_algorithm: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_JWT_ALGORITHM", "HS256")
    )
    jwt_secret: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_JWT_SECRET", "smartcloud-x-dev-secret")
    )
    access_token_ttl_minutes: int = Field(
        default_factory=lambda: int(os.getenv("SMARTCLOUD_TOKEN_TTL_MINUTES", "120"))
    )
    refresh_token_ttl_minutes: int = Field(
        default_factory=lambda: int(os.getenv("AUTH_USER_SERVICE_REFRESH_TOKEN_TTL_MINUTES", "43200"))
    )
    verification_code_ttl_seconds: int = Field(
        default_factory=lambda: int(os.getenv("AUTH_USER_SERVICE_CODE_TTL_SECONDS", "300"))
    )
    reset_challenge_ttl_seconds: int = Field(
        default_factory=lambda: int(os.getenv("AUTH_USER_SERVICE_RESET_TTL_SECONDS", "600"))
    )
    admin_confirm_ttl_seconds: int = Field(
        default_factory=lambda: int(os.getenv("AUTH_USER_SERVICE_ADMIN_CONFIRM_TTL_SECONDS", "300"))
    )
    default_locale: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_DEFAULT_LOCALE", "zh-CN")
    )
    default_time_zone: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_TIMEZONE", "Asia/Shanghai")
    )
    data_path: Path = Field(
        default_factory=lambda: _resolve_path_env(
            "AUTH_USER_SERVICE_DATA_PATH",
            _service_root() / "data" / "auth-store.json",
        )
    )
    allowed_internal_callers: list[str] = Field(
        default_factory=lambda: _parse_csv_env_aliases(
            ("ALLOWED_INTERNAL_CALLERS", "AUTH_USER_SERVICE_ALLOWED_INTERNAL_CALLERS"),
            DEFAULT_INTERNAL_CALLERS,
        )
    )

    model_config = {"arbitrary_types_allowed": True}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
