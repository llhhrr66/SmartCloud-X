from __future__ import annotations

from fastapi import APIRouter, Query
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.routes.orchestration import _conversation_store

router = APIRouter(tags=["admin"])


@router.get("/admin/saga/events")
def list_saga_events(
    conversation_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, object]:
    backend = _conversation_store._backend
    if backend is None:
        return {"items": [], "error": "mysql_backend_not_configured"}
    events = backend.list_saga_events(
        conversation_id=conversation_id,
        status=status,
        limit=limit,
    )
    return {"items": events, "total": len(events)}


@router.get("/admin/saga/summary")
def saga_summary() -> dict[str, object]:
    backend = _conversation_store._backend
    if backend is None:
        return {"error": "mysql_backend_not_configured"}
    recent_failures = backend.list_saga_events(status="failed", limit=10)
    recent_compensations = backend.list_saga_events(status="compensated", limit=10)
    recent_compensation_failures = backend.list_saga_events(status="compensation_failed", limit=10)
    return {
        "recent_failures": recent_failures,
        "recent_compensations": recent_compensations,
        "recent_compensation_failures": recent_compensation_failures,
    }


@router.get("/metrics")
def metrics():
    from fastapi.responses import Response

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
