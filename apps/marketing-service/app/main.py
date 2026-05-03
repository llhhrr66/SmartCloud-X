from __future__ import annotations

from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.logging import configure_logging, logger
from app.core.telemetry import attach_request_context, configure_tracing, detach_request_context, reset_tracing, set_current_trace_id, should_trace_path
from app.dependencies import build_trace_context
from app.mongo_runtime import DisabledMarketingMongoRuntime, MarketingMongoRuntime, set_marketing_mongo_runtime
from app.models import CanonicalErrorEnvelope, ServiceError, now_timestamp_ms
from app.routes import health_router, router

settings = get_settings()
configure_logging(settings.log_level)
reset_tracing()
configure_tracing(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    runtime = DisabledMarketingMongoRuntime()
    if settings.mongodb_uri:
        runtime = await MarketingMongoRuntime.connect(settings)
    set_marketing_mongo_runtime(runtime)
    try:
        yield
    finally:
        runtime.close()
        set_marketing_mongo_runtime(None)


app = FastAPI(title='SmartCloud-X Marketing Service', version=settings.app_version, description='Database-backed marketing service baseline with campaign browsing, copy generation, promotion links, and object-storage-friendly poster placeholders.', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_allowed_origins, allow_credentials=False, allow_methods=['*'], allow_headers=['*'])


@app.middleware('http')
async def add_standard_headers(request: Request, call_next):
    trace = build_trace_context(request)
    started = perf_counter()
    if should_trace_path(request.url.path):
        attach_request_context(request)
    set_current_trace_id(trace.trace_id)
    try:
        response = await call_next(request)
    finally:
        if should_trace_path(request.url.path):
            detach_request_context(request)
    response.headers[settings.request_id_header] = trace.request_id or ''
    response.headers[settings.trace_id_header] = trace.trace_id or ''
    response.headers['X-App-Name'] = settings.app_name
    response.headers['X-App-Version'] = settings.app_version
    response.headers['X-Response-Time'] = f'{(perf_counter() - started) * 1000:.2f}ms'
    return response


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    trace = build_trace_context(request)
    payload = CanonicalErrorEnvelope(code=exc.code, message=exc.message, request_id=trace.request_id or '', timestamp=now_timestamp_ms(), error=None if not any([exc.error_type, exc.field, exc.details]) else {'type': exc.error_type, 'field': exc.field, 'details': exc.details}).model_dump(mode='json')
    return JSONResponse(status_code=exc.status_code, content=payload)


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    trace = build_trace_context(request)
    first_error = exc.errors()[0] if exc.errors() else {}
    field = '.'.join(str(item) for item in first_error.get('loc', [])[1:]) or None
    payload = CanonicalErrorEnvelope(code=4001001, message='request validation failed', request_id=trace.request_id or '', timestamp=now_timestamp_ms(), error={'type': 'validation_error', 'field': field, 'details': {'errors': exc.errors()}}).model_dump(mode='json')
    return JSONResponse(status_code=400, content=payload)


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    trace = build_trace_context(request)
    logger.exception('marketing.unexpected_error', extra={'request_id': trace.request_id, 'trace_id': trace.trace_id, 'path': request.url.path})
    payload = CanonicalErrorEnvelope(code=5000000, message='internal server error', request_id=trace.request_id or '', timestamp=now_timestamp_ms()).model_dump(mode='json')
    return JSONResponse(status_code=500, content=payload)


app.include_router(health_router)
app.include_router(router, prefix=settings.api_prefix)
