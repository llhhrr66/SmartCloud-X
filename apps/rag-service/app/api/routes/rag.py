import httpx
from fastapi import APIRouter, Request

from app.api.dependencies import build_trace_context, build_upstream_headers
from app.core.metrics import UPSTREAM_ERRORS_TOTAL
from app.models.common import ApiEnvelope
from app.models.rag import AnswerRequest, RetrieveRequest
from app.services.answer import get_answer_composer
from app.services.cache import get_retrieval_cache
from app.services.providers import get_knowledge_client
from app.services.knowledge_client import KnowledgeServiceProtocolError
from app.services.retrieval import get_retrieval_service

router = APIRouter()


def _build_degradation_note(exc: Exception) -> str:
    if isinstance(exc, KnowledgeServiceProtocolError):
        return str(exc)
    return f"knowledge-service unavailable: {exc.__class__.__name__}"


@router.get("/capabilities", response_model=ApiEnvelope)
def capabilities(request: Request) -> ApiEnvelope[dict]:
    trace = build_trace_context(request)
    return ApiEnvelope(
        data={
            "rewrite": "keyword-and-synonym",
            "retrieval": "knowledge-service-search",
            "rerank": "deterministic-baseline",
            "answering": "template-composer",
            "diagnostics": "rewrite-filters-candidate-inspection",
            "cache": get_retrieval_cache().describe()["backend"],
        },
        requestId=trace.request_id,
        trace=trace,
    )


@router.post("/retrieve", response_model=ApiEnvelope)
async def retrieve(payload: RetrieveRequest, request: Request) -> ApiEnvelope[dict]:
    trace = build_trace_context(request)
    retrieval_service = get_retrieval_service()
    upstream_headers = build_upstream_headers(trace, conversation_id=payload.conversation_id)
    try:
        rewrite, candidates = await retrieval_service.search_candidates(
            payload,
            get_knowledge_client(),
            upstream_headers,
            cache_service=get_retrieval_cache(),
        )
        response = retrieval_service.build_response(payload, candidates, rewrite.rewritten_query)
    except (httpx.HTTPError, KnowledgeServiceProtocolError) as exc:
        UPSTREAM_ERRORS_TOTAL.inc()
        rewrite = retrieval_service.rewrite_query(payload.query)
        response = retrieval_service.build_response(
            payload,
            [],
            rewritten_query=rewrite.rewritten_query,
            degraded=True,
            degradation_note=_build_degradation_note(exc),
        )
    return ApiEnvelope(data=response, requestId=trace.request_id, trace=trace)


@router.post("/diagnose", response_model=ApiEnvelope)
async def diagnose(payload: RetrieveRequest, request: Request) -> ApiEnvelope[dict]:
    trace = build_trace_context(request)
    retrieval_service = get_retrieval_service()
    upstream_headers = build_upstream_headers(trace, conversation_id=payload.conversation_id)
    try:
        rewrite, candidates = await retrieval_service.search_candidates(
            payload,
            get_knowledge_client(),
            upstream_headers,
            cache_service=get_retrieval_cache(),
        )
        response = retrieval_service.build_diagnostic(payload, candidates, rewrite)
    except (httpx.HTTPError, KnowledgeServiceProtocolError) as exc:
        UPSTREAM_ERRORS_TOTAL.inc()
        rewrite = retrieval_service.rewrite_query(payload.query)
        response = retrieval_service.build_diagnostic(
            payload,
            [],
            rewrite,
            degraded=True,
            degradation_note=_build_degradation_note(exc),
        )
    return ApiEnvelope(data=response, requestId=trace.request_id, trace=trace)


@router.post("/answer", response_model=ApiEnvelope)
async def answer(payload: AnswerRequest, request: Request) -> ApiEnvelope[dict]:
    trace = build_trace_context(request)
    retrieval_service = get_retrieval_service()
    upstream_headers = build_upstream_headers(trace, conversation_id=payload.conversation_id)
    try:
        rewrite, candidates = await retrieval_service.search_candidates(
            payload,
            get_knowledge_client(),
            upstream_headers,
            cache_service=get_retrieval_cache(),
        )
        retrieval = retrieval_service.build_response(payload, candidates, rewrite.rewritten_query)
    except (httpx.HTTPError, KnowledgeServiceProtocolError) as exc:
        UPSTREAM_ERRORS_TOTAL.inc()
        rewrite = retrieval_service.rewrite_query(payload.query)
        retrieval = retrieval_service.build_response(
            payload,
            [],
            rewritten_query=rewrite.rewritten_query,
            degraded=True,
            degradation_note=_build_degradation_note(exc),
        )
    response = get_answer_composer().compose(payload.query, retrieval, style=payload.style)
    return ApiEnvelope(data=response, requestId=trace.request_id, trace=trace)
