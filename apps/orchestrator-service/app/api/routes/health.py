from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.services.mongo_runtime import DisabledConversationMongoRuntime
from app.services.tool_hub_client import ToolHubClient

router = APIRouter(tags=["health"])
_tool_hub_client = ToolHubClient()


def _document_store_degraded(description: object, *, include_optional: bool = False) -> bool:
    if not isinstance(description, dict):
        return False
    document_store = description.get("documentStore")
    if not isinstance(document_store, dict):
        return False
    required = bool(document_store.get("required"))
    configured = bool(document_store.get("configured"))
    if not required and not (include_optional and configured):
        return False
    if document_store.get("degradedFrom"):
        return True
    if document_store.get("backendError"):
        return True
    return document_store.get("ready") is not True


def _component_degraded(description: object, *, include_optional_document_store: bool = False) -> bool:
    if not isinstance(description, dict):
        return False
    if description.get("degradedFrom"):
        return True
    if _document_store_degraded(
        description,
        include_optional=include_optional_document_store,
    ):
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
        _runtime,
        _sse_event_store,
        _state_store,
    )
    from app.core.business_tools_sdk import describe_local_runtime
    from app.core.config import get_settings

    settings = get_settings()
    local_runtime = describe_local_runtime(settings=settings)
    dependency_readiness = _tool_hub_client.dependency_readiness()

    strict_remote_discovery_enabled: bool | None = False
    if settings.tool_hub_transport == "http":
        readiness_value = dependency_readiness.get("strictRemoteDiscoveryEnabled")
        strict_remote_discovery_enabled = readiness_value if isinstance(readiness_value, bool) else None

    conversation_store = _conversation_store.describe_backend()
    document_store = conversation_store.get("documentStore")
    if not isinstance(document_store, dict):
        document_store = DisabledConversationMongoRuntime().describe_backend()
    conversation_store = {
        **conversation_store,
        "documentStore": {
            **document_store,
            "required": settings.conversation_document_store_required,
        },
    }

    return {
        "conversationStore": conversation_store,
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
            "strictRemoteDiscoveryEnabled": strict_remote_discovery_enabled,
            "dependencyReadiness": dependency_readiness,
        },
        "ragServiceClient": _runtime._rag_client.describe_runtime(),
    }


def _degraded_components(
    runtime: dict[str, object],
    *,
    include_optional_document_store: bool = False,
) -> list[str]:
    return [
        name
        for name, description in runtime.items()
        if _component_degraded(
            description,
            include_optional_document_store=include_optional_document_store,
        )
    ]


@router.get("/healthz")
def healthz() -> dict[str, object]:
    runtime = _runtime_snapshot()
    degraded_components = _degraded_components(runtime, include_optional_document_store=True)
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
