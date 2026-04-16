from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


def _runtime_snapshot() -> dict[str, object]:
    from business_tools import get_idempotency_store, get_query_cache_store

    return {
        "idempotency": get_idempotency_store().describe_backend(),
        "queryCache": get_query_cache_store().describe_backend(),
    }


def _degraded_components(runtime: dict[str, object]) -> list[str]:
    return [
        name
        for name, description in runtime.items()
        if isinstance(description, dict) and description.get("degradedFrom")
    ]


@router.get("/healthz")
def healthz() -> dict[str, object]:
    runtime = _runtime_snapshot()
    degraded_components = _degraded_components(runtime)
    return {
        "status": "degraded" if degraded_components else "ok",
        "service": "business-tools-service",
        "degraded_components": degraded_components,
        "runtime": runtime,
    }


@router.get("/readyz")
def readyz() -> JSONResponse:
    runtime = _runtime_snapshot()
    not_ready_components = _degraded_components(runtime)
    payload = {
        "status": "ready" if not not_ready_components else "not_ready",
        "service": "business-tools-service",
        "not_ready_components": not_ready_components,
        "runtime": runtime,
    }
    return JSONResponse(status_code=200 if not not_ready_components else 503, content=payload)
