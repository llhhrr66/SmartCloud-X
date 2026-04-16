import os
from functools import lru_cache

from pydantic import BaseModel, Field


def _build_api_prefix(service_segment: str) -> str:
    base = os.getenv("SMARTCLOUD_API_PREFIX", "/api").rstrip("/")
    version = os.getenv("SMARTCLOUD_API_VERSION", "v1").strip("/")
    return f"{base}/{service_segment}/{version}"


DEFAULT_CORS_ALLOWED_ORIGINS = [
    "http://localhost:8050",
    "http://127.0.0.1:8050",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def _parse_csv_env(name: str, default: list[str]) -> list[str]:
    raw_value = os.getenv(name)
    if not raw_value:
        return default
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _parse_bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _default_otlp_endpoint() -> str | None:
    return os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or os.getenv(
        "SMARTCLOUD_PHOENIX_COLLECTOR_ENDPOINT"
    )


def _default_trace_enabled() -> bool:
    return _parse_bool_env("SMARTCLOUD_TRACE_ENABLED", bool(_default_otlp_endpoint()))


class Settings(BaseModel):
    app_name: str = "smartcloud-x-rag-service"
    app_version: str = "0.1.0"
    api_prefix: str = Field(default_factory=lambda: _build_api_prefix("rag"))
    env: str = Field(default_factory=lambda: os.getenv("SMARTCLOUD_ENV", "development"))
    log_level: str = Field(default_factory=lambda: os.getenv("SMARTCLOUD_LOG_LEVEL", "INFO"))
    knowledge_service_base_url: str = Field(
        default_factory=lambda: os.getenv("KNOWLEDGE_SERVICE_BASE_URL", "http://localhost:8030")
    )
    knowledge_service_api_prefix: str = Field(default_factory=lambda: _build_api_prefix("knowledge"))
    request_timeout_ms: int = Field(
        default_factory=lambda: int(os.getenv("SMARTCLOUD_REQUEST_TIMEOUT_MS", "10000"))
    )
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
            "SMARTCLOUD_CONVERSATION_ID_HEADER", "X-Conversation-Id"
        )
    )
    tenant_id_header: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_TENANT_ID_HEADER", "X-Tenant-Id")
    )
    caller_service_header: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_CALLER_SERVICE_HEADER", "X-Caller-Service")
    )
    redis_url: str | None = Field(default_factory=lambda: os.getenv("SMARTCLOUD_REDIS_URL"))
    cache_enabled: bool = Field(
        default_factory=lambda: _parse_bool_env("SMARTCLOUD_RAG_CACHE_ENABLED", True)
    )
    cache_ttl_seconds: int = Field(
        default_factory=lambda: int(os.getenv("SMARTCLOUD_RAG_CACHE_TTL_SECONDS", "60"))
    )
    cache_namespace: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_RAG_CACHE_NAMESPACE", "smartcloud-x:rag")
    )
    trace_enabled: bool = Field(default_factory=_default_trace_enabled)
    otlp_endpoint: str | None = Field(default_factory=_default_otlp_endpoint)
    otlp_protocol: str = Field(
        default_factory=lambda: os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc")
    )
    otel_service_name: str = Field(
        default_factory=lambda: os.getenv(
            "OTEL_SERVICE_NAME",
            "smartcloud-x-rag-service",
        )
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
