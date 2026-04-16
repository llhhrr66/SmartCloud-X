from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, Request

from app.api.routes.health import router as health_router
from app.api.routes.orchestration import internal_router, router as orchestration_router
from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(
    title="SmartCloud-X Orchestrator Service",
    version=settings.app_version,
    description="Baseline orchestrator for multi-agent routing, handoff planning, internal chat orchestration, and tool execution.",
)
app.include_router(health_router)
app.include_router(orchestration_router, prefix=settings.api_prefix)
app.include_router(orchestration_router, prefix=settings.legacy_api_prefix, include_in_schema=False)
app.include_router(internal_router, prefix=settings.internal_api_prefix, include_in_schema=False)


@app.middleware("http")
async def response_headers_middleware(request: Request, call_next):
    started = time.perf_counter()
    request_id = request.headers.get(settings.request_id_header, uuid.uuid4().hex)
    trace_id = request.headers.get(settings.trace_id_header, request_id)
    response = await call_next(request)
    duration_ms = int((time.perf_counter() - started) * 1000)
    response.headers[settings.request_id_header] = request_id
    response.headers[settings.trace_id_header] = trace_id
    response.headers["X-App-Name"] = settings.app_name
    response.headers["X-App-Version"] = settings.app_version
    response.headers["X-Response-Time"] = f"{duration_ms}ms"
    return response
