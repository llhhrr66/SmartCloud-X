from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.dependencies import build_trace_context, require_user_permissions
from app.models import (
    CanonicalSuccessEnvelope,
    CreatePosterTaskRequest,
    CurrentUserContext,
    MarketingCopyResult,
    MarketingCopyRequest,
    PosterResultData,
    PosterTask,
    PromotionLinkResult,
    PromotionLinkRequest,
    ServiceError,
    now_timestamp_ms,
)
from app.store import get_marketing_store


health_router = APIRouter(tags=["health"])
router = APIRouter(tags=["marketing"])


@health_router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "marketing-service"}


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
    trace = build_trace_context(request)
    data = get_marketing_store().list_campaigns(
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
        status=status,
        product_type=product_type,
    )
    return _canonical_success(trace.request_id or "", data.model_dump(mode="json"))


@router.post("/marketing/copy/generate")
def generate_copy(
    payload: MarketingCopyRequest,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:marketing.write")),
) -> JSONResponse:
    trace = build_trace_context(request)
    data = get_marketing_store().create_copy(user_id=user.user_id, tenant_id=user.tenant_id, payload=payload)
    return _canonical_success(trace.request_id or "", data.model_dump(mode="json"), message="success")


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
    trace = build_trace_context(request)
    data = get_marketing_store().list_copies(
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
        campaign_id=campaign_id,
        tone=tone,
    )
    return _canonical_success(trace.request_id or "", data.model_dump(mode="json"))


@router.get("/marketing/copies/{copy_id}")
def get_generated_copy(
    copy_id: str,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:marketing.read")),
) -> JSONResponse:
    trace = build_trace_context(request)
    copy = _get_owned_copy(user.user_id, user.tenant_id, copy_id)
    return _canonical_success(trace.request_id or "", copy.model_dump(mode="json"), message="success")


@router.post("/marketing/promotion-links/generate")
def generate_promotion_link(
    payload: PromotionLinkRequest,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:marketing.write")),
) -> JSONResponse:
    trace = build_trace_context(request)
    data = get_marketing_store().create_promotion_link(
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        payload=payload,
    )
    return _canonical_success(trace.request_id or "", data.model_dump(mode="json"), message="success")


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
    trace = build_trace_context(request)
    data = get_marketing_store().list_promotion_links(
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
        campaign_id=campaign_id,
        channel=channel,
    )
    return _canonical_success(trace.request_id or "", data.model_dump(mode="json"))


@router.get("/marketing/promotion-links/{link_id}")
def get_promotion_link(
    link_id: str,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:marketing.read")),
) -> JSONResponse:
    trace = build_trace_context(request)
    link = _get_owned_promotion_link(user.user_id, user.tenant_id, link_id)
    return _canonical_success(trace.request_id or "", link.model_dump(mode="json"), message="success")


@router.get("/marketing/posters")
def list_poster_tasks(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="page_size"),
    sort_by: str = Query(default="updated_at", alias="sort_by"),
    sort_order: str = Query(default="desc", alias="sort_order"),
    status: str | None = Query(default=None),
    campaign_id: str | None = Query(default=None),
    user: CurrentUserContext = Depends(require_user_permissions("user:marketing.read")),
) -> JSONResponse:
    trace = build_trace_context(request)
    data = get_marketing_store().list_poster_tasks(
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
        status=status,
        campaign_id=campaign_id,
    )
    return _canonical_success(trace.request_id or "", data.model_dump(mode="json"))


@router.post("/marketing/posters")
def create_poster_task(
    payload: CreatePosterTaskRequest,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:marketing.write")),
) -> JSONResponse:
    trace = build_trace_context(request)
    data = get_marketing_store().create_poster_task(
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        payload=payload,
        idempotency_key=_require_idempotency_key(request),
    )
    return _canonical_success(trace.request_id or "", data.model_dump(mode="json"), message="accepted", status_code=202)


@router.get("/marketing/posters/{task_id}")
def get_poster_task(
    task_id: str,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:marketing.read")),
) -> JSONResponse:
    trace = build_trace_context(request)
    task = _get_owned_poster_task(user.user_id, user.tenant_id, task_id)
    return _canonical_success(trace.request_id or "", task.model_dump(mode="json"), message="success")


@router.get("/marketing/posters/{task_id}/result")
def get_poster_result(
    task_id: str,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:marketing.read")),
) -> JSONResponse:
    trace = build_trace_context(request)
    task = _get_owned_poster_task(user.user_id, user.tenant_id, task_id)
    result = _build_poster_result(task)
    return _canonical_success(trace.request_id or "", result.model_dump(mode="json"), message="success")


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
            error_type="missing_header",
            details={"header": "Idempotency-Key"},
        )
    return idempotency_key


def _get_owned_poster_task(user_id: str, tenant_id: str | None, task_id: str) -> PosterTask:
    task = get_marketing_store().get_poster_task(user_id=user_id, tenant_id=tenant_id, task_id=task_id)
    if task is None:
        raise ServiceError(404, 4040001, f"poster task '{task_id}' was not found")
    return task


def _get_owned_copy(user_id: str, tenant_id: str | None, copy_id: str) -> MarketingCopyResult:
    copy = get_marketing_store().get_copy(user_id=user_id, tenant_id=tenant_id, copy_id=copy_id)
    if copy is None:
        raise ServiceError(404, 4040001, f"marketing copy '{copy_id}' was not found")
    return copy


def _get_owned_promotion_link(user_id: str, tenant_id: str | None, link_id: str) -> PromotionLinkResult:
    link = get_marketing_store().get_promotion_link(user_id=user_id, tenant_id=tenant_id, link_id=link_id)
    if link is None:
        raise ServiceError(404, 4040001, f"promotion link '{link_id}' was not found")
    return link


def _build_poster_result(task: PosterTask) -> PosterResultData:
    result_ready = bool(task.image_url and task.status == "completed")
    download_url = f"{task.image_url}?download=1" if result_ready and task.image_url else None
    return PosterResultData(
        task_id=task.task_id,
        status=task.status,
        result_ready=result_ready,
        campaign_id=task.campaign_id,
        campaign_name=task.campaign_name,
        theme=task.theme,
        slogan=task.slogan,
        size=task.size,
        image_url=task.image_url,
        preview_url=task.image_url if result_ready else None,
        download_url=download_url,
        mime_type="image/png" if result_ready else None,
        generated_at=task.updated_at,
    )
