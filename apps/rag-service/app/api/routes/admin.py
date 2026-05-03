from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import build_trace_context, build_upstream_headers
from app.core.metrics import UPSTREAM_ERRORS_TOTAL
from app.models.admin import (
    AdminRetrievalDiagnosticsRequest,
    CanonicalErrorDetail,
    CanonicalErrorEnvelope,
    CanonicalSuccessEnvelope,
)
from app.models.rag import RetrieveRequest
from app.services.cache import get_retrieval_cache
from app.services.knowledge_client import KnowledgeServiceProtocolError
from app.services.providers import get_knowledge_client
from app.services.retrieval import get_retrieval_service

router = APIRouter()


def _timestamp_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def _build_degradation_note(exc: Exception) -> str:
    if isinstance(exc, KnowledgeServiceProtocolError):
        return str(exc)
    return f"knowledge-service unavailable: {exc.__class__.__name__}"


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


def _error(request: Request, *, status_code: int, code: int, message: str, error_type: str, field: str | None = None) -> JSONResponse:
    trace = build_trace_context(request)
    return JSONResponse(
        status_code=status_code,
        content=CanonicalErrorEnvelope(
            code=code,
            message=message,
            request_id=trace.request_id or "",
            timestamp=_timestamp_ms(),
            error=CanonicalErrorDetail(type=error_type, field=field, reason=message),
        ).model_dump(mode="json"),
    )


@router.post("/retrieval/diagnostics")
async def retrieval_diagnostics(payload: AdminRetrievalDiagnosticsRequest, request: Request) -> JSONResponse:
    trace = build_trace_context(request)
    retrieval_service = get_retrieval_service()
    filters = {"sourceIds": [payload.kb_id] if payload.kb_id else [], "tags": []}
    upstream_headers = build_upstream_headers(trace)

    request_model = RetrieveRequest(query=payload.query, topK=payload.top_k, filters=filters)
    try:
        rewrite, candidates = await retrieval_service.search_candidates(
            request_model,
            get_knowledge_client(),
            upstream_headers,
            cache_service=get_retrieval_cache(),
        )
        diagnostic = retrieval_service.build_diagnostic(request_model, candidates, rewrite)
    except (httpx.HTTPError, KnowledgeServiceProtocolError) as exc:
        UPSTREAM_ERRORS_TOTAL.inc()
        rewrite = retrieval_service.rewrite_query(request_model)
        diagnostic = retrieval_service.build_diagnostic(
            request_model,
            [],
            rewrite,
            degraded=True,
            degradation_note=_build_degradation_note(exc),
        )

    sources = [
        {
            "doc_id": citation.document_id,
            "chunk_id": citation.chunk_id,
            "kb_id": citation.source_id,
            "title": citation.document_title,
            "score": citation.score,
            "content_preview": citation.snippet,
            "tags": [],
        }
        for citation in diagnostic.citations
    ]
    data = {
        "query": diagnostic.query,
        "rewritten_query": diagnostic.rewritten_query,
        "sources": sources,
        "coverage": {
            "candidate_count": diagnostic.candidate_count,
            "source_breakdown": [item.model_dump(mode="json") for item in diagnostic.source_breakdown],
            "tag_breakdown": [item.model_dump(mode="json") for item in diagnostic.tag_breakdown],
            "unmatched_terms": diagnostic.unmatched_terms,
            "degraded": diagnostic.degraded,
        },
        "answerable": len(diagnostic.citations) > 0 and not diagnostic.degraded,
        "debug": {
            "expanded_terms": diagnostic.expanded_terms,
            "query_terms": diagnostic.query_terms,
            "applied_filters": diagnostic.applied_filters.model_dump(mode="json", by_alias=True),
            "strategy": diagnostic.strategy,
            "citations": [citation.model_dump(mode="json", by_alias=True) for citation in diagnostic.citations] if payload.include_citations else [],
        },
        "notes": diagnostic.coverage_notes,
    }
    return _success(request, data)


@router.post("/cache/clear")
async def clear_cache(request: Request) -> JSONResponse:
    cleared = get_retrieval_cache().clear_prefix()
    return _success(request, {"clearedEntries": cleared})
