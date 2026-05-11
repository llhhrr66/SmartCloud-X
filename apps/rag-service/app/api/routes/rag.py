import httpx
from fastapi import APIRouter, Query, Request

from pydantic import BaseModel, Field

from app.api.dependencies import build_trace_context, build_upstream_headers
from app.core.metrics import UPSTREAM_ERRORS_TOTAL
from app.models.common import ApiEnvelope
from app.models.rag import AnswerRequest, RetrieveRequest
from app.services.answer import get_answer_composer
from app.services.cache import get_retrieval_cache
from app.services.faq_cache import get_faq_cache
from app.services.providers import get_knowledge_client
from app.services.knowledge_client import KnowledgeServiceProtocolError
from app.services.retrieval import get_retrieval_service

router = APIRouter()


KNOWLEDGE_SEARCH_BACKEND = "knowledge-service-search"
KNOWLEDGE_UNAVAILABLE_BACKEND = "knowledge-service-unavailable"
HYBRID_BACKEND = "hybrid-semantic-bm25"


def _build_degradation_note(exc: Exception) -> str:
    if isinstance(exc, KnowledgeServiceProtocolError):
        return str(exc)
    return f"knowledge-service unavailable: {exc.__class__.__name__}"


@router.get("/capabilities", response_model=ApiEnvelope)
def capabilities(request: Request) -> ApiEnvelope[dict]:
    trace = build_trace_context(request)
    return ApiEnvelope(
        data={
            "rewrite": "keyword-synonym-context-aware",
            "retrieval": KNOWLEDGE_SEARCH_BACKEND,
            "hybrid": HYBRID_BACKEND,
            "rerank": "deterministic-configurable",
            "answering": "template-composer",
            "diagnostics": "rewrite-filters-candidate-inspection",
            "cache": {
                "L1_FAQ": get_faq_cache().describe(),
                "L2_retrieval": get_retrieval_cache().describe()["backend"],
            },
        },
        requestId=trace.request_id,
        trace=trace,
    )


@router.post("/rewrite", response_model=ApiEnvelope)
async def rewrite(payload: RetrieveRequest, request: Request) -> ApiEnvelope[dict]:
    trace = build_trace_context(request)
    response = get_retrieval_service().rewrite_query(payload)
    return ApiEnvelope(data=response, requestId=trace.request_id, trace=trace)


@router.post("/retrieve", response_model=ApiEnvelope)
async def retrieve(payload: RetrieveRequest, request: Request) -> ApiEnvelope[dict]:
    trace = build_trace_context(request)
    retrieval_service = get_retrieval_service()
    upstream_headers = build_upstream_headers(trace, conversation_id=payload.conversation_id)
    try:
        rewrite_result, candidates = await retrieval_service.search_candidates(
            payload,
            get_knowledge_client(),
            upstream_headers,
            cache_service=get_retrieval_cache(),
        )
        response = retrieval_service.build_response(
            payload,
            candidates,
            rewrite_result.rewritten_query,
            backend_used=KNOWLEDGE_SEARCH_BACKEND,
        )
    except (httpx.HTTPError, KnowledgeServiceProtocolError) as exc:
        UPSTREAM_ERRORS_TOTAL.inc()
        rewrite_result = retrieval_service.rewrite_query(payload)
        response = retrieval_service.build_response(
            payload,
            [],
            rewritten_query=rewrite_result.rewritten_query,
            degraded=True,
            degradation_note=_build_degradation_note(exc),
            backend_used=KNOWLEDGE_UNAVAILABLE_BACKEND,
        )
    return ApiEnvelope(data=response, requestId=trace.request_id, trace=trace)


@router.post("/retrieve/hybrid", response_model=ApiEnvelope)
async def hybrid_retrieve(
    payload: RetrieveRequest,
    request: Request,
    semantic_weight: float = Query(default=0.6, ge=0.0, le=1.0),
) -> ApiEnvelope[dict]:
    """Hybrid retrieval: semantic vector search + BM25 keyword scoring with weighted fusion.

    Query params:
    - semantic_weight: 0.0 = pure BM25, 1.0 = pure semantic, 0.6 = balanced (default)
    """
    trace = build_trace_context(request)
    retrieval_service = get_retrieval_service()
    upstream_headers = build_upstream_headers(trace, conversation_id=payload.conversation_id)
    try:
        response = await retrieval_service.hybrid_retrieve(
            payload,
            get_knowledge_client(),
            upstream_headers,
            cache_service=get_retrieval_cache(),
            semantic_weight=semantic_weight,
        )
    except (httpx.HTTPError, KnowledgeServiceProtocolError) as exc:
        UPSTREAM_ERRORS_TOTAL.inc()
        rewrite_result = retrieval_service.rewrite_query(payload)
        response = retrieval_service.build_response(
            payload,
            [],
            rewritten_query=rewrite_result.rewritten_query,
            degraded=True,
            degradation_note=_build_degradation_note(exc),
            backend_used=KNOWLEDGE_UNAVAILABLE_BACKEND,
        )
    return ApiEnvelope(data=response, requestId=trace.request_id, trace=trace)


@router.post("/diagnose", response_model=ApiEnvelope)
async def diagnose(payload: RetrieveRequest, request: Request) -> ApiEnvelope[dict]:
    trace = build_trace_context(request)
    retrieval_service = get_retrieval_service()
    upstream_headers = build_upstream_headers(trace, conversation_id=payload.conversation_id)
    try:
        rewrite_result, candidates = await retrieval_service.search_candidates(
            payload,
            get_knowledge_client(),
            upstream_headers,
            cache_service=get_retrieval_cache(),
        )
        response = retrieval_service.build_diagnostic(payload, candidates, rewrite_result, backend_used=KNOWLEDGE_SEARCH_BACKEND)
    except (httpx.HTTPError, KnowledgeServiceProtocolError) as exc:
        UPSTREAM_ERRORS_TOTAL.inc()
        rewrite_result = retrieval_service.rewrite_query(payload)
        response = retrieval_service.build_diagnostic(
            payload,
            [],
            rewrite_result,
            degraded=True,
            degradation_note=_build_degradation_note(exc),
            backend_used=KNOWLEDGE_UNAVAILABLE_BACKEND,
        )
    return ApiEnvelope(data=response, requestId=trace.request_id, trace=trace)


@router.post("/context", response_model=ApiEnvelope)
async def context(payload: RetrieveRequest, request: Request) -> ApiEnvelope[dict]:
    trace = build_trace_context(request)
    retrieval_service = get_retrieval_service()
    upstream_headers = build_upstream_headers(trace, conversation_id=payload.conversation_id)
    try:
        rewrite_result, candidates = await retrieval_service.search_candidates(
            payload,
            get_knowledge_client(),
            upstream_headers,
            cache_service=get_retrieval_cache(),
        )
        response = retrieval_service.build_context(payload, candidates, rewrite_result.rewritten_query, backend_used=KNOWLEDGE_SEARCH_BACKEND)
    except (httpx.HTTPError, KnowledgeServiceProtocolError):
        response = retrieval_service.build_context(
            payload,
            [],
            retrieval_service.rewrite_query(payload).rewritten_query,
            backend_used=KNOWLEDGE_UNAVAILABLE_BACKEND,
        )
    return ApiEnvelope(data=response, requestId=trace.request_id, trace=trace)


class FaqMatchQuery(BaseModel):
    query: str = Field(min_length=1)


@router.post("/faq/match", response_model=ApiEnvelope)
async def faq_match(payload: FaqMatchQuery, request: Request) -> ApiEnvelope[dict]:
    """L1 FAQ cache match only - no L2 retrieval fallback."""
    trace = build_trace_context(request)
    faq_result = get_faq_cache().match(payload.query)
    if faq_result is not None:
        entry = faq_result.entry
        response_data = {
            "matched": True,
            "answer": entry.answer,
            "matchReason": faq_result.match_reason,
            "tokenSaved": faq_result.token_saved_estimate,
            "category": entry.category,
            "prerequisites": entry.prerequisites or [],
            "relatedTopics": entry.related_topics or [],
            "documentRefs": [{"docId": r.doc_id, "title": r.title, **({"url": r.url} if r.url else {})} for r in (entry.document_refs or [])],
        }
        return ApiEnvelope(
            data=response_data,
            requestId=trace.request_id,
            trace=trace,
        )
    return ApiEnvelope(
        data={"matched": False, "answer": None, "matchReason": None, "tokenSaved": 0,
              "category": None, "prerequisites": [], "relatedTopics": [], "documentRefs": []},
        requestId=trace.request_id,
        trace=trace,
    )


@router.delete("/cache", response_model=ApiEnvelope)
async def clear_cache(request: Request) -> ApiEnvelope[dict]:
    trace = build_trace_context(request)
    cleared = get_retrieval_cache().clear_prefix()
    return ApiEnvelope(data={"clearedEntries": cleared}, requestId=trace.request_id, trace=trace)


@router.post("/answer", response_model=ApiEnvelope)
async def answer(payload: AnswerRequest, request: Request) -> ApiEnvelope[dict]:
    trace = build_trace_context(request)

    faq_result = get_faq_cache().match(payload.query)
    if faq_result is not None:
        return ApiEnvelope(
            data={
                "query": payload.query,
                "rewrittenQuery": payload.query,
                "backendUsed": "L1_FAQ_CACHE",
                "answer": faq_result.entry.answer,
                "citations": [],
                "coverageNotes": f"L1 exact match triggered: {faq_result.match_reason}, saved ~{faq_result.token_saved_estimate} tokens",
                "degraded": False,
                "context": None,
                "cache": {"layer": "L1_FAQ", "tokenSaved": faq_result.token_saved_estimate},
            },
            requestId=trace.request_id,
            trace=trace,
        )

    retrieval_service = get_retrieval_service()
    upstream_headers = build_upstream_headers(trace, conversation_id=payload.conversation_id)
    try:
        rewrite_result, candidates = await retrieval_service.search_candidates(
            payload,
            get_knowledge_client(),
            upstream_headers,
            cache_service=get_retrieval_cache(),
        )
        retrieval = retrieval_service.build_response(payload, candidates, rewrite_result.rewritten_query, include_context=True, backend_used=KNOWLEDGE_SEARCH_BACKEND)
    except (httpx.HTTPError, KnowledgeServiceProtocolError) as exc:
        UPSTREAM_ERRORS_TOTAL.inc()
        rewrite_result = retrieval_service.rewrite_query(payload)
        retrieval = retrieval_service.build_response(
            payload,
            [],
            rewritten_query=rewrite_result.rewritten_query,
            degraded=True,
            degradation_note=_build_degradation_note(exc),
            include_context=True,
            backend_used=KNOWLEDGE_UNAVAILABLE_BACKEND,
        )
    response = get_answer_composer().compose(payload.query, retrieval, style=payload.style)
    return ApiEnvelope(data=response, requestId=trace.request_id, trace=trace)