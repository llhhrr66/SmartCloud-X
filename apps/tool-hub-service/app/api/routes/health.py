from fastapi import APIRouter
from fastapi.responses import JSONResponse

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
    return {
        "auditStore": _audit_store.describe_backend(),
        "businessToolsIdempotency": local_runtime["idempotency"],
        "businessToolsQueryCache": local_runtime["queryCache"],
        "businessToolsTransport": {
            "transport": settings.business_tools_transport,
            "baseUrl": settings.business_tools_base_url if settings.business_tools_transport == "http" else None,
            "internalApiPrefix": settings.business_tools_internal_api_prefix,
            "degradedLocalFallbackEnabled": settings.app_env in {"local", "dev", "test"},
            "dependencyReadiness": _business_tools_client.dependency_readiness(),
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
        "service": "tool-hub-service",
        "degraded_components": degraded_components,
        "runtime": runtime,
    }


@router.get("/readyz")
def readyz() -> JSONResponse:
    runtime = _runtime_snapshot()
    not_ready_components = _degraded_components(runtime)
    payload = {
        "status": "ready" if not not_ready_components else "not_ready",
        "service": "tool-hub-service",
        "not_ready_components": not_ready_components,
        "runtime": runtime,
    }
    return JSONResponse(status_code=200 if not not_ready_components else 503, content=payload)
