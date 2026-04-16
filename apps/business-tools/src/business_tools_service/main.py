from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, Request

from business_tools import configure_idempotency_store, configure_query_cache
from business_tools_service.api.routes.health import router as health_router
from business_tools_service.api.routes.tools import router as tools_router
from business_tools_service.core.config import get_settings
from business_tools_service.core.logging import configure_logging

settings = get_settings()
configure_idempotency_store(
    persistence_path=settings.idempotency_store_path,
    redis_url=settings.redis_url,
    redis_namespace=f"{settings.redis_namespace}:idempotency",
)
configure_query_cache(
    enabled=settings.tool_query_cache_enabled,
    ttl_cap_seconds=settings.tool_query_cache_ttl_cap_seconds,
    persistence_path=settings.query_cache_store_path,
    redis_url=settings.redis_url,
    redis_namespace=f"{settings.redis_namespace}:query-cache",
)
configure_logging(settings.log_level)

app = FastAPI(
    title="SmartCloud-X Business Tools Service",
    version=settings.app_version,
    description="Starter business-tools internal service for tool-hub integration.",
)
app.include_router(health_router)
app.include_router(tools_router, prefix=settings.internal_api_prefix)


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
