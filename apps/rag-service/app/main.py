from datetime import UTC, datetime
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.dependencies import build_trace_context
from app.api.routes.admin import router as admin_router
from app.api.routes.health import router as health_router
from app.api.routes.rag import router as rag_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.tracing import annotate_current_span, configure_tracing
from app.models.admin import CanonicalErrorDetail, CanonicalErrorEnvelope

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(
    title="SmartCloud-X RAG Service",
    version=settings.app_version,
    description="Baseline retrieval and answer composition service.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_standard_response_headers(request: Request, call_next):
    trace = build_trace_context(request)
    annotate_current_span(
        smartcloud_request_id=trace.request_id,
        smartcloud_trace_id=trace.trace_id,
        smartcloud_conversation_id=trace.conversation_id,
        smartcloud_tenant_id=trace.tenant_id,
        smartcloud_caller_service=trace.caller_service,
    )
    started = perf_counter()
    response = await call_next(request)
    response_time_ms = round((perf_counter() - started) * 1000, 2)
    response.headers[settings.request_id_header] = trace.request_id or ""
    response.headers[settings.trace_id_header] = trace.trace_id or ""
    response.headers["X-App-Name"] = settings.app_name
    response.headers["X-App-Version"] = settings.app_version
    response.headers["X-Response-Time"] = f"{response_time_ms:.2f}ms"
    annotate_current_span(
        smartcloud_response_time_ms=response_time_ms,
        smartcloud_http_path=request.url.path,
        smartcloud_http_method=request.method,
        smartcloud_http_status_code=response.status_code,
    )
    return response


configure_tracing(app, settings)


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(request: Request, exc: RequestValidationError):
    if not request.url.path.startswith("/api/v1/admin/"):
        return await request_validation_exception_handler(request, exc)

    trace = build_trace_context(request)
    first_error = exc.errors()[0] if exc.errors() else {}
    location = first_error.get("loc", [])
    field = ".".join(str(item) for item in location[1:]) if len(location) > 1 else None
    return JSONResponse(
        status_code=400,
        content=CanonicalErrorEnvelope(
            code=4001001,
            message="admin request validation failed",
            request_id=trace.request_id or "",
            timestamp=int(datetime.now(UTC).timestamp() * 1000),
            error=CanonicalErrorDetail(
                type="validation_error",
                field=field,
                reason=first_error.get("msg", "validation failed"),
                details={"errors": exc.errors()},
            ),
        ).model_dump(mode="json"),
    )


app.include_router(health_router)
app.include_router(rag_router, prefix=settings.api_prefix)
app.include_router(admin_router, prefix="/api/v1/admin")
