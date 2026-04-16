from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.dependencies import build_trace_context, require_user_permissions
from app.models import (
    CanonicalSuccessEnvelope,
    CreateResearchTaskRequest,
    CurrentUserContext,
    ResearchTask,
    ResearchTaskResultData,
    ResearchTaskStatusData,
    ServiceError,
    now_timestamp_ms,
)
from app.store import get_research_store


health_router = APIRouter(tags=["health"])
router = APIRouter(tags=["research"])


@health_router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "research-service"}


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
    trace = build_trace_context(request)
    data = get_research_store().list_tasks(
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
        status=status,
    )
    return _canonical_success(trace.request_id or "", data.model_dump(mode="json"))


@router.post("/research/tasks")
def create_research_task(
    payload: CreateResearchTaskRequest,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:research.write")),
) -> JSONResponse:
    trace = build_trace_context(request)
    data = get_research_store().create_task(
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        payload=payload,
        idempotency_key=_require_idempotency_key(request),
    )
    return _canonical_success(
        trace.request_id or "",
        data.model_dump(mode="json"),
        message="accepted",
        status_code=202,
    )


@router.get("/research/tasks/{task_id}")
def get_research_task(
    task_id: str,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:research.read")),
) -> JSONResponse:
    trace = build_trace_context(request)
    task = _get_owned_task(user.user_id, user.tenant_id, task_id)
    return _canonical_success(trace.request_id or "", task.model_dump(mode="json"), message="success")


@router.get("/research/tasks/{task_id}/status")
def get_research_task_status(
    task_id: str,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:research.read")),
) -> JSONResponse:
    trace = build_trace_context(request)
    task = _get_owned_task(user.user_id, user.tenant_id, task_id)
    status = ResearchTaskStatusData(
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
    return _canonical_success(trace.request_id or "", status.model_dump(mode="json"), message="success")


@router.get("/research/tasks/{task_id}/result")
def get_research_task_result(
    task_id: str,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:research.read")),
) -> JSONResponse:
    trace = build_trace_context(request)
    task = _get_owned_task(user.user_id, user.tenant_id, task_id)
    result = _build_research_result(task)
    return _canonical_success(trace.request_id or "", result.model_dump(mode="json"), message="success")


@router.get("/research/tasks/{task_id}/report", include_in_schema=False)
def get_research_task_report(
    task_id: str,
    request: Request,
    user: CurrentUserContext = Depends(require_user_permissions("user:research.read")),
) -> JSONResponse:
    trace = build_trace_context(request)
    task = _get_owned_task(user.user_id, user.tenant_id, task_id)
    result = _build_research_result(task)
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


def _get_owned_task(user_id: str, tenant_id: str | None, task_id: str) -> ResearchTask:
    task = get_research_store().get_task(user_id=user_id, tenant_id=tenant_id, task_id=task_id)
    if task is None:
        raise ServiceError(404, 4040001, f"research task '{task_id}' was not found")
    return task


def _build_research_result(task: ResearchTask) -> ResearchTaskResultData:
    result_ready = bool(task.report_file_id and task.status == "completed")
    download_url = None
    preview_text = None
    citations: list[str] = []
    if result_ready and task.report_file_id:
        extension = "pdf" if task.output_format == "pdf" else "md"
        download_url = f"https://downloads.smartcloud.local/research/{task.report_file_id}.{extension}"
        preview_text = "\n\n".join(
            [
                f"# {task.topic}",
                f"## 研究范围\n{task.scope}",
                "## 占位结论\n- 当前基线已生成结论摘要、对比矩阵与下一步实施建议。",
            ]
        )
        citations = [
            "placeholder://research/executive-summary",
            "placeholder://research/comparison-matrix",
            "placeholder://research/recommendations",
        ]
    return ResearchTaskResultData(
        task_id=task.task_id,
        status=task.status,
        result_ready=result_ready,
        output_format=task.output_format,
        summary=task.summary,
        report_file_id=task.report_file_id,
        download_url=download_url,
        preview_text=preview_text,
        citations=citations,
        generated_at=task.finished_at,
    )
