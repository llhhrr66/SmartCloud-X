from datetime import UTC, datetime

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import build_trace_context
from app.core.config import get_settings
from app.models.admin import (
    CanonicalErrorDetail,
    CanonicalErrorEnvelope,
    CanonicalSuccessEnvelope,
    AdminKnowledgeBaseCreateRequest,
    AdminKnowledgeBaseUpdateRequest,
    AdminKnowledgeDocumentCreateRequest,
    AdminKnowledgeReindexRequest,
    AdminRetrievalSearchPreviewRequest,
)
from app.services.admin import (
    AdminConflictError,
    AdminNotFoundError,
    AdminValidationError,
    get_admin_service,
)

router = APIRouter()

VALIDATION_CODE = 4001001
NOT_FOUND_CODE = 4040001
CONFLICT_CODE = 4090001


def _timestamp_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def _success(request: Request, data, *, status_code: int = 200, message: str = "ok") -> JSONResponse:
    trace = build_trace_context(request)
    return JSONResponse(
        status_code=status_code,
        content=CanonicalSuccessEnvelope(
            message=message,
            data=data,
            request_id=trace.request_id or "",
            timestamp=_timestamp_ms(),
        ).model_dump(mode="json"),
    )


def _error(
    request: Request,
    *,
    status_code: int,
    code: int,
    message: str,
    error_type: str,
    field: str | None = None,
) -> JSONResponse:
    trace = build_trace_context(request)
    return JSONResponse(
        status_code=status_code,
        content=CanonicalErrorEnvelope(
            code=code,
            message=message,
            request_id=trace.request_id or "",
            timestamp=_timestamp_ms(),
            error=CanonicalErrorDetail(
                type=error_type,
                field=field,
                reason=message,
            ),
        ).model_dump(mode="json"),
    )


def _operator_reason(request: Request) -> str:
    header_name = get_settings().operator_reason_header
    reason = request.headers.get(header_name, "").strip()
    if not reason:
        raise AdminValidationError(f"{header_name} header is required for admin write routes")
    return reason


def _operator_id(request: Request) -> str:
    trace = build_trace_context(request)
    caller = trace.caller_service or request.headers.get("X-Caller-Service")
    return caller or "web-admin"


def _operator_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/knowledge-bases")
def list_knowledge_bases(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
    scene: str | None = Query(default=None),
) -> JSONResponse:
    data = get_admin_service().list_knowledge_bases(
        page=page,
        page_size=page_size,
        status=status,
        scene=scene,
    )
    return _success(request, data.model_dump(mode="json"))


@router.post("/knowledge-bases")
def create_knowledge_base(payload: AdminKnowledgeBaseCreateRequest, request: Request) -> JSONResponse:
    service = get_admin_service()
    try:
        record = service.create_knowledge_base(
            payload,
            operator_id=_operator_id(request),
            operator_ip=_operator_ip(request),
            reason=_operator_reason(request),
        )
    except AdminConflictError as exc:
        return _error(
            request,
            status_code=409,
            code=CONFLICT_CODE,
            message=str(exc),
            error_type="conflict",
            field="code",
        )
    except AdminValidationError as exc:
        return _error(
            request,
            status_code=400,
            code=VALIDATION_CODE,
            message=str(exc),
            error_type="validation_error",
        )
    return _success(request, record.model_dump(mode="json"), status_code=201, message="created")


@router.patch("/knowledge-bases/{kb_id}")
def update_knowledge_base(
    kb_id: str,
    payload: AdminKnowledgeBaseUpdateRequest,
    request: Request,
) -> JSONResponse:
    service = get_admin_service()
    try:
        record = service.update_knowledge_base(
            kb_id,
            payload,
            operator_id=_operator_id(request),
            operator_ip=_operator_ip(request),
            reason=_operator_reason(request),
        )
    except AdminNotFoundError as exc:
        return _error(
            request,
            status_code=404,
            code=NOT_FOUND_CODE,
            message=str(exc),
            error_type="not_found",
            field="kb_id",
        )
    except AdminValidationError as exc:
        return _error(
            request,
            status_code=400,
            code=VALIDATION_CODE,
            message=str(exc),
            error_type="validation_error",
        )
    return _success(request, record.model_dump(mode="json"))


@router.get("/knowledge-bases/{kb_id}/documents")
def list_documents(
    kb_id: str,
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
) -> JSONResponse:
    service = get_admin_service()
    try:
        data = service.list_documents(
            kb_id,
            page=page,
            page_size=page_size,
            status=status,
            keyword=keyword,
        )
    except AdminNotFoundError as exc:
        return _error(
            request,
            status_code=404,
            code=NOT_FOUND_CODE,
            message=str(exc),
            error_type="not_found",
            field="kb_id",
        )
    return _success(request, data.model_dump(mode="json"))


@router.get("/knowledge-documents/{doc_id}")
def get_document_detail(doc_id: str, request: Request) -> JSONResponse:
    service = get_admin_service()
    try:
        data = service.get_document_detail(doc_id)
    except AdminNotFoundError as exc:
        return _error(
            request,
            status_code=404,
            code=NOT_FOUND_CODE,
            message=str(exc),
            error_type="not_found",
            field="doc_id",
        )
    return _success(request, data.model_dump(mode="json"))


@router.post("/knowledge-bases/{kb_id}/documents")
def create_document(
    kb_id: str,
    payload: AdminKnowledgeDocumentCreateRequest,
    request: Request,
) -> JSONResponse:
    service = get_admin_service()
    try:
        record = service.create_document(
            kb_id,
            payload,
            operator_id=_operator_id(request),
            operator_ip=_operator_ip(request),
            reason=_operator_reason(request),
        )
    except AdminNotFoundError as exc:
        return _error(
            request,
            status_code=404,
            code=NOT_FOUND_CODE,
            message=str(exc),
            error_type="not_found",
            field="kb_id" if "base" in str(exc).lower() else "file_id",
        )
    except AdminValidationError as exc:
        return _error(
            request,
            status_code=400,
            code=VALIDATION_CODE,
            message=str(exc),
            error_type="validation_error",
        )
    except ValueError as exc:
        return _error(
            request,
            status_code=400,
            code=VALIDATION_CODE,
            message=str(exc),
            error_type="validation_error",
            field="file_id",
        )
    return _success(request, record.model_dump(mode="json"), status_code=202, message="accepted")


@router.get("/knowledge-documents/{doc_id}/chunks")
def list_document_chunks(
    doc_id: str,
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> JSONResponse:
    service = get_admin_service()
    try:
        data = service.list_document_chunks(doc_id, page=page, page_size=page_size)
    except AdminNotFoundError as exc:
        return _error(
            request,
            status_code=404,
            code=NOT_FOUND_CODE,
            message=str(exc),
            error_type="not_found",
            field="doc_id",
        )
    return _success(request, data.model_dump(mode="json"))


@router.post("/knowledge-documents/{doc_id}/reindex")
def reindex_document(
    doc_id: str,
    payload: AdminKnowledgeReindexRequest,
    request: Request,
) -> JSONResponse:
    service = get_admin_service()
    try:
        data = service.reindex_document(
            doc_id,
            payload,
            operator_id=_operator_id(request),
            operator_ip=_operator_ip(request),
            reason=_operator_reason(request),
        )
    except AdminNotFoundError as exc:
        return _error(
            request,
            status_code=404,
            code=NOT_FOUND_CODE,
            message=str(exc),
            error_type="not_found",
            field="doc_id",
        )
    except AdminValidationError as exc:
        return _error(
            request,
            status_code=400,
            code=VALIDATION_CODE,
            message=str(exc),
            error_type="validation_error",
            field="confirm_token" if "confirm_token" in str(exc) else None,
        )
    return _success(request, data.model_dump(mode="json"), status_code=202, message="accepted")


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request) -> JSONResponse:
    service = get_admin_service()
    try:
        data = service.get_job(job_id)
    except AdminNotFoundError as exc:
        return _error(
            request,
            status_code=404,
            code=NOT_FOUND_CODE,
            message=str(exc),
            error_type="not_found",
            field="job_id",
        )
    return _success(request, data.model_dump(mode="json"))


@router.post("/retrieval/search-preview")
def search_preview(payload: AdminRetrievalSearchPreviewRequest, request: Request) -> JSONResponse:
    service = get_admin_service()
    try:
        data = service.preview_search(payload)
    except AdminNotFoundError as exc:
        return _error(
            request,
            status_code=404,
            code=NOT_FOUND_CODE,
            message=str(exc),
            error_type="not_found",
            field="kb_id",
        )
    return _success(request, data.model_dump(mode="json"))
