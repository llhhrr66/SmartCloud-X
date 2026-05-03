from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.dependencies import build_trace_context
from app.core.metrics import update_health_metrics
from app.models.common import ApiEnvelope
from app.services.health import get_health_service

router = APIRouter()


@router.get("/healthz", response_model=ApiEnvelope)
async def healthz(request: Request) -> ApiEnvelope[dict]:
    trace = build_trace_context(request)
    payload = await get_health_service().build_payload()
    update_health_metrics(payload)
    return ApiEnvelope(
        data=payload,
        requestId=trace.request_id,
        trace=trace,
    )


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    _ = request.query_params
    status_code, payload = await get_health_service().build_readiness_payload()
    return JSONResponse(status_code=status_code, content=payload)


@router.get("/metrics")
async def metrics() -> PlainTextResponse:
    update_health_metrics(await get_health_service().build_payload())
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
