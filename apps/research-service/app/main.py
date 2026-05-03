from __future__ import annotations

from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.tracing import configure_tracing
from app.dependencies import build_trace_context
from app.mongo_runtime import DisabledResearchMongoRuntime, ResearchMongoRuntime, set_research_mongo_runtime
from app.models import CanonicalErrorEnvelope, ServiceError, now_timestamp_ms
from app.routes import health_router, router

settings = get_settings()
configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(_: FastAPI):
    runtime = DisabledResearchMongoRuntime()
    if settings.mongodb_uri:
        runtime = await ResearchMongoRuntime.connect(settings)
    set_research_mongo_runtime(runtime)
    try:
        yield
    finally:
        runtime.close()
        set_research_mongo_runtime(None)


app = FastAPI(
    title="SmartCloud-X Research Service",
    version=settings.app_version,
    description="Database-backed research task service with canonical external envelopes and persisted results.",
    lifespan=lifespan,
)
configure_tracing(app, settings)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _build_traceparent_header(trace_id: str | None) -> str | None:
    if not trace_id:
        return None
    normalized_trace_id = trace_id.strip().lower()
    if len(normalized_trace_id) != 32:
        return None
    if any(character not in "0123456789abcdef" for character in normalized_trace_id):
        return None
    if normalized_trace_id == "0" * 32:
        return None
    span = trace.get_current_span()
    span_context = span.get_span_context() if span is not None else None
    span_id = None
    trace_flags = "01"
    if span_context is not None and span_context.is_valid:
        span_id = format(span_context.span_id, "016x")
        trace_flags = format(int(span_context.trace_flags), "02x")
    if not span_id or span_id == "0" * 16:
        span_id = "0" * 16
    return f"00-{normalized_trace_id}-{span_id}-{trace_flags}"


@app.middleware("http")
async def add_standard_headers(request: Request, call_next):
    trace = build_trace_context(request)
    started = perf_counter()
    response = await call_next(request)
    response.headers[settings.request_id_header] = trace.request_id or ""
    response.headers[settings.trace_id_header] = trace.trace_id or ""
    if settings.trace_enabled:
        carrier: dict[str, str] = {}
        TraceContextTextMapPropagator().inject(carrier)
        response_traceparent = carrier.get("traceparent") or _build_traceparent_header(trace.trace_id)
        if response_traceparent:
            response.headers["traceparent"] = response_traceparent
    response.headers["X-App-Name"] = settings.app_name
    response.headers["X-App-Version"] = settings.app_version
    response.headers["X-Response-Time"] = f"{(perf_counter() - started) * 1000:.2f}ms"
    return response


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    trace = build_trace_context(request)
    payload = CanonicalErrorEnvelope(
        code=exc.code,
        message=exc.message,
        request_id=trace.request_id or "",
        timestamp=now_timestamp_ms(),
        error=None
        if not any([exc.error_type, exc.field, exc.details])
        else {
            "type": exc.error_type,
            "field": exc.field,
            "details": exc.details,
        },
    ).model_dump(mode="json")
    return JSONResponse(status_code=exc.status_code, content=payload)


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    trace = build_trace_context(request)
    first_error = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(item) for item in first_error.get("loc", [])[1:]) or None
    payload = CanonicalErrorEnvelope(
        code=4001001,
        message="request validation failed",
        request_id=trace.request_id or "",
        timestamp=now_timestamp_ms(),
        error={
            "type": "validation_error",
            "field": field,
            "details": {"errors": exc.errors()},
        },
    ).model_dump(mode="json")
    return JSONResponse(status_code=400, content=payload)


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:  # pragma: no cover
    trace = build_trace_context(request)
    payload = CanonicalErrorEnvelope(
        code=5000000,
        message="internal server error",
        request_id=trace.request_id or "",
        timestamp=now_timestamp_ms(),
    ).model_dump(mode="json")
    return JSONResponse(status_code=500, content=payload)


app.include_router(health_router)
app.include_router(router, prefix=settings.api_prefix)
