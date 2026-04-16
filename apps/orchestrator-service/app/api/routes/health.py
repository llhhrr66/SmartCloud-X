from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.services.tool_hub_client import ToolHubClient

router = APIRouter(tags=["health"])
_tool_hub_client = ToolHubClient()


def _component_degraded(description: object) -> bool:
    if not isinstance(description, dict):
        return False
    if description.get("degradedFrom"):
        return True
    runtime_cache = description.get("runtimeCache")
    if isinstance(runtime_cache, dict) and bool(runtime_cache.get("degradedFrom")):
        return True
    dependency_readiness = description.get("dependencyReadiness")
    return isinstance(dependency_readiness, dict) and dependency_readiness.get("ready") is False


def _runtime_snapshot() -> dict[str, object]:
    from app.api.routes.orchestration import (
        _agent_config_store,
        _conversation_store,
        _run_control,
        _sse_event_store,
        _state_store,
    )
    from app.core.business_tools_sdk import describe_local_runtime
    from app.core.config import get_settings

    settings = get_settings()
    local_runtime = describe_local_runtime(settings=settings)
    return {
        "conversationStore": _conversation_store.describe_backend(),
        "stateStore": _state_store.describe_backend(),
        "sseStore": _sse_event_store.describe_backend(),
        "agentConfigStore": _agent_config_store.describe_backend(),
        "runControl": _run_control.describe_backend(),
        "businessToolsIdempotency": local_runtime["idempotency"],
        "businessToolsQueryCache": local_runtime["queryCache"],
        "toolHubTransport": {
            "transport": settings.tool_hub_transport,
            "baseUrl": settings.tool_hub_base_url if settings.tool_hub_transport == "http" else None,
            "internalApiPrefix": settings.tool_hub_internal_api_prefix,
            "degradedLocalFallbackEnabled": settings.app_env in {"local", "dev", "test"},
            "dependencyReadiness": _tool_hub_client.dependency_readiness(),
        },
    }


def _degraded_components(runtime: dict[str, object]) -> list[str]:
    return [
        name
        for name, description in runtime.items()
        if _component_degraded(description)
    ]


@router.get("/healthz")
def healthz() -> dict[str, object]:
    runtime = _runtime_snapshot()
    degraded_components = _degraded_components(runtime)
    return {
        "status": "degraded" if degraded_components else "ok",
        "service": "orchestrator-service",
        "degraded_components": degraded_components,
        "runtime": runtime,
    }


@router.get("/readyz")
def readyz() -> JSONResponse:
    runtime = _runtime_snapshot()
    not_ready_components = _degraded_components(runtime)
    payload = {
        "status": "ready" if not not_ready_components else "not_ready",
        "service": "orchestrator-service",
        "not_ready_components": not_ready_components,
        "runtime": runtime,
    }
    return JSONResponse(status_code=200 if not not_ready_components else 503, content=payload)
