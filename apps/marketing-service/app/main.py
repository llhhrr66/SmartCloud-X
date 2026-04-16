from __future__ import annotations

from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.dependencies import build_trace_context
from app.models import CanonicalErrorEnvelope, ServiceError, now_timestamp_ms
from app.routes import health_router, router

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(
    title="SmartCloud-X Marketing Service",
    version=settings.app_version,
    description="Database-backed marketing service baseline with campaign browsing, copy generation, promotion links, and object-storage-friendly poster placeholders.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_standard_headers(request: Request, call_next):
    trace = build_trace_context(request)
    started = perf_counter()
    response = await call_next(request)
    response.headers[settings.request_id_header] = trace.request_id or ""
    response.headers[settings.trace_id_header] = trace.trace_id or ""
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
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:  # pragma: no cover - fallback
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
