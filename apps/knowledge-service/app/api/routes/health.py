from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.dependencies import build_trace_context
from app.core.metrics import update_health_metrics_from_payload
from app.models.common import ApiEnvelope
from app.services.health import get_health_service

router = APIRouter()


@router.get("/healthz", response_model=ApiEnvelope)
def healthz(request: Request) -> ApiEnvelope[dict]:
    trace = build_trace_context(request)
    payload = get_health_service().build_payload()
    update_health_metrics_from_payload(payload)
    return ApiEnvelope(
        data=payload,
        requestId=trace.request_id,
        trace=trace,
    )


@router.get("/metrics")
def metrics() -> PlainTextResponse:
    update_health_metrics_from_payload(get_health_service().build_payload())
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
