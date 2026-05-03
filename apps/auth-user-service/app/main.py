from __future__ import annotations

from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.dependencies import build_trace_context
from app.models import ApiEnvelope, CanonicalErrorEnvelope, ErrorInfo, ServiceError, TraceContext, now_timestamp_ms
from app.routes import admin_router, health_router, internal_router, router

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(
    title="SmartCloud-X Auth User Service",
    version=settings.app_version,
    description="Database-backed auth service baseline for user login/profile flows, admin auth bootstrap, and internal permission checks.",
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


@app.exception_handler(HTTPException)
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    trace = build_trace_context(request)
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    code = detail.get("code") if isinstance(detail.get("code"), int) else exc.status_code * 1000
    message = detail.get("message") if isinstance(detail.get("message"), str) else str(exc.detail)
    error = detail.get("error") if isinstance(detail.get("error"), dict) else None
    payload = CanonicalErrorEnvelope(
        code=code,
        message=message,
        request_id=trace.request_id or "",
        timestamp=now_timestamp_ms(),
        error=error,
    ).model_dump(mode="json")
    return JSONResponse(status_code=exc.status_code, content=payload)


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    trace = build_trace_context(request)
    if exc.public:
        payload = CanonicalErrorEnvelope(
            code=int(exc.code),
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

    payload = ApiEnvelope(
        success=False,
        requestId=trace.request_id,
        trace=trace,
        error=ErrorInfo(code=str(exc.code), message=exc.message, details=exc.details, retryable=exc.retryable),
    ).model_dump(mode="json", by_alias=True)
    return JSONResponse(status_code=exc.status_code, content=payload)


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    trace = build_trace_context(request)
    first_error = exc.errors()[0] if exc.errors() else {}
    loc_items = list(first_error.get("loc", []))
    field = None
    if len(loc_items) >= 2 and str(loc_items[0]) == "body":
        field = ".".join(str(item) for item in loc_items[1:]) or None
    if field is None:
        ctx = first_error.get("ctx") if isinstance(first_error.get("ctx"), dict) else {}
        if isinstance(ctx, dict):
            source = ctx.get("field_name")
            if isinstance(source, str) and source:
                field = source
            elif loc_items == ["body"]:
                raw_error = str(ctx.get("error") or "")
                field_match = __import__("re").match(
                    r"^(?P<field>[A-Za-z_][A-Za-z0-9_]*) (?:cannot be null|cannot be blank|must .+)$",
                    raw_error,
                )
                if field_match is not None:
                    field = field_match.group("field")
    normalized_errors = []
    for item in exc.errors():
        error_item = dict(item)
        ctx = error_item.get("ctx")
        if isinstance(ctx, dict):
            error_item["ctx"] = {
                key: str(value) if isinstance(value, Exception) else value
                for key, value in ctx.items()
            }
        normalized_errors.append(error_item)
    if field is None:
        for error_item in normalized_errors:
            ctx = error_item.get("ctx") if isinstance(error_item.get("ctx"), dict) else {}
            loc_items = list(error_item.get("loc", []))
            if len(loc_items) >= 2 and str(loc_items[0]) == "body":
                field = ".".join(str(item) for item in loc_items[1:]) or None
                if field:
                    break
            raw_error = str(ctx.get("error") or "") if isinstance(ctx, dict) else ""
            field_match = __import__("re").match(
                r"^(?P<field>[A-Za-z_][A-Za-z0-9_]*) (?:cannot be null|cannot be blank|must be .+)$",
                raw_error,
            )
            if field_match is not None:
                field = field_match.group("field")
                break
    if request.url.path.startswith(settings.internal_api_prefix):
        payload = ApiEnvelope(
            success=False,
            requestId=trace.request_id,
            trace=trace,
            error=ErrorInfo(
                code="VALIDATION_ERROR",
                message="request validation failed",
                details={"errors": normalized_errors},
            ),
        ).model_dump(mode="json", by_alias=True)
        return JSONResponse(status_code=400, content=payload)

    payload = CanonicalErrorEnvelope(
        code=4001001,
        message="request validation failed",
        request_id=trace.request_id or "",
        timestamp=now_timestamp_ms(),
        error={
            "type": "validation_error",
            "field": field,
            "details": {"errors": normalized_errors},
        },
    ).model_dump(mode="json")
    return JSONResponse(status_code=400, content=payload)


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:  # pragma: no cover - fallback
    trace = build_trace_context(request)
    if request.url.path.startswith(settings.internal_api_prefix):
        payload = ApiEnvelope(
            success=False,
            requestId=trace.request_id,
            trace=trace,
            error=ErrorInfo(code="INTERNAL_SERVER_ERROR", message=str(exc)),
        ).model_dump(mode="json", by_alias=True)
        return JSONResponse(status_code=500, content=payload)
    payload = CanonicalErrorEnvelope(
        code=5000000,
        message="internal server error",
        request_id=trace.request_id or "",
        timestamp=now_timestamp_ms(),
    ).model_dump(mode="json")
    return JSONResponse(status_code=500, content=payload)


app.include_router(health_router)
app.include_router(router, prefix=settings.api_prefix)
app.include_router(admin_router, prefix=settings.api_prefix)
app.include_router(internal_router, prefix=settings.internal_api_prefix)
