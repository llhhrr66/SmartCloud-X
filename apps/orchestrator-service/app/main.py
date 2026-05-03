from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.api.routes.a2a import jsonrpc_router as a2a_jsonrpc_router, router as a2a_router
from app.api.routes.admin import router as admin_router
from app.api.routes.llm_providers import router as llm_providers_router
from app.api.routes.health import router as health_router
from app.api.routes.orchestration import internal_router, router as orchestration_router
from app.core.config import get_settings
from app.core.langsmith import configure_langsmith_env
from app.core.logging import configure_logging
from app.services.mongo_runtime import (
    ConversationMongoRuntime,
    DisabledConversationMongoRuntime,
    UnavailableConversationMongoRuntime,
)

settings = get_settings()
configure_logging(settings.log_level)
configure_langsmith_env(settings)


async def _build_conversation_mongo_runtime(current_settings):
    if not current_settings.mongodb_uri:
        if current_settings.conversation_document_store_required:
            raise RuntimeError(
                "MongoDB conversation document store is required but SMARTCLOUD_MONGODB_URI is not configured."
            )
        return DisabledConversationMongoRuntime()
    try:
        return await ConversationMongoRuntime.connect(current_settings)
    except Exception as exc:
        if current_settings.conversation_document_store_required:
            raise
        return UnavailableConversationMongoRuntime(
            f"{exc.__class__.__name__}: {exc}",
            database_name=current_settings.mongodb_database,
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.api.routes.orchestration import _conversation_store

    runtime = await _build_conversation_mongo_runtime(settings)
    _conversation_store.configure_mongo_runtime(runtime)
    try:
        yield
    finally:
        runtime.close()
        _conversation_store.configure_mongo_runtime(None)

app = FastAPI(
    title="SmartCloud-X Orchestrator Service",
    version=settings.app_version,
    description="Baseline orchestrator for multi-agent routing, handoff planning, internal chat orchestration, and tool execution.",
    lifespan=lifespan,
)
app.include_router(health_router)
app.include_router(admin_router)
app.include_router(a2a_router)
app.include_router(a2a_jsonrpc_router, prefix=settings.api_prefix)
app.include_router(orchestration_router, prefix=settings.api_prefix)
app.include_router(orchestration_router, prefix=settings.legacy_api_prefix, include_in_schema=False)
app.include_router(internal_router, prefix=settings.internal_api_prefix, include_in_schema=False)
app.include_router(llm_providers_router, include_in_schema=False)


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
