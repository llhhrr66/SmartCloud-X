from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal


BUSINESS_TOOLS_SRC = Path(__file__).resolve().parents[3] / "business-tools" / "src"
if str(BUSINESS_TOOLS_SRC) not in sys.path:
    sys.path.insert(0, str(BUSINESS_TOOLS_SRC))

from business_tools import (  # noqa: E402
    BusinessTool,
    CompensationExecutionRequest,
    CompensationExecutionResult,
    ToolAuthRequirements,
    ToolCompensationAction,
    ToolDefinition,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolInvocationRequest,
    ToolMode,
    ToolUserActionHint,
    build_catalog,
    configure_idempotency_store,
    configure_query_cache,
    execute_compensation,
    filter_tool_definitions,
    get_idempotency_store,
    get_query_cache_store,
    ToolPreflightResult,
    is_missing_tool_value,
    preflight_tool_invocation,
)

__all__ = [
    "BusinessTool",
    "CompensationExecutionRequest",
    "CompensationExecutionResult",
    "ToolAuthRequirements",
    "ToolCompensationAction",
    "ToolDefinition",
    "ToolExecutionContext",
    "ToolExecutionResult",
    "ToolInvocationRequest",
    "ToolMode",
    "ToolPreflightResult",
    "ToolUserActionHint",
    "build_catalog",
    "configure_idempotency_store",
    "configure_query_cache",
    "execute_compensation",
    "filter_tool_definitions",
    "get_idempotency_store",
    "get_query_cache_store",
    "is_missing_tool_value",
    "preflight_tool_invocation",
]


_LOCAL_RUNTIME_CONFIGURATION: tuple[object, ...] | None = None
_LOCAL_RUNTIME_ACTIVATION_MODE: Literal["transport-local", "degraded-fallback"] | None = None
_DEFAULT_BUSINESS_TOOLS_REDIS_NAMESPACE = "smartcloud:business-tools"


def _normalize_namespace(value: str | None) -> str:
    raw = str(value or "").strip().strip(":")
    parts = [part for part in raw.split(":") if part]
    return ":".join(parts) or _DEFAULT_BUSINESS_TOOLS_REDIS_NAMESPACE


def _component_namespace(value: str | None, component: str) -> str:
    return f"{_normalize_namespace(value)}:{component}"


def ensure_local_runtime(
    *,
    activation_mode: Literal["transport-local", "degraded-fallback"],
    settings=None,
) -> None:
    from app.core.config import get_settings

    global _LOCAL_RUNTIME_CONFIGURATION, _LOCAL_RUNTIME_ACTIVATION_MODE

    settings = settings or get_settings()
    configuration = (
        settings.business_tools_idempotency_store_path,
        settings.business_tools_query_cache_store_path,
        settings.redis_url,
        settings.business_tools_redis_namespace,
        settings.tool_query_cache_enabled,
        settings.tool_query_cache_ttl_cap_seconds,
    )
    if configuration != _LOCAL_RUNTIME_CONFIGURATION:
        configure_idempotency_store(
            persistence_path=settings.business_tools_idempotency_store_path,
            redis_url=settings.redis_url,
            redis_namespace=_component_namespace(settings.business_tools_redis_namespace, "idempotency"),
        )
        configure_query_cache(
            enabled=settings.tool_query_cache_enabled,
            ttl_cap_seconds=settings.tool_query_cache_ttl_cap_seconds,
            persistence_path=settings.business_tools_query_cache_store_path,
            redis_url=settings.redis_url,
            redis_namespace=_component_namespace(settings.business_tools_redis_namespace, "query-cache"),
        )
        _LOCAL_RUNTIME_CONFIGURATION = configuration
    _LOCAL_RUNTIME_ACTIVATION_MODE = activation_mode


def describe_local_runtime(*, settings=None) -> dict[str, dict[str, object]]:
    from app.core.config import get_settings

    settings = settings or get_settings()
    if settings.business_tools_transport == "local":
        ensure_local_runtime(activation_mode="transport-local", settings=settings)

    if _LOCAL_RUNTIME_ACTIVATION_MODE is None:
        return {
            "idempotency": {
                "active": False,
                "backend": "inactive",
                "activationMode": "degraded-fallback-only",
                "redisConfigured": bool(settings.redis_url),
                "redisNamespace": _component_namespace(settings.business_tools_redis_namespace, "idempotency")
                if settings.redis_url
                else None,
                "fallbackPath": settings.business_tools_idempotency_store_path,
            },
            "queryCache": {
                "active": False,
                "backend": "inactive",
                "activationMode": "degraded-fallback-only",
                "enabled": settings.tool_query_cache_enabled,
                "ttlCapSeconds": settings.tool_query_cache_ttl_cap_seconds,
                "redisConfigured": bool(settings.redis_url),
                "redisNamespace": _component_namespace(settings.business_tools_redis_namespace, "query-cache")
                if settings.redis_url
                else None,
                "fallbackPath": settings.business_tools_query_cache_store_path,
            },
        }

    idempotency = get_idempotency_store().describe_backend()
    query_cache = get_query_cache_store().describe_backend()
    return {
        "idempotency": {
            **idempotency,
            "active": True,
            "activationMode": _LOCAL_RUNTIME_ACTIVATION_MODE,
        },
        "queryCache": {
            **query_cache,
            "active": True,
            "activationMode": _LOCAL_RUNTIME_ACTIVATION_MODE,
        },
    }


def reset_local_runtime_state() -> None:
    global _LOCAL_RUNTIME_CONFIGURATION, _LOCAL_RUNTIME_ACTIVATION_MODE

    _LOCAL_RUNTIME_CONFIGURATION = None
    _LOCAL_RUNTIME_ACTIVATION_MODE = None
