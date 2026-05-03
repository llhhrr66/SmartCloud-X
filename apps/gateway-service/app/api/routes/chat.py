from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request

from app.api.common import canonical_error
from app.services.auth import GatewaySubject, require_user_subject
from app.services.logging import log_event
from app.services.request_context import get_request_identity
from app.services.streaming import tee_sse_stream


router = APIRouter(prefix="/api/v1", tags=["chat"])


LEGACY_SCENE_ALIASES = {
    "general": "customer_service",
}


def _normalize_scene(value: object) -> object:
    if not isinstance(value, str):
        return value
    normalized = value.strip()
    if not normalized:
        return value
    return LEGACY_SCENE_ALIASES.get(normalized, normalized)


async def _capture_citations(
    request: Request,
    subject: GatewaySubject,
    stream,
):
    store = request.app.state.gateway_services.store
    citation_count = 0
    event_count = 0
    stream_failed = False
    retrieval_degraded = False

    def _is_real_citation_entry(citation: dict) -> bool:
        if not isinstance(citation, dict):
            return False
        citation_id = citation.get("citation_id") or citation.get("id")
        if not citation_id:
            return False
        backend_used = citation.get("backend_used") or citation.get("backendUsed")
        source_id = citation.get("source_id") or citation.get("sourceId")
        doc_id = citation.get("doc_id") or citation.get("docId")
        chunk_id = citation.get("chunk_id") or citation.get("chunkId")
        uri = citation.get("uri")
        if isinstance(uri, str) and uri.startswith("baseline://"):
            return False
        has_real_source_evidence = any(
            value
            for value in (
                backend_used,
                source_id,
                doc_id,
                chunk_id,
            )
        )
        if has_real_source_evidence:
            return True
        return isinstance(uri, str) and uri.strip() != ""

    def _extract_citations(event_name: str, payload: dict) -> list[dict]:
        citations: list[dict] = []
        if event_name in {"citation", "citation.delta"}:
            if isinstance(payload.get("citations"), list):
                for citation in payload.get("citations") or []:
                    if isinstance(citation, dict):
                        citations.append(citation)
            elif isinstance(payload, dict):
                citations.append(payload)
        elif event_name in {"message.completed", "done"}:
            for citation in payload.get("citations") or []:
                if isinstance(citation, dict):
                    citations.append(citation)
        return citations

    async def on_event(event_name: str, payload: dict) -> None:
        nonlocal citation_count, event_count, stream_failed, retrieval_degraded
        event_count += 1
        request.state.sse_event_count = event_count

        if event_name == "retrieval":
            retrieval_degraded = bool(payload.get("degraded"))
            request.state.retrieval_degraded = retrieval_degraded
            request.state.retrieval_backend_used = payload.get("backend_used")
        elif event_name == "message.error":
            stream_failed = True
            request.state.stream_failed = True

        citations = [citation for citation in _extract_citations(event_name, payload) if _is_real_citation_entry(citation)]
        if citations and not stream_failed:
            citation_count += len(citations)
            store.remember_citations(subject.tenant_id, subject.subject_id, citations)
        request.state.citation_cache_count = citation_count

    async for chunk in tee_sse_stream(stream, on_event):
        yield chunk


async def _ensure_conversation_id(request: Request, payload: dict) -> str | None:
    conversation_id = payload.get("conversation_id")
    if isinstance(conversation_id, str) and conversation_id.strip():
        return conversation_id.strip()

    services = request.app.state.gateway_services
    session_payload: dict[str, object] = {}
    scene = _normalize_scene(payload.get("scene"))
    if isinstance(scene, str) and scene.strip():
        session_payload["scene"] = scene.strip()

    context = payload.get("context")
    if isinstance(context, dict) and context:
        session_payload["initial_context"] = context

    response = await services.http.request_json(
        "orchestrator-service",
        "POST",
        "/api/v1/chat/sessions",
        headers={
            services.settings.request_id_header: request.state.request_id,
            services.settings.trace_id_header: request.state.trace_id,
            "Content-Type": "application/json",
        },
        content=json.dumps(session_payload, ensure_ascii=False).encode("utf-8"),
        request_identity=get_request_identity(request),
    )
    data = response.get("data") if isinstance(response.get("data"), dict) else response
    created_conversation_id = data.get("conversation_id") if isinstance(data, dict) else None
    return created_conversation_id if isinstance(created_conversation_id, str) and created_conversation_id.strip() else None


async def _build_internal_chat_payload(payload: dict, subject: GatewaySubject, request: Request) -> dict:
    chat_request = dict(payload)
    normalized_scene = _normalize_scene(chat_request.get("scene"))
    if isinstance(normalized_scene, str) and normalized_scene.strip():
        chat_request["scene"] = normalized_scene.strip()
    conversation_id = await _ensure_conversation_id(request, chat_request)
    if conversation_id:
        chat_request["conversation_id"] = conversation_id
    context = chat_request.get("context") if isinstance(chat_request.get("context"), dict) else {}
    context.setdefault("user_id", subject.subject_id)
    context.setdefault("tenant_id", subject.tenant_id or "default")
    chat_request["context"] = context
    chat_request["stream"] = bool(chat_request.get("stream", False))
    return {
        "request_id": request.state.request_id,
        "trace_id": request.state.trace_id,
        "tenant_id": subject.tenant_id or "default",
        "user": {
            "user_id": subject.subject_id,
            "account_id": subject.account_id,
            "roles": subject.roles or ["end_user"],
            "permissions": subject.permissions,
        },
        "chat_request": chat_request,
    }


@router.get("/chat/sessions")
async def list_sessions(request: Request, _=Depends(require_user_subject)):
    return await request.app.state.gateway_services.http.proxy(request, "orchestrator-service")


@router.post("/chat/sessions")
async def create_session(request: Request, _=Depends(require_user_subject)):
    payload = await request.json()
    payload["scene"] = _normalize_scene(payload.get("scene"))
    initial_context = payload.get("initial_context")
    if isinstance(initial_context, str):
        payload["initial_context"] = {"history_summary": initial_context}
    request._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")  # type: ignore[attr-defined]
    return await request.app.state.gateway_services.http.proxy(request, "orchestrator-service")


@router.get("/chat/sessions/{conversation_id}")
async def get_session(request: Request, conversation_id: str, _=Depends(require_user_subject)):
    return await request.app.state.gateway_services.http.proxy(request, "orchestrator-service")


@router.patch("/chat/sessions/{conversation_id}")
async def patch_session(request: Request, conversation_id: str, _=Depends(require_user_subject)):
    return await request.app.state.gateway_services.http.proxy(request, "orchestrator-service")


@router.delete("/chat/sessions/{conversation_id}")
async def delete_session(request: Request, conversation_id: str, _=Depends(require_user_subject)):
    return await request.app.state.gateway_services.http.proxy(request, "orchestrator-service")


@router.get("/chat/sessions/{conversation_id}/messages")
async def get_messages(request: Request, conversation_id: str, _=Depends(require_user_subject)):
    return await request.app.state.gateway_services.http.proxy(request, "orchestrator-service")


@router.post("/chat/sessions/{conversation_id}/archive")
async def archive_session(request: Request, conversation_id: str, _=Depends(require_user_subject)):
    return await request.app.state.gateway_services.http.proxy(request, "orchestrator-service")


@router.post("/chat/sessions/{conversation_id}/restore")
async def restore_session(request: Request, conversation_id: str, _=Depends(require_user_subject)):
    return await request.app.state.gateway_services.http.proxy(request, "orchestrator-service")


@router.post("/chat/sessions/{conversation_id}/retry")
async def retry_session(request: Request, conversation_id: str, _=Depends(require_user_subject)):
    return await request.app.state.gateway_services.http.proxy(request, "orchestrator-service")


@router.post("/chat/sessions/{conversation_id}/cancel")
async def cancel_session(request: Request, conversation_id: str, _=Depends(require_user_subject)):
    return await request.app.state.gateway_services.http.proxy(request, "orchestrator-service")


@router.post("/chat/completions")
async def chat_completions(request: Request, subject: GatewaySubject = Depends(require_user_subject)):
    body = await request.body()
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        return canonical_error(
            request_id=request.state.request_id,
            status_code=400,
            code=4001001,
            message="request validation failed",
            error={"type": "validation_error", "field": "body", "reason": "must be an object"},
        )

    internal_payload = await _build_internal_chat_payload(payload, subject, request)
    internal_body = json.dumps(internal_payload, ensure_ascii=False).encode("utf-8")
    internal_path = "/internal/v1/orchestrator/chat"

    if payload.get("stream"):
        request.scope["query_string"] = b""
        request.state.sse_event_count = 0
        request.state.citation_cache_count = 0
        request.state.stream_failed = False
        request.state.retrieval_degraded = False
        request.state.retrieval_backend_used = None
        identity = get_request_identity(request)

        def on_stream_start(upstream_status: int, headers: dict[str, str]) -> None:
            log_event(
                "stream_started",
                request_id=identity.request_id,
                trace_id=identity.trace_id,
                method=request.method,
                path=request.url.path,
                subject_type=identity.subject_type,
                subject_id=identity.subject_id,
                tenant_id=identity.tenant_id,
                upstream_service="orchestrator-service",
                upstream_status=upstream_status,
                content_type=headers.get("content-type"),
            )

        def on_stream_end(summary: dict) -> None:
            log_event(
                summary.get("event", "stream_completed"),
                request_id=identity.request_id,
                trace_id=identity.trace_id,
                method=request.method,
                path=request.url.path,
                subject_type=identity.subject_type,
                subject_id=identity.subject_id,
                tenant_id=identity.tenant_id,
                upstream_service="orchestrator-service",
                upstream_status=summary.get("upstream_status"),
                upstream_latency_ms=summary.get("upstream_latency_ms"),
                total_bytes=summary.get("total_bytes"),
                event_count=getattr(request.state, "sse_event_count", 0),
                citation_cache_count=getattr(request.state, "citation_cache_count", 0),
                retrieval_degraded=getattr(request.state, "retrieval_degraded", False),
                retrieval_backend_used=getattr(request.state, "retrieval_backend_used", None),
                stream_failed=getattr(request.state, "stream_failed", False),
            )

        return await request.app.state.gateway_services.http.stream_proxy(
            request,
            "orchestrator-service",
            path=internal_path,
            content=internal_body,
            transform_stream=lambda stream: _capture_citations(request, subject, stream),
            timeout=60,
            on_stream_start=on_stream_start,
            on_stream_end=on_stream_end,
        )
    return await request.app.state.gateway_services.http.proxy(
        request,
        "orchestrator-service",
        path=internal_path,
        content=internal_body,
    )
