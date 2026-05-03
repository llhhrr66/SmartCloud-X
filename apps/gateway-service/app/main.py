from __future__ import annotations

import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.common import canonical_error
from app.api.routes.admin import router as admin_router
from app.api.routes.auth import router as auth_router
from app.api.routes.business import router as business_router
from app.api.routes.chat import router as chat_router
from app.api.routes.health import router as health_router
from app.api.routes.marketing import router as marketing_router
from app.api.routes.owner_local import router as owner_local_router
from app.core.config import GatewaySettings
from app.core.upstreams import UpstreamDefinition, build_upstream_registry
from app.middleware.rate_limit import SimpleRateLimiter
from app.services.http import UpstreamHttpService, decode_header_value
from app.services.logging import configure_logging, log_event
from app.services.store import GatewayStore


@dataclass(slots=True)
class GatewayServices:
    settings: GatewaySettings
    registry: dict[str, UpstreamDefinition]
    http: UpstreamHttpService
    store: GatewayStore
    rate_limiter: SimpleRateLimiter


def create_app(
    *,
    settings: GatewaySettings | None = None,
    upstream_transports: dict[str, httpx.BaseTransport | httpx.AsyncBaseTransport] | None = None,
) -> FastAPI:
    configure_logging()
    gateway_settings = settings or GatewaySettings.from_env()
    registry = build_upstream_registry(gateway_settings)
    services = GatewayServices(
        settings=gateway_settings,
        registry=registry,
        http=UpstreamHttpService(
            settings=gateway_settings,
            registry=registry,
            transports=upstream_transports,
        ),
        store=GatewayStore(
            gateway_settings.gateway_store_path,
            object_storage_base_url=gateway_settings.object_storage_base_url,
        ),
        rate_limiter=SimpleRateLimiter(
            request_limit=gateway_settings.rate_limit_requests,
            window_seconds=gateway_settings.rate_limit_window_seconds,
        ),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            await services.http.close()

    app = FastAPI(
        title="SmartCloud-X Gateway Service",
        version=gateway_settings.app_version,
        description="Unified API gateway / BFF for SmartCloud-X web-user and admin surfaces.",
        lifespan=lifespan,
    )
    app.state.gateway_services = services
    app.add_middleware(
        CORSMiddleware,
        allow_origins=gateway_settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request.state.request_id = request.headers.get(gateway_settings.request_id_header, uuid4().hex)
        request.state.trace_id = request.headers.get(gateway_settings.trace_id_header, request.state.request_id)
        request.state.tenant_id = request.headers.get(gateway_settings.tenant_id_header)
        request.state.subject_type = "anonymous"
        request.state.subject_id = None
        request.state.rate_limit_remaining = services.rate_limiter.request_limit
        request.state.rate_limit_limit = services.rate_limiter.request_limit
        request.state.rate_limit_bucket = "default"
        started = time.perf_counter()
        if request.method != "OPTIONS" and request.url.path not in {"/healthz", "/readyz"}:
            rate_key, bucket_name, limit = build_rate_limit_key(request, services.rate_limiter)
            decision = services.rate_limiter.allow_detailed(rate_key, limit=limit, bucket_name=bucket_name)
            request.state.rate_limit_remaining = decision.remaining
            request.state.rate_limit_limit = decision.limit
            request.state.rate_limit_bucket = decision.bucket_name
            if not decision.allowed:
                log_request_event(
                    request,
                    response_status=429,
                    latency_ms=elapsed_ms(started),
                    rate_limit_remaining=0,
                    blocked=True,
                )
                return canonical_error(
                    request_id=request.state.request_id,
                    status_code=429,
                    code=4290001,
                    message="rate limit exceeded",
                    headers={
                        "Retry-After": str(decision.retry_after_seconds),
                        "X-RateLimit-Limit": str(decision.limit),
                        "X-RateLimit-Remaining": "0",
                    },
                )
        response = await call_next(request)
        response.headers[gateway_settings.request_id_header] = request.state.request_id
        response.headers[gateway_settings.trace_id_header] = request.state.trace_id
        response.headers["X-App-Name"] = gateway_settings.app_name
        response.headers["X-App-Version"] = gateway_settings.app_version
        response.headers["X-Response-Time"] = f"{(time.perf_counter() - started) * 1000:.2f}ms"
        response.headers["X-RateLimit-Limit"] = str(getattr(request.state, "rate_limit_limit", services.rate_limiter.request_limit))
        response.headers["X-RateLimit-Remaining"] = str(
            getattr(request.state, "rate_limit_remaining", services.rate_limiter.request_limit)
        )
        log_request_event(
            request,
            response_status=response.status_code,
            latency_ms=elapsed_ms(started),
            rate_limit_remaining=getattr(request.state, "rate_limit_remaining", services.rate_limiter.request_limit),
        )
        return response

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(chat_router)
    app.include_router(marketing_router)
    app.include_router(admin_router)
    app.include_router(business_router)
    app.include_router(owner_local_router)
    return app


def build_rate_limit_key(request: Request, limiter: SimpleRateLimiter) -> tuple[str, str, int]:
    path = request.url.path
    if path.startswith("/api/v1/chat/completions"):
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            return f"user-token:{auth.removeprefix('Bearer ').removeprefix('bearer ').strip()}", "chat_sse", limiter.stream_request_limit
        tenant_id = request.headers.get("x-tenant-id") or "anonymous"
        client_host = request.client.host if request.client else "unknown"
        return f"chat-anon:{tenant_id}:{client_host}", "chat_sse", limiter.stream_request_limit

    subject_id = request.headers.get("x-user-id") or request.headers.get("x-subject-id")
    tenant_id = request.headers.get("x-tenant-id")
    client_host = request.client.host if request.client else "unknown"
    if subject_id and tenant_id:
        return f"tenant-user:{tenant_id}:{subject_id}", "authenticated", limiter.request_limit
    if tenant_id:
        return f"tenant:{tenant_id}:{path}", "tenant", limiter.request_limit
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
        return f"bearer:{token}", "authenticated", limiter.request_limit
    return f"anonymous:{client_host}:{path}", "anonymous", limiter.request_limit


def log_request_event(
    request: Request,
    *,
    response_status: int,
    latency_ms: int,
    rate_limit_remaining: int,
    blocked: bool = False,
) -> None:
    log_event(
        "request_completed" if not blocked else "request_rejected",
        request_id=request.state.request_id,
        trace_id=request.state.trace_id,
        method=request.method,
        path=request.url.path,
        subject_type=getattr(request.state, "subject_type", "anonymous"),
        subject_id=getattr(request.state, "subject_id", None),
        tenant_id=getattr(request.state, "tenant_id", None),
        response_status=response_status,
        latency_ms=latency_ms,
        rate_limit_remaining=rate_limit_remaining,
        rate_limit_bucket=getattr(request.state, "rate_limit_bucket", "default"),
    )


def elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


app = create_app()
