from __future__ import annotations

from time import perf_counter
from typing import Any, Callable

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.metrics import (
    ReadinessReport,
    export_metrics,
    marketing_celery_operations_total,
    marketing_readiness_state,
    marketing_upstream_errors_total,
    marketing_mongodb_operations_total,
    marketing_minio_operations_total,
    marketing_auth_validation_total,
    observe_duration,
    record_request,
)
from app.core.telemetry import set_span_attributes, should_trace_path, start_span
from app.dependencies import build_trace_context, require_user_permissions
from app.models import (
    AdminCampaignUpsertRequest,
    CanonicalSuccessEnvelope,
    CreatePosterTaskRequest,
    CurrentUserContext,
    MarketingCapabilitiesData,
    MarketingCopyRequest,
    MarketingCopyResult,
    PosterResultData,
    PosterTask,
    PromotionLinkRequest,
    PromotionLinkResult,
    ServiceError,
    now_timestamp_ms,
)
from app.mongo_runtime import get_marketing_mongo_runtime
from app.services.copy_generator import get_copy_generator
from app.services.poster_generator import get_poster_generator
from app.store import get_marketing_store
from app.tasks import generate_poster_task as generate_poster_task_job

health_router = APIRouter(tags=["health"])
router = APIRouter(tags=["marketing"])


@health_router.get("/healthz")
def healthz() -> dict[str, Any]:
    settings = get_settings()
    using_sqlite = settings.database_url.startswith("sqlite")
    minio_configured = all(
        [
            settings.minio_endpoint,
            settings.minio_bucket,
            settings.minio_access_key,
            settings.minio_secret_key,
        ]
    )
    celery_configured = bool(settings.celery_broker_url and settings.celery_result_backend)
    return {
        "status": "ok",
        "service": "marketing-service",
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
                notes=None if not using_sqlite else "set SMARTCLOUD_MYSQL_DSN or MARKETING_SERVICE_DATABASE_URL to promote the shared backend",
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
            "minio": _backend_record(
                kind="minio",
                role="raw-object",
                configured=minio_configured,
                active=minio_configured,
                restart_durable=minio_configured,
                required_for_release=False,
                evidence="config-selected" if minio_configured else "config-only",
                fallback=settings.poster_public_base_url,
                notes="poster artifacts use public URL fallback when object storage is unavailable",
            ),
            "redis": _backend_record(
                kind="redis",
                role="queue",
                configured=bool(settings.redis_url),
                active=celery_configured,
                restart_durable=celery_configured,
                required_for_release=False,
                evidence="celery-redis" if celery_configured else "config-only",
                fallback=None,
                notes="marketing poster generation enters Celery + Redis when broker/result backend are configured",
            ),
            "celery": _backend_record(
                kind="celery",
                role="queue",
                configured=celery_configured,
                active=celery_configured,
                restart_durable=celery_configured,
                required_for_release=False,
                evidence="celery-worker-configured" if celery_configured else "config-only",
                fallback="inline-auto-complete",
                notes="poster tasks auto-complete inline when queue is unavailable",
            ),
            "mongodb": _backend_record(
                kind="mongodb",
                role="document-store",
                configured=bool(settings.mongodb_uri),
                active=bool(settings.mongodb_uri),
                restart_durable=bool(settings.mongodb_uri),
                required_for_release=False,
                evidence="config-selected" if settings.mongodb_uri else "config-only",
                fallback="disabled-runtime",
                notes="poster result metadata falls back to response-only mode without MongoDB",
            ),
        },
    }


@health_router.get("/readyz")
async def readyz() -> JSONResponse:
    settings = get_settings()
    store = get_marketing_store(allow_fallback=True)
    mongo_runtime = get_marketing_mongo_runtime()
    runtime_mode = "local-fallback" if settings.database_url.startswith("sqlite") else "shared-backend"
    components = {
        "database": store.database_readiness(trace=False),
        "minio": store.minio_readiness(trace=False),
        "mongodb": await mongo_runtime.readiness(),
        "celery": store.celery_readiness(trace=False),
    }
    report = ReadinessReport(ready=all(component["ready"] for component in components.values()), components=components)
    marketing_readiness_state.set(1 if report.ready else 0)
    not_ready_components = [name for name, component in report.components.items() if not component.get("ready")]
    payload = {
        "status": "ready" if report.ready else "not_ready",
        "service": "marketing-service",
        "runtime_mode": runtime_mode,
        "ready": report.ready,
        "components": report.components,
        "not_ready_components": not_ready_components,
        "runtime": report.components,
    }
    status_code = 200 if report.ready else 503
    return JSONResponse(status_code=status_code, content=payload)


@health_router.get("/metrics")
def metrics() -> Response:
    payload, content_type = export_metrics()
    return Response(content=payload, media_type=content_type)


@router.get("/marketing/capabilities")
def marketing_capabilities(
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:marketing.read")),
) -> JSONResponse:
    trace = build_trace_context(request)
    data = MarketingCapabilitiesData(
        copy={"provider": get_copy_generator().capabilities().get("provider")},
        poster={"provider": get_poster_generator().capabilities().get("provider")},
    )
    data.copy_provider = get_copy_generator().capabilities()
    data.poster_provider = get_poster_generator().capabilities()
    return _canonical_success(trace.request_id or "", data.model_dump(mode="json", by_alias=True))


@router.get("/marketing/campaigns")
def list_campaigns(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="page_size"),
    sort_by: str = Query(default="start_at", alias="sort_by"),
    sort_order: str = Query(default="desc", alias="sort_order"),
    product_type: str | None = Query(default=None),
    status: str | None = Query(default="published"),
    user: CurrentUserContext = Depends(require_user_permissions("user:marketing.read")),
) -> JSONResponse:
    return _timed_call(
        request,
        "campaign_listing",
        "campaign",
        lambda trace: _canonical_success(
            trace.request_id or "",
            get_marketing_store(allow_fallback=True)
            .list_campaigns(
                page=page,
                page_size=page_size,
                sort_by=sort_by,
                sort_order=sort_order,
                status=status,
                product_type=product_type,
            )
            .model_dump(mode="json"),
        ),
        attributes_factory=lambda _trace: {"user_id": user.user_id, "tenant_id": user.tenant_id},
    )


@router.get("/marketing/admin/campaigns")
def list_admin_campaigns(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="page_size"),
    sort_by: str = Query(default="start_at", alias="sort_by"),
    sort_order: str = Query(default="desc", alias="sort_order"),
    status: str | None = Query(default=None),
    product_type: str | None = Query(default=None),
    user: CurrentUserContext = Depends(require_user_permissions("admin:marketing.read")),
) -> JSONResponse:
    return _timed_call(
        request,
        "admin_campaign_list",
        "campaign",
        lambda trace: _canonical_success(
            trace.request_id or "",
            get_marketing_store()
            .list_admin_campaigns(
                page=page,
                page_size=page_size,
                sort_by=sort_by,
                sort_order=sort_order,
                status=status,
                product_type=product_type,
            )
            .model_dump(mode="json"),
        ),
        attributes_factory=lambda _trace: {"user_id": user.user_id, "tenant_id": user.tenant_id},
    )


@router.get("/marketing/admin/campaigns/{campaign_id}")
def get_admin_campaign(
    campaign_id: str,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("admin:marketing.read")),
) -> JSONResponse:
    return _timed_call(
        request,
        "admin_campaign_detail",
        "campaign",
        lambda trace: _canonical_success(
            trace.request_id or "",
            get_marketing_store().get_admin_campaign(campaign_id).model_dump(mode="json"),
            message="success",
        ),
        attributes_factory=lambda _trace: {"user_id": user.user_id, "tenant_id": user.tenant_id, "campaign_id": campaign_id},
    )


@router.post("/marketing/admin/campaigns")
def create_admin_campaign(
    payload: AdminCampaignUpsertRequest,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("admin:marketing.write")),
) -> JSONResponse:
    return _timed_call(
        request,
        "admin_campaign_create",
        "campaign",
        lambda trace: _canonical_success(
            trace.request_id or "",
            get_marketing_store().create_admin_campaign(payload).model_dump(mode="json"),
            message="success",
        ),
    )


@router.put("/marketing/admin/campaigns/{campaign_id}")
def update_admin_campaign(
    campaign_id: str,
    payload: AdminCampaignUpsertRequest,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("admin:marketing.write")),
) -> JSONResponse:
    return _timed_call(
        request,
        "admin_campaign_update",
        "campaign",
        lambda trace: _canonical_success(
            trace.request_id or "",
            get_marketing_store().update_admin_campaign(campaign_id, payload).model_dump(mode="json"),
            message="success",
        ),
    )


@router.delete("/marketing/admin/campaigns/{campaign_id}")
def delete_admin_campaign(
    campaign_id: str,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("admin:marketing.write")),
) -> JSONResponse:
    return _timed_call(
        request,
        "admin_campaign_delete",
        "campaign",
        lambda trace: _delete_admin_campaign_response(trace, campaign_id),
    )


@router.patch("/marketing/admin/campaigns/{campaign_id}")
def patch_admin_campaign(
    campaign_id: str,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("admin:marketing.write")),
) -> JSONResponse:
    import json as _json

    body = _json.loads(request.body().decode("utf-8")) if request.headers.get("content-type", "").startswith("application/json") else {}
    return _timed_call(
        request,
        "admin_campaign_patch",
        "campaign",
        lambda trace: _canonical_success(
            trace.request_id or "",
            get_marketing_store().patch_admin_campaign(campaign_id, body).model_dump(mode="json"),
            message="success",
        ),
        attributes_factory=lambda _trace: {"user_id": user.user_id, "tenant_id": user.tenant_id, "campaign_id": campaign_id},
    )


@router.post("/marketing/copy/generate")
def generate_copy(
    payload: MarketingCopyRequest,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:marketing.write")),
) -> JSONResponse:
    return _timed_call(
        request,
        "copy_generation",
        "copy",
        lambda trace: _canonical_success(
            trace.request_id or "",
            get_marketing_store(allow_fallback=True).create_copy(user_id=user.user_id, tenant_id=user.tenant_id, payload=payload).model_dump(mode="json"),
            message="success",
        ),
        attributes_factory=lambda _trace: {"user_id": user.user_id, "tenant_id": user.tenant_id, "campaign_id": payload.campaign_id},
    )


@router.get("/marketing/copies")
def list_generated_copies(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="page_size"),
    sort_by: str = Query(default="created_at", alias="sort_by"),
    sort_order: str = Query(default="desc", alias="sort_order"),
    campaign_id: str | None = Query(default=None),
    tone: str | None = Query(default=None),
    user: CurrentUserContext = Depends(require_user_permissions("user:marketing.read")),
) -> JSONResponse:
    return _timed_call(
        request,
        "copy_list",
        "copy",
        lambda trace: _canonical_success(
            trace.request_id or "",
            get_marketing_store()
            .list_copies(
                user_id=user.user_id,
                tenant_id=user.tenant_id,
                page=page,
                page_size=page_size,
                sort_by=sort_by,
                sort_order=sort_order,
                campaign_id=campaign_id,
                tone=tone,
            )
            .model_dump(mode="json"),
        ),
    )


@router.get("/marketing/copies/{copy_id}")
def get_generated_copy(
    copy_id: str,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:marketing.read")),
) -> JSONResponse:
    return _timed_call(
        request,
        "copy_detail",
        "copy",
        lambda trace: _canonical_success(
            trace.request_id or "",
            _get_owned_copy(user.user_id, user.tenant_id, copy_id).model_dump(mode="json"),
            message="success",
        ),
        attributes_factory=lambda _trace: {"user_id": user.user_id, "tenant_id": user.tenant_id, "copy_id": copy_id},
    )


@router.post("/marketing/promotion-links/generate")
def generate_promotion_link(
    payload: PromotionLinkRequest,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:marketing.write")),
) -> JSONResponse:
    return _timed_call(
        request,
        "promotion_link_generation",
        "promotion_link",
        lambda trace: _canonical_success(
            trace.request_id or "",
            get_marketing_store().create_promotion_link(user_id=user.user_id, tenant_id=user.tenant_id, payload=payload).model_dump(mode="json"),
            message="success",
        ),
        attributes_factory=lambda _trace: {"user_id": user.user_id, "tenant_id": user.tenant_id, "campaign_id": payload.campaign_id},
    )


@router.get("/marketing/promotion-links")
def list_promotion_links(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="page_size"),
    sort_by: str = Query(default="created_at", alias="sort_by"),
    sort_order: str = Query(default="desc", alias="sort_order"),
    campaign_id: str | None = Query(default=None),
    channel: str | None = Query(default=None),
    user: CurrentUserContext = Depends(require_user_permissions("user:marketing.read")),
) -> JSONResponse:
    return _timed_call(
        request,
        "promotion_link_list",
        "promotion_link",
        lambda trace: _canonical_success(
            trace.request_id or "",
            get_marketing_store()
            .list_promotion_links(
                user_id=user.user_id,
                tenant_id=user.tenant_id,
                page=page,
                page_size=page_size,
                sort_by=sort_by,
                sort_order=sort_order,
                campaign_id=campaign_id,
                channel=channel,
            )
            .model_dump(mode="json"),
        ),
    )


@router.get("/marketing/promotion-links/{link_id}")
def get_promotion_link(
    link_id: str,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:marketing.read")),
) -> JSONResponse:
    return _timed_call(
        request,
        "promotion_link_detail",
        "promotion_link",
        lambda trace: _canonical_success(
            trace.request_id or "",
            _get_owned_link(user.user_id, user.tenant_id, link_id).model_dump(mode="json"),
            message="success",
        ),
        attributes_factory=lambda _trace: {"user_id": user.user_id, "tenant_id": user.tenant_id, "link_id": link_id},
    )


@router.post("/marketing/posters")
def create_poster_task(
    payload: CreatePosterTaskRequest,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:marketing.write")),
) -> JSONResponse:
    return _timed_call(
        request,
        "poster_create",
        "poster",
        lambda trace: _create_poster_task_response(trace, user, payload),
        attributes_factory=lambda _trace: {"user_id": user.user_id, "tenant_id": user.tenant_id, "campaign_id": payload.campaign_id},
    )


@router.get("/marketing/posters")
def list_poster_tasks(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="page_size"),
    sort_by: str = Query(default="created_at", alias="sort_by"),
    sort_order: str = Query(default="desc", alias="sort_order"),
    campaign_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    user: CurrentUserContext = Depends(require_user_permissions("user:marketing.read")),
) -> JSONResponse:
    return _timed_call(
        request,
        "poster_task_list",
        "poster",
        lambda trace: _canonical_success(
            trace.request_id or "",
            get_marketing_store()
            .list_poster_tasks(
                user_id=user.user_id,
                tenant_id=user.tenant_id,
                page=page,
                page_size=page_size,
                sort_by=sort_by,
                sort_order=sort_order,
                campaign_id=campaign_id,
                status=status,
            )
            .model_dump(mode="json"),
        ),
    )


@router.get("/marketing/posters/{task_id}")
def get_poster_task(
    task_id: str,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:marketing.read")),
) -> JSONResponse:
    return _timed_call(
        request,
        "poster_detail",
        "poster",
        lambda trace: _canonical_success(
            trace.request_id or "",
            _get_owned_poster_task(user.user_id, user.tenant_id, task_id).model_dump(mode="json"),
            message="success",
        ),
        attributes_factory=lambda _trace: {"user_id": user.user_id, "tenant_id": user.tenant_id, "task_id": task_id},
    )


@router.get("/marketing/posters/{task_id}/result")
def get_poster_result(
    task_id: str,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:marketing.read")),
) -> JSONResponse:
    return _timed_call(
        request,
        "poster_result_detail",
        "poster",
        lambda trace: _canonical_success(
            trace.request_id or "",
            _get_owned_poster_result(user.user_id, user.tenant_id, task_id).model_dump(mode="json"),
            message="success",
        ),
        attributes_factory=lambda _trace: {"user_id": user.user_id, "tenant_id": user.tenant_id, "task_id": task_id},
    )


def _create_poster_task_response(trace, user: CurrentUserContext, payload: CreatePosterTaskRequest) -> JSONResponse:
    request_id = trace.request_id or ""
    idempotency_key = trace.idempotency_key
    response = get_marketing_store().create_poster_task(
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )
    mongo_runtime = get_marketing_mongo_runtime()
    if getattr(mongo_runtime, "enabled", True) and response.status == "queued":
        task_record = get_marketing_store().get_poster_task(user_id=user.user_id, tenant_id=user.tenant_id, task_id=response.task_id)
        if task_record is not None:
            try:
                _run_async(mongo_runtime.upsert_asset(task_record))
            except Exception as exc:
                marketing_mongodb_operations_total.labels(operation="upsert_asset", status="error").inc()
                marketing_upstream_errors_total.labels(backend="mongodb", error_type=exc.__class__.__name__).inc()
                get_marketing_store().delete_poster_task(response.task_id)
                raise ServiceError(503, 5030001, "poster asset document store unavailable", error_type=exc.__class__.__name__) from exc
            marketing_mongodb_operations_total.labels(operation="upsert_asset", status="success").inc()
    if response.status == "queued":
        celery_enabled = bool(get_settings().celery_broker_url and get_settings().celery_result_backend)
        if celery_enabled:
            with start_span(
                "marketing.celery_enqueue",
                attributes={"operation": "celery_enqueue", "trace_id": trace.trace_id, "task_id": response.task_id},
            ) as enqueue_span:
                try:
                    generate_poster_task_job.apply_async(args=[response.task_id])
                except Exception as exc:
                    set_span_attributes(enqueue_span, {"status": "error", "error_type": exc.__class__.__name__})
                    marketing_celery_operations_total.labels(operation="enqueue", status="error").inc()
                    marketing_upstream_errors_total.labels(backend="celery", error_type=exc.__class__.__name__).inc()
                    raise ServiceError(503, 5030001, "poster task queue unavailable", error_type=exc.__class__.__name__) from exc
                set_span_attributes(enqueue_span, {"status": "ok"})
                marketing_celery_operations_total.labels(operation="enqueue", status="success").inc()
        else:
            try:
                get_marketing_store().process_poster_task(response.task_id)
            except Exception:
                pass
            marketing_celery_operations_total.labels(operation="poster_inline_complete", status="success").inc()
    return _canonical_success(request_id, response.model_dump(mode="json"), status_code=202)


def _run_async(coro):
    import asyncio

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            raise RuntimeError("event loop already running")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    return loop.run_until_complete(coro)


def _delete_admin_campaign_response(trace, campaign_id: str) -> JSONResponse:
    get_marketing_store().soft_delete_admin_campaign(campaign_id)
    return _canonical_success(trace.request_id or "", {"success": True})


def _get_owned_copy(user_id: str, tenant_id: str, copy_id: str) -> MarketingCopyResult:
    result = get_marketing_store().get_copy(user_id=user_id, tenant_id=tenant_id, copy_id=copy_id)
    if result is None:
        raise ServiceError(404, 4040001, "marketing copy not found", public=True)
    return result


def _get_owned_link(user_id: str, tenant_id: str, link_id: str) -> PromotionLinkResult:
    result = get_marketing_store().get_promotion_link(user_id=user_id, tenant_id=tenant_id, link_id=link_id)
    if result is None:
        raise ServiceError(404, 4040001, "promotion link not found", public=True)
    return result


def _get_owned_poster_task(user_id: str, tenant_id: str, task_id: str) -> PosterTask:
    task = get_marketing_store().get_poster_task(user_id=user_id, tenant_id=tenant_id, task_id=task_id)
    if task is None:
        raise ServiceError(404, 4040001, "poster task not found", public=True)
    return task


def _get_owned_poster_result(user_id: str, tenant_id: str, task_id: str) -> PosterResultData:
    result = get_marketing_store().get_poster_result(user_id=user_id, tenant_id=tenant_id, task_id=task_id)
    if result is None:
        raise ServiceError(404, 4040001, "poster result not found", public=True)
    return result


def _timed_call(
    request: Request,
    operation: str,
    resource_type: str,
    callback: Callable[[Any], JSONResponse],
    *,
    attributes_factory: Callable[[Any], dict[str, Any]] | None = None,
) -> JSONResponse:
    trace = build_trace_context(request)
    started = perf_counter()
    attributes = attributes_factory(trace) if attributes_factory else {}
    with start_span(
        f"marketing.{operation}",
        attributes={"operation": operation, "request_id": trace.request_id, "trace_id": trace.trace_id, **attributes},
    ) as span:
        try:
            response = callback(trace)
        except ServiceError as exc:
            set_span_attributes(span, {"status": "error", "error_type": exc.error_type or exc.__class__.__name__})
            raise
        except Exception as exc:
            set_span_attributes(span, {"status": "error", "error_type": exc.__class__.__name__})
            raise
    observe_duration(operation, perf_counter() - started)
    record_request(operation, "success" if response.status_code < 400 else "error", resource_type)
    return response


def _canonical_success(
    request_id: str,
    data: dict[str, Any],
    *,
    message: str = "ok",
    status_code: int = 200,
) -> JSONResponse:
    envelope = CanonicalSuccessEnvelope(
        message=message,
        data=data,
        request_id=request_id,
        timestamp=now_timestamp_ms(),
    ).model_dump(mode="json")
    return JSONResponse(status_code=status_code, content=envelope)


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


