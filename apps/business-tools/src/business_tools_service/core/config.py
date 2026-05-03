from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ENV_ALIASES = {
    "APP_ENV": ("APP_ENV", "SMARTCLOUD_ENV"),
    "LOG_LEVEL": ("LOG_LEVEL", "SMARTCLOUD_LOG_LEVEL"),
    "API_PREFIX": ("API_PREFIX", "SMARTCLOUD_API_PREFIX"),
    "DEFAULT_TIMEZONE": ("DEFAULT_TIMEZONE", "SMARTCLOUD_TIMEZONE"),
    "DEFAULT_LANGUAGE": ("DEFAULT_LANGUAGE", "SMARTCLOUD_DEFAULT_LOCALE"),
    "REQUEST_TIMEOUT_MS": ("REQUEST_TIMEOUT_MS", "SMARTCLOUD_REQUEST_TIMEOUT_MS"),
    "BUSINESS_TOOLS_RUNTIME_DIR": ("BUSINESS_TOOLS_RUNTIME_DIR",),
    "SMARTCLOUD_REDIS_URL": ("SMARTCLOUD_REDIS_URL",),
}


RELEASE_ENVS = {"staging", "prod"}
LOCAL_FALLBACK_ENVS = {"local", "dev", "test"}


def _coerce_value(raw: str) -> Any:
    value = raw.strip()
    lower = value.lower()
    if lower in {"true", "false"}:
        return lower == "true"
    if value.isdigit():
        return int(value)
    if "," in value and not value.startswith(("http://", "https://")):
        return [item.strip() for item in value.split(",") if item.strip()]
    if value.startswith(('"', "'")) and value.endswith(('"', "'")) and len(value) >= 2:
        return value[1:-1]
    return value


def _load_dotenv(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        data[key.strip()] = _coerce_value(value)
    return data


def _load_flat_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        data[key.strip()] = _coerce_value(value)
    return data


class Settings(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    app_env: Literal["local", "dev", "test", "staging", "prod"] = Field(default="dev", alias="APP_ENV")
    app_name: str = Field(default="business-tools-service", alias="APP_NAME")
    app_version: str = Field(default="0.3.0", alias="APP_VERSION")
    app_port: int = Field(default=8030, alias="APP_PORT")
    api_prefix: str = Field(default="/api/v1", alias="API_PREFIX")
    internal_api_prefix: str = "/internal/v1"
    log_level: Literal["DEBUG", "INFO", "WARN", "ERROR"] = Field(default="INFO", alias="LOG_LEVEL")
    default_timezone: str = Field(default="Asia/Shanghai", alias="DEFAULT_TIMEZONE")
    default_language: str = Field(default="zh-CN", alias="DEFAULT_LANGUAGE")
    request_timeout_ms: int = Field(default=30000, alias="REQUEST_TIMEOUT_MS")
    request_id_header: str = Field(default="X-Request-Id", alias="SMARTCLOUD_REQUEST_ID_HEADER")
    trace_id_header: str = Field(default="X-Trace-Id", alias="SMARTCLOUD_TRACE_ID_HEADER")
    conversation_id_header: str = Field(default="X-Conversation-Id", alias="SMARTCLOUD_CONVERSATION_ID_HEADER")
    message_id_header: str = Field(default="X-Message-Id", alias="SMARTCLOUD_MESSAGE_ID_HEADER")
    tenant_id_header: str = Field(default="X-Tenant-Id", alias="SMARTCLOUD_TENANT_ID_HEADER")
    caller_service_header: str = Field(default="X-Caller-Service", alias="SMARTCLOUD_CALLER_SERVICE_HEADER")
    tool_call_id_header: str = Field(default="X-Tool-Call-Id", alias="SMARTCLOUD_TOOL_CALL_ID_HEADER")
    idempotency_key_header: str = Field(default="Idempotency-Key", alias="SMARTCLOUD_IDEMPOTENCY_KEY_HEADER")
    allowed_internal_callers: list[str] = Field(
        default_factory=lambda: ["tool-hub-service"],
        alias="ALLOWED_INTERNAL_CALLERS",
    )
    runtime_data_dir: str | None = Field(default=None, alias="BUSINESS_TOOLS_RUNTIME_DIR")
    redis_url: str | None = Field(default=None, alias="SMARTCLOUD_REDIS_URL")
    redis_namespace: str = Field(default="smartcloud:business-tools", alias="BUSINESS_TOOLS_REDIS_NAMESPACE")
    database_url: str | None = Field(default=None, alias="SMARTCLOUD_MYSQL_DSN")
    tool_query_cache_enabled: bool = Field(default=True, alias="TOOL_QUERY_CACHE_ENABLED")
    tool_query_cache_ttl_cap_seconds: int = Field(default=300, alias="TOOL_QUERY_CACHE_TTL_CAP_SECONDS")
    idempotency_store_path: str | None = Field(default=None, alias="BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH")
    query_cache_store_path: str | None = Field(default=None, alias="BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH")
    runtime_mode: Literal["shared-backend", "mixed", "local-fallback"] = "local-fallback"
    release_readiness_required_components: list[str] = Field(default_factory=list)
    local_fallback_components: list[str] = Field(default_factory=list)

    @field_validator("api_prefix", "internal_api_prefix")
    @classmethod
    def _validate_prefix(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("API prefix must start with '/'.")
        return value.rstrip("/") or "/"

    @field_validator("request_timeout_ms", "tool_query_cache_ttl_cap_seconds")
    @classmethod
    def _validate_timeout(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Numeric settings must be greater than 0.")
        return value

    @field_validator(
        "request_id_header",
        "trace_id_header",
        "conversation_id_header",
        "message_id_header",
        "tenant_id_header",
        "caller_service_header",
        "tool_call_id_header",
        "idempotency_key_header",
    )
    @classmethod
    def _validate_header_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or any(char.isspace() for char in normalized) or ":" in normalized:
            raise ValueError("Header names must be non-empty HTTP token strings.")
        return normalized

    @field_validator("allowed_internal_callers", mode="before")
    @classmethod
    def _validate_allowed_internal_callers(cls, value: list[str] | str) -> list[str]:
        if isinstance(value, str):
            value = [item.strip() for item in value.split(",") if item.strip()]
        callers = [caller.strip() for caller in value if caller and caller.strip()]
        if not callers:
            raise ValueError("ALLOWED_INTERNAL_CALLERS must not be empty.")
        return callers

    @model_validator(mode="after")
    def _validate_prod(self) -> "Settings":
        if self.app_env == "prod" and self.log_level == "DEBUG":
            raise ValueError("DEBUG logging is not allowed in prod.")
        if self.app_env in RELEASE_ENVS and not self.redis_url:
            raise ValueError(
                f"{self.app_env} requires middleware-backed business-tools runtime config: SMARTCLOUD_REDIS_URL."
            )
        if self.app_env in RELEASE_ENVS:
            self.release_readiness_required_components = ["redis"]
            self.local_fallback_components = []
            self.runtime_mode = "shared-backend"
            return self

        fallback_components: list[str] = []
        if self.redis_url and (self.idempotency_store_path or self.query_cache_store_path):
            fallback_components.extend(["idempotency_store", "query_cache_store"])
        self.release_readiness_required_components = ["redis"]
        self.local_fallback_components = fallback_components
        self.runtime_mode = "mixed" if fallback_components else "local-fallback"
        return self


def build_settings(service_root: Path | None = None, environ: dict[str, str] | None = None) -> Settings:
    root = service_root or Path(__file__).resolve().parents[3]
    env = dict(os.environ if environ is None else environ)
    app_env = env.get("APP_ENV") or env.get("SMARTCLOUD_ENV") or "dev"

    merged: dict[str, Any] = {}
    merged.update(_load_flat_yaml(root / "config" / "settings" / f"{app_env}.yaml"))
    merged.update(_load_dotenv(root / f".env.{app_env}"))

    for canonical, aliases in ENV_ALIASES.items():
        for alias in aliases:
            if alias in env and env[alias] not in {"", None}:
                merged[canonical] = _coerce_value(str(env[alias]))
                break

    passthrough_keys = {
        "APP_NAME",
        "APP_VERSION",
        "APP_PORT",
        "DEFAULT_TIMEZONE",
        "DEFAULT_LANGUAGE",
        "REQUEST_TIMEOUT_MS",
        "SMARTCLOUD_REQUEST_ID_HEADER",
        "SMARTCLOUD_TRACE_ID_HEADER",
        "SMARTCLOUD_CONVERSATION_ID_HEADER",
        "SMARTCLOUD_MESSAGE_ID_HEADER",
        "SMARTCLOUD_TENANT_ID_HEADER",
        "SMARTCLOUD_CALLER_SERVICE_HEADER",
        "SMARTCLOUD_TOOL_CALL_ID_HEADER",
        "SMARTCLOUD_IDEMPOTENCY_KEY_HEADER",
        "ALLOWED_INTERNAL_CALLERS",
        "TOOL_QUERY_CACHE_ENABLED",
        "TOOL_QUERY_CACHE_TTL_CAP_SECONDS",
        "BUSINESS_TOOLS_RUNTIME_DIR",
        "SMARTCLOUD_REDIS_URL",
        "SMARTCLOUD_MYSQL_DSN",
        "BUSINESS_TOOLS_REDIS_NAMESPACE",
        "BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH",
        "BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH",
    }
    for key in passthrough_keys:
        if key in env and env[key] not in {"", None}:
            merged[key] = _coerce_value(str(env[key]))

    runtime_dir = Path(str(merged.get("BUSINESS_TOOLS_RUNTIME_DIR") or (root / ".tmp" / "business-tools-service"))).expanduser()
    merged.setdefault("BUSINESS_TOOLS_RUNTIME_DIR", str(runtime_dir))
    if app_env in LOCAL_FALLBACK_ENVS and merged.get("SMARTCLOUD_REDIS_URL") not in {None, ""}:
        merged.setdefault(
            "BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH",
            str(runtime_dir / "degraded-idempotency-store.json"),
        )
        merged.setdefault(
            "BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH",
            str(runtime_dir / "degraded-query-cache-store.json"),
        )

    merged.setdefault("APP_ENV", app_env)
    return Settings.model_validate(merged)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return build_settings()
