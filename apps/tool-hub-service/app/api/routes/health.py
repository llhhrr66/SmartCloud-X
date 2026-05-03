from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from app.core.observability import metrics_content_type, metrics_payload, metric_snapshot, set_readiness_state
from app.services.idempotency import coordinator as idempotency_coordinator

router = APIRouter(tags=["health"])


def _component_degraded(description: object) -> bool:
    return (
        isinstance(description, dict)
        and (
            bool(description.get("degradedFrom"))
            or (
                isinstance(description.get("dependencyReadiness"), dict)
                and description["dependencyReadiness"].get("ready") is False
            )
        )
    )


def _runtime_snapshot() -> dict[str, object]:
    from app.api.routes.tools import _audit_store, _business_tools_client
    from app.core.business_tools_sdk import describe_local_runtime
    from app.core.config import get_settings

    settings = get_settings()
    local_runtime = describe_local_runtime(settings=settings)
    idempotency_stats = idempotency_coordinator.stats()
    return {
        "auditStore": _audit_store.describe_backend(),
        "businessToolsIdempotency": local_runtime["idempotency"],
        "businessToolsQueryCache": local_runtime["queryCache"],
        "businessToolsTransport": {
            "transport": settings.business_tools_transport,
            "baseUrl": settings.business_tools_base_url if settings.business_tools_transport == "http" else None,
            "internalApiPrefix": settings.business_tools_internal_api_prefix,
            "degradedLocalFallbackEnabled": settings.app_env in {"local", "dev", "test"},
            "strictRemoteDiscoveryEnabled": bool(
                settings.business_tools_transport == "http" and settings.business_tools_discovery_strict
            ),
            "dependencyReadiness": _business_tools_client.dependency_readiness(),
        },
        "toolHubIdempotency": {
            "ttlSeconds": idempotency_coordinator.ttl_seconds,
            **idempotency_stats,
        },
        "metrics": metric_snapshot(),
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
    set_readiness_state(not degraded_components)
    return {
        "status": "degraded" if degraded_components else "ok",
        "service": "tool-hub-service",
        "degraded_components": degraded_components,
        "runtime": runtime,
    }


@router.get("/metrics")
def metrics() -> Response:
    return Response(content=metrics_payload(), media_type=metrics_content_type())


@router.get("/readyz")
def readyz() -> JSONResponse:
    runtime = _runtime_snapshot()
    not_ready_components = _degraded_components(runtime)
    set_readiness_state(not not_ready_components)
    payload = {
        "status": "ready" if not not_ready_components else "not_ready",
        "service": "tool-hub-service",
        "not_ready_components": not_ready_components,
        "runtime": runtime,
    }
    return JSONResponse(status_code=200 if not not_ready_components else 503, content=payload)
