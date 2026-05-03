from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import build_trace_context
from app.models.common import ApiEnvelope, ErrorInfo
from app.models.knowledge import (
    CreateSourceRequest,
    FileImportPreviewRequest,
    FileImportRequest,
    IngestDocumentRequest,
    SearchRequest,
)
from app.services.admin import get_admin_service
from app.services.analytics import get_analytics_service
from app.services.file_import import get_file_import_service
from app.services.ingestion import get_ingestion_service
from app.services.search import get_search_service
from app.services.snapshot import get_snapshot_service
from app.services.store_provider import get_repository
from app.core.config import EmbeddingConfigurationError, get_settings
from app.services.embeddings import FallbackEmbeddingProvider, build_embedding_provider

router = APIRouter()


def error_response(trace, status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ApiEnvelope(
            success=False,
            requestId=trace.request_id,
            trace=trace,
            error=ErrorInfo(code=code, message=message),
        ).model_dump(mode="json", by_alias=True),
    )


@router.get("/sources", response_model=ApiEnvelope)
def list_sources(request: Request) -> ApiEnvelope[list]:
    trace = build_trace_context(request)
    return ApiEnvelope(
        data=get_repository().list_sources(),
        requestId=trace.request_id,
        trace=trace,
    )


@router.post("/sources", response_model=ApiEnvelope, status_code=201)
def create_source(payload: CreateSourceRequest, request: Request) -> ApiEnvelope[dict]:
    trace = build_trace_context(request)
    source = get_ingestion_service().create_source(payload)
    return ApiEnvelope(data=source, requestId=trace.request_id, trace=trace)


@router.get("/documents", response_model=ApiEnvelope)
def list_documents(
    request: Request,
    source_id: str | None = Query(default=None, alias="sourceId"),
) -> ApiEnvelope[list]:
    trace = build_trace_context(request)
    documents = get_repository().list_documents(source_id=source_id)
    return ApiEnvelope(data=documents, requestId=trace.request_id, trace=trace)


@router.get("/chunks", response_model=ApiEnvelope)
def list_chunks(
    request: Request,
    document_id: str | None = Query(default=None, alias="documentId"),
    source_ids: list[str] | None = Query(default=None, alias="sourceId"),
    tags: list[str] | None = Query(default=None),
) -> ApiEnvelope[list]:
    trace = build_trace_context(request)
    chunks = get_repository().list_chunks(document_id=document_id, source_ids=source_ids, tags=tags)
    return ApiEnvelope(data=chunks, requestId=trace.request_id, trace=trace)


@router.get("/ingestions", response_model=ApiEnvelope)
def list_ingestions(
    request: Request,
    source_id: str | None = Query(default=None, alias="sourceId"),
) -> ApiEnvelope[list]:
    trace = build_trace_context(request)
    ingestions = get_repository().list_ingestions(source_id=source_id)
    return ApiEnvelope(data=ingestions, requestId=trace.request_id, trace=trace)


@router.get("/admin/audit-records", response_model=ApiEnvelope)
def list_admin_audit_records(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    resource_type: str | None = Query(default=None, alias="resourceType"),
    action: str | None = Query(default=None),
    operator_id: str | None = Query(default=None, alias="operatorId"),
) -> ApiEnvelope[dict]:
    trace = build_trace_context(request)
    result = get_admin_service().list_audit_records(
        page=page,
        page_size=page_size,
        resource_type=resource_type,
        action=action,
        operator_id=operator_id,
    )
    return ApiEnvelope(data=result, requestId=trace.request_id, trace=trace)


@router.get("/overview", response_model=ApiEnvelope)
def overview(request: Request) -> ApiEnvelope[dict]:
    trace = build_trace_context(request)
    result = get_analytics_service().build_overview()
    return ApiEnvelope(data=result, requestId=trace.request_id, trace=trace)


@router.get("/snapshot", response_model=ApiEnvelope)
def snapshot(
    request: Request,
    audit_limit: int = Query(default=20, ge=0, le=200, alias="auditLimit"),
) -> ApiEnvelope[dict]:
    trace = build_trace_context(request)
    result = get_snapshot_service().build_snapshot(audit_limit=audit_limit)
    return ApiEnvelope(data=result, requestId=trace.request_id, trace=trace)


@router.get("/imports:preview", response_model=ApiEnvelope)
def preview_imports(
    request: Request,
    directory: str | None = Query(default=None),
    glob_pattern: str = Query(default="**/*", alias="glob"),
    max_files: int = Query(default=12, ge=1, le=100, alias="maxFiles"),
) -> ApiEnvelope[dict] | JSONResponse:
    trace = build_trace_context(request)
    try:
        result = get_file_import_service().preview(
            FileImportPreviewRequest(
                directory=directory,
                glob=glob_pattern,
                maxFiles=max_files,
            )
        )
    except ValueError as exc:
        return error_response(trace, 404, "knowledge.import_preview_failed", str(exc))
    return ApiEnvelope(data=result, requestId=trace.request_id, trace=trace)


@router.post("/documents:ingest", response_model=ApiEnvelope, status_code=201)
def ingest_document(payload: IngestDocumentRequest, request: Request) -> ApiEnvelope[dict] | JSONResponse:
    trace = build_trace_context(request)
    try:
        result = get_ingestion_service().ingest_document(payload)
    except ValueError as exc:
        return error_response(trace, 404, "knowledge.source_not_found", str(exc))
    return ApiEnvelope(data=result, requestId=trace.request_id, trace=trace)


@router.post("/files:ingest", response_model=ApiEnvelope, status_code=201)
def ingest_files(payload: FileImportRequest, request: Request) -> ApiEnvelope[dict] | JSONResponse:
    trace = build_trace_context(request)
    try:
        result = get_file_import_service().import_files(payload)
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "directory" in message.lower() or "sourceid" in message.lower() else 400
        return error_response(trace, status_code, "knowledge.file_import_failed", message)
    return ApiEnvelope(data=result, requestId=trace.request_id, trace=trace)


@router.post("/catalog:bootstrap", response_model=ApiEnvelope)
def bootstrap_catalog(request: Request) -> ApiEnvelope[dict]:
    trace = build_trace_context(request)
    result = get_ingestion_service().bootstrap_catalog()
    return ApiEnvelope(data=result, requestId=trace.request_id, trace=trace)


@router.post("/search", response_model=ApiEnvelope)
def search(payload: SearchRequest, request: Request) -> ApiEnvelope[dict]:
    trace = build_trace_context(request)
    result = get_search_service().search(payload)
    return ApiEnvelope(data=result, requestId=trace.request_id, trace=trace)


@router.get("/embedding:test", response_model=ApiEnvelope)
def embedding_test(
    request: Request,
    text: str = Query(..., min_length=1),
) -> ApiEnvelope[dict] | JSONResponse:
    trace = build_trace_context(request)
    try:
        settings = get_settings()
        provider = build_embedding_provider(settings)
        vector = provider.embed([text])[0]
    except EmbeddingConfigurationError as exc:
        return error_response(trace, 500, "knowledge.embedding_configuration_invalid", str(exc))
    except ValueError as exc:
        return error_response(trace, 500, "knowledge.embedding_provider_failed", str(exc))
    data = {
        "provider": provider.__class__.__name__,
        "configuredProvider": settings.embedding_provider,
        "sample": vector[:8],
        "dimensions": len(vector),
    }
    if isinstance(provider, FallbackEmbeddingProvider):
        data["provider"] = provider.last_provider_name
        data["fallbackActive"] = provider.last_provider_name != provider.primary.__class__.__name__
        if provider.last_error:
            data["providerError"] = provider.last_error
    return ApiEnvelope(
        data=data,
        requestId=trace.request_id,
        trace=trace,
    )
