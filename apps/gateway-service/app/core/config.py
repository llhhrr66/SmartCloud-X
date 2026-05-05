from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlparse


def _read_env_list(name: str, default: str) -> list[str]:
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


def _read_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _normalize_service_base_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme and parsed.hostname in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
        netloc = host
        if parsed.port is not None:
            netloc = f"{host}:{parsed.port}"
        return parsed._replace(netloc=netloc).geturl()
    return value


@dataclass(slots=True)
class GatewaySettings:
    app_name: str = "gateway-service"
    app_version: str = "0.1.0"
    request_timeout_ms: int = 10_000
    cors_allowed_origins: list[str] = field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3100",
            "http://127.0.0.1:3100",
            "http://localhost:8050",
            "http://127.0.0.1:8050",
        ]
    )
    request_id_header: str = "X-Request-Id"
    trace_id_header: str = "X-Trace-Id"
    tenant_id_header: str = "X-Tenant-Id"
    caller_service_header: str = "X-Caller-Service"
    idempotency_key_header: str = "Idempotency-Key"
    operator_reason_header: str = "X-Operator-Reason"
    conversation_id_header: str = "X-Conversation-Id"
    tool_call_id_header: str = "X-Tool-Call-Id"
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60
    gateway_store_path: str = "apps/gateway-service/data/gateway-store.json"
    auth_user_service_base_url: str = "http://localhost:8001"
    marketing_service_base_url: str = "http://localhost:8002"
    research_service_base_url: str = "http://localhost:8003"
    orchestrator_service_base_url: str = "http://localhost:8010"
    tool_hub_service_base_url: str = "http://localhost:8020"
    business_tools_service_base_url: str = "http://localhost:8030"
    knowledge_service_base_url: str = "http://localhost:8031"
    rag_service_base_url: str = "http://localhost:8040"
    object_storage_base_url: str = ""
    redis_url: str | None = None  # SMARTCLOUD_REDIS_URL

    @classmethod
    def from_env(cls) -> "GatewaySettings":
        return cls(
            request_timeout_ms=_read_env_int("SMARTCLOUD_REQUEST_TIMEOUT_MS", 10_000),
            cors_allowed_origins=_read_env_list(
                "SMARTCLOUD_CORS_ALLOWED_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3100,http://127.0.0.1:3100,http://localhost:8050,http://127.0.0.1:8050",
            ),
            request_id_header=os.getenv("SMARTCLOUD_REQUEST_ID_HEADER", "X-Request-Id"),
            trace_id_header=os.getenv("SMARTCLOUD_TRACE_ID_HEADER", "X-Trace-Id"),
            tenant_id_header=os.getenv("SMARTCLOUD_TENANT_ID_HEADER", "X-Tenant-Id"),
            caller_service_header=os.getenv("SMARTCLOUD_CALLER_SERVICE_HEADER", "X-Caller-Service"),
            idempotency_key_header=os.getenv("SMARTCLOUD_IDEMPOTENCY_KEY_HEADER", "Idempotency-Key"),
            operator_reason_header=os.getenv("SMARTCLOUD_OPERATOR_REASON_HEADER", "X-Operator-Reason"),
            conversation_id_header=os.getenv("SMARTCLOUD_CONVERSATION_ID_HEADER", "X-Conversation-Id"),
            tool_call_id_header=os.getenv("SMARTCLOUD_TOOL_CALL_ID_HEADER", "X-Tool-Call-Id"),
            rate_limit_requests=_read_env_int("GATEWAY_RATE_LIMIT_REQUESTS", 120),
            rate_limit_window_seconds=_read_env_int("GATEWAY_RATE_LIMIT_WINDOW_SECONDS", 60),
            gateway_store_path=os.getenv(
                "GATEWAY_STORE_PATH", "apps/gateway-service/data/gateway-store.json"
            ),
            auth_user_service_base_url=_normalize_service_base_url(
                os.getenv("AUTH_USER_SERVICE_BASE_URL", "http://localhost:8001")
            ),
            marketing_service_base_url=_normalize_service_base_url(
                os.getenv("MARKETING_SERVICE_BASE_URL", "http://localhost:8002")
            ),
            research_service_base_url=_normalize_service_base_url(
                os.getenv("RESEARCH_SERVICE_BASE_URL", "http://localhost:8003")
            ),
            orchestrator_service_base_url=_normalize_service_base_url(
                os.getenv("ORCHESTRATOR_SERVICE_BASE_URL", "http://localhost:8010")
            ),
            tool_hub_service_base_url=_normalize_service_base_url(
                os.getenv("TOOL_HUB_SERVICE_BASE_URL", "http://localhost:8020")
            ),
            business_tools_service_base_url=_normalize_service_base_url(
                os.getenv("BUSINESS_TOOLS_SERVICE_BASE_URL", "http://localhost:8030")
            ),
            knowledge_service_base_url=_normalize_service_base_url(
                os.getenv("KNOWLEDGE_SERVICE_BASE_URL", "http://localhost:8031")
            ),
            rag_service_base_url=_normalize_service_base_url(
                os.getenv("RAG_SERVICE_BASE_URL", "http://localhost:8040")
            ),
            object_storage_base_url=os.getenv("OBJECT_STORAGE_BASE_URL", ""),
            redis_url=os.getenv("SMARTCLOUD_REDIS_URL"),
        )
