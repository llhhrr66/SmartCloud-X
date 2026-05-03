from __future__ import annotations

from time import perf_counter
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.core.config import get_settings
from app.core.metrics import (
    RESEARCH_READINESS_STATE,
    RESEARCH_REQUEST_DURATION_SECONDS,
    RESEARCH_REQUESTS_TOTAL,
    RESEARCH_UPSTREAM_ERRORS_TOTAL,
)
from app.core.tracing import annotate_current_span, start_span
from app.dependencies import build_trace_context, require_user_permissions
from app.models import (
    CanonicalSuccessEnvelope,
    CreateResearchTaskRequest,
    CurrentUserContext,
    ResearchCapabilitiesResponseData,
    ResearchTask,
    ResearchTaskRecord,
    ResearchTaskResultData,
    ResearchTaskStatusData,
    ServiceError,
    now_timestamp_ms,
)
from app.mongo_runtime import get_research_mongo_runtime
from app.services.report_renderer import render_research_artifact
from app.services.research_agent import describe_research_agent_configuration, get_research_agent_provider
from app.store import get_research_store


health_router = APIRouter(tags=["health"])
router = APIRouter(tags=["research"])


@health_router.get("/healthz")
def healthz() -> dict[str, Any]:
    settings = get_settings()
    using_sqlite = settings.database_url.startswith("sqlite")
    return {
        "status": "ok",
        "service": "research-service",
        "runtime_mode": "local-fallback" if using_sqlite else "shared-backend",
        "backends": {
            "mysql": _backend_record(
                kind="mysql",
                role="primary",
                configured=not using_sqlite,
                active=not using_sqlite,
                restart_durable=not using_sqlite,
                required_for_release=True,
                evidence="engine-dialect" if not using_sqlite else "config-only",
                fallback="sqlite://local-fallback",
                notes=None if not using_sqlite else "set SMARTCLOUD_MYSQL_DSN or RESEARCH_SERVICE_DATABASE_URL to promote the shared backend",
            ),
            "sqlite": _backend_record(
                kind="sqlite",
                role="fallback",
                configured=using_sqlite,
                active=using_sqlite,
                restart_durable=using_sqlite,
                required_for_release=False,
                evidence="engine-dialect" if using_sqlite else "config-only",
                fallback=str(settings.bootstrap_path) if settings.bootstrap_path else None,
                notes="local/test compatibility database derived from owner config",
            ),
            "redis": _backend_record(
                kind="redis",
                role="optional",
                configured=bool(settings.redis_url),
                active=False,
                restart_durable=False,
                required_for_release=False,
                evidence="config-only",
                fallback=None,
                notes="declared config only; current research runtime persists tasks and idempotency in database tables",
            ),
            "mongodb": _backend_record(
                kind="mongodb",
                role="optional",
                configured=bool(settings.mongodb_uri),
                active=getattr(get_research_mongo_runtime(), "enabled", False),
                restart_durable=bool(settings.mongodb_uri),
                required_for_release=False,
                evidence="document-store" if settings.mongodb_uri else "config-only",
                fallback="inline placeholder result payload",
                notes="research report documents live in MongoDB when SMARTCLOUD_MONGODB_URI is configured",
            ),
        },
    }


@health_router.get("/readyz")
async def readyz() -> JSONResponse:
    settings = get_settings()
    runtime_mode = "local-fallback" if settings.database_url.startswith("sqlite") else "shared-backend"
    store_ready = True
    store_error = None
    try:
        with get_research_store()._session() as session:
            session.execute(__import__("sqlalchemy").text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        store_ready = False
        store_error = f"{exc.__class__.__name__}: {exc}"
        RESEARCH_UPSTREAM_ERRORS_TOTAL.labels(backend="database", error_type="connectivity").inc()
    mongo_readiness = await get_research_mongo_runtime().readiness()
    runtime = {
        "database": {
            "ready": store_ready,
            "configured": bool(settings.database_url),
            "error": store_error,
        },
        "mongodb": {
            "ready": mongo_readiness.ready,
            **mongo_readiness.details,
        },
    }
    not_ready_components = [name for name, component in runtime.items() if not component.get("ready")]
    ready = not not_ready_components
    RESEARCH_READINESS_STATE.set(1 if ready else 0)
    payload = {
        "status": "ready" if ready else "degraded",
        "service": "research-service",
        "runtime_mode": runtime_mode,
        "ready": ready,
        "checks": runtime,
        "not_ready_components": not_ready_components,
        "runtime": runtime,
    }
    return JSONResponse(status_code=200, content=payload)


@health_router.get("/metrics")
def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/research/tasks")
def list_research_tasks(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="page_size"),
    sort_by: str = Query(default="updated_at", alias="sort_by"),
    sort_order: str = Query(default="desc", alias="sort_order"),
    status: str | None = Query(default=None),
    user: CurrentUserContext = Depends(require_user_permissions("user:research.read")),
) -> JSONResponse:
    return _route_wrapper(
        request,
        operation="list_tasks",
        depth="na",
        func=lambda: _canonical_success(
            build_trace_context(request).request_id or "",
            get_research_store()
            .list_tasks(
                user_id=user.user_id,
                tenant_id=user.tenant_id,
                page=page,
                page_size=page_size,
                sort_by=sort_by,
                sort_order=sort_order,
                status=status,
            )
            .model_dump(mode="json"),
        ),
    )


@router.post("/research/tasks")
async def create_research_task(
    payload: CreateResearchTaskRequest,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:research.write")),
) -> JSONResponse:
    trace = build_trace_context(request)
    store = get_research_store()
    started = perf_counter()
    with start_span(
        "research.task.create",
        operation="task_create",
        depth=payload.depth,
        output_format=payload.output_format,
        user_id=user.user_id,
        tenant_id=user.tenant_id,
    ):
        data = store.create_task(
            user_id=user.user_id,
            tenant_id=user.tenant_id,
            payload=payload,
            idempotency_key=_require_idempotency_key(request),
        )
        task_record = store.get_task_record(user_id=user.user_id, tenant_id=user.tenant_id, task_id=data.task_id)
        if task_record is None:
            raise ServiceError(404, 4040001, "research task was not found after creation")
        if task_record.status == "queued":
            try:
                task_record = await _dispatch_agent(task_record)
            except Exception as exc:  # noqa: BLE001
                task_record = store.mark_task_failed(
                    user_id=user.user_id,
                    tenant_id=user.tenant_id,
                    task_id=data.task_id,
                    error_message=f"research agent execution failed: {exc}",
                )
                RESEARCH_UPSTREAM_ERRORS_TOTAL.labels(backend="research-agent", error_type=exc.__class__.__name__).inc()
        result = await _build_research_result(task_record.to_public(), task_record)
        annotate_current_span(
            task_id=data.task_id,
            operation="task_create",
            status=task_record.status,
            depth=payload.depth,
            output_format=payload.output_format,
            user_id=user.user_id,
            tenant_id=user.tenant_id,
        )
    RESEARCH_REQUEST_DURATION_SECONDS.labels(operation="create_task").observe(perf_counter() - started)
    RESEARCH_REQUESTS_TOTAL.labels(operation="create_task", status=task_record.status, depth=payload.depth).inc()
    response_payload = data.model_dump(mode="json")
    response_payload["status"] = task_record.status
    return _canonical_success(trace.request_id or "", response_payload, message="accepted", status_code=202)


@router.get("/research/tasks/{task_id}")
def get_research_task(
    task_id: str,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:research.read")),
) -> JSONResponse:
    return _route_wrapper(
        request,
        operation="get_task",
        depth="na",
        func=lambda: _canonical_success(
            build_trace_context(request).request_id or "",
            _get_owned_task(user.user_id, user.tenant_id, task_id).model_dump(mode="json"),
            message="success",
        ),
        task_id=task_id,
        user_id=user.user_id,
        tenant_id=user.tenant_id,
    )


@router.get("/research/tasks/{task_id}/status")
def get_research_task_status(
    task_id: str,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:research.read")),
) -> JSONResponse:
    def _build() -> JSONResponse:
        task = _get_owned_task(user.user_id, user.tenant_id, task_id)
        status_data = ResearchTaskStatusData(
            task_id=task.task_id,
            status=task.status,
            progress=task.progress,
            created_at=task.created_at,
            updated_at=task.updated_at,
            started_at=task.started_at,
            finished_at=task.finished_at,
            result_ready=bool(task.report_file_id and task.status == "completed"),
            report_file_id=task.report_file_id,
        )
        return _canonical_success(build_trace_context(request).request_id or "", status_data.model_dump(mode="json"), message="success")

    return _route_wrapper(
        request,
        operation="get_task_status",
        depth="na",
        func=_build,
        task_id=task_id,
        user_id=user.user_id,
        tenant_id=user.tenant_id,
    )


@router.get("/research/tasks/{task_id}/result")
async def get_research_task_result(
    task_id: str,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:research.read")),
) -> JSONResponse:
    trace = build_trace_context(request)
    started = perf_counter()
    with start_span("research.task.result", operation="result_generation", task_id=task_id, user_id=user.user_id, tenant_id=user.tenant_id):
        task = _get_owned_task(user.user_id, user.tenant_id, task_id)
        task_record = get_research_store().get_task_record(user_id=user.user_id, tenant_id=user.tenant_id, task_id=task_id)
        result = await _build_research_result(task, task_record)
        annotate_current_span(status=task.status, depth=task.depth, output_format=task.output_format)
    RESEARCH_REQUEST_DURATION_SECONDS.labels(operation="get_task_result").observe(perf_counter() - started)
    RESEARCH_REQUESTS_TOTAL.labels(operation="get_task_result", status=task.status, depth=task.depth).inc()
    return _canonical_success(trace.request_id or "", result.model_dump(mode="json"), message="success")


@router.get("/research/tasks/{task_id}/report", include_in_schema=False)
async def get_research_task_report(
    task_id: str,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:research.read")),
) -> JSONResponse:
    trace = build_trace_context(request)
    task = _get_owned_task(user.user_id, user.tenant_id, task_id)
    task_record = get_research_store().get_task_record(user_id=user.user_id, tenant_id=user.tenant_id, task_id=task_id)
    result = await _build_research_result(task, task_record)
    return _canonical_success(trace.request_id or "", result.model_dump(mode="json"), message="success")


@router.get("/research/capabilities")
def get_research_capabilities(
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:research.read")),
) -> JSONResponse:
    return _route_wrapper(
        request,
        operation="capabilities",
        depth="na",
        func=lambda: _canonical_success(
            build_trace_context(request).request_id or "",
            ResearchCapabilitiesResponseData.model_validate(describe_research_agent_configuration()).model_dump(mode="json"),
        ),
        user_id=user.user_id,
        tenant_id=user.tenant_id,
    )


@router.post("/research/tasks/{task_id}/cancel")
def cancel_research_task(
    task_id: str,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:research.write")),
) -> JSONResponse:
    return _route_wrapper(
        request,
        operation="cancel_task",
        depth="na",
        func=lambda: _canonical_success(
            build_trace_context(request).request_id or "",
            get_research_store().cancel_task(user_id=user.user_id, tenant_id=user.tenant_id, task_id=task_id).model_dump(mode="json"),
            message="success",
        ),
        task_id=task_id,
        user_id=user.user_id,
        tenant_id=user.tenant_id,
    )


@router.delete("/research/tasks/{task_id}")
def delete_research_task(
    task_id: str,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:research.write")),
) -> JSONResponse:
    return _route_wrapper(
        request,
        operation="delete_task",
        depth="na",
        func=lambda: _canonical_success(
            build_trace_context(request).request_id or "",
            get_research_store().archive_task(user_id=user.user_id, tenant_id=user.tenant_id, task_id=task_id).model_dump(mode="json"),
            message="success",
        ),
        task_id=task_id,
        user_id=user.user_id,
        tenant_id=user.tenant_id,
    )


def _route_wrapper(
    request: Request,
    *,
    operation: str,
    depth: str,
    func,
    **attributes,
):
    started = perf_counter()
    with start_span(f"research.{operation}", operation=operation, depth=depth, **attributes):
        response = func()
        status_text = "ok" if response.status_code < 400 else "error"
        annotate_current_span(status=status_text, **attributes)
    RESEARCH_REQUEST_DURATION_SECONDS.labels(operation=operation).observe(perf_counter() - started)
    RESEARCH_REQUESTS_TOTAL.labels(operation=operation, status=status_text, depth=depth).inc()
    return response


def _canonical_success(request_id: str, data: dict, *, message: str = "ok", status_code: int = 200) -> JSONResponse:
    payload = CanonicalSuccessEnvelope(
        message=message,
        data=data,
        request_id=request_id,
        timestamp=now_timestamp_ms(),
    ).model_dump(mode="json")
    return JSONResponse(status_code=status_code, content=payload)


def _require_idempotency_key(request: Request) -> str:
    idempotency_key = (request.headers.get("Idempotency-Key") or "").strip()
    if not idempotency_key:
        raise ServiceError(
            400,
            4001001,
            "Idempotency-Key header is required",
            field="Idempotency-Key",
            public=True,
        )
    return idempotency_key


def _get_owned_task(user_id: str, tenant_id: str, task_id: str) -> ResearchTask:
    task = get_research_store().get_task(user_id=user_id, tenant_id=tenant_id, task_id=task_id)
    if task is None:
        raise ServiceError(404, 4040001, "research task not found", public=True)
    return task


async def _dispatch_agent(task: ResearchTaskRecord) -> ResearchTaskRecord:
    provider = get_research_agent_provider()
    return await provider.execute(task)


async def _build_research_result(task: ResearchTask, task_record: ResearchTaskRecord | None) -> ResearchTaskResultData:
    mongo_runtime = get_research_mongo_runtime()
    if getattr(mongo_runtime, "enabled", False):
        return await mongo_runtime.upsert_report(
            task,
            report_download_base_url=get_settings().report_download_base_url,
        )
    if task_record is not None and getattr(task_record, "agent_result", None):
        rendered = render_research_artifact(task_record.to_public(), task_record.agent_result)
        return ResearchTaskResultData(
            task_id=task.task_id,
            status=task.status,
            result_ready=bool(task.report_file_id and task.status == "completed"),
            output_format=task.output_format,
            summary=task.summary,
            report_file_id=rendered.report_file_id,
            download_url=rendered.download_url,
            preview_text=rendered.preview_text,
            citations=[citation.url for citation in rendered.citations],
            generated_at=task.finished_at,
            sections=list(rendered.sections),
            metadata=dict(rendered.metadata),
        )
    return await mongo_runtime.upsert_report(
        task,
        report_download_base_url=get_settings().report_download_base_url,
    )


def _backend_record(
    *,
    kind: str,
    role: str,
    configured: bool,
    active: bool,
    restart_durable: bool,
    required_for_release: bool,
    evidence: str,
    fallback: str | None,
    notes: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": kind,
        "role": role,
        "configured": configured,
        "active": active,
        "restart_durable": restart_durable,
        "required_for_release": required_for_release,
        "evidence": evidence,
        "fallback": fallback,
    }
    if notes:
        payload["notes"] = notes
    return payload
