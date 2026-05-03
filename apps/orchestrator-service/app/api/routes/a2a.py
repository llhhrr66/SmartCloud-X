from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.routes.orchestration import _conversation_store, _execute_message, _response_message_status
from app.core.config import get_settings
from app.models.common import TraceContext
from app.models.orchestration import MessageRequest
from app.services.conversation_store import ConversationStore


router = APIRouter(tags=["a2a"])
jsonrpc_router = APIRouter(tags=["a2a"])


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text_part(text: str) -> dict[str, str]:
    return {"type": "text", "text": text}


def _message_record(role: str, *, text: str, message_id: str, context_id: str, task_id: str) -> dict[str, Any]:
    return {
        "role": role,
        "messageId": message_id,
        "contextId": context_id,
        "taskId": task_id,
        "parts": [_text_part(text)],
    }


def _state_from_response(status: str, response) -> str:
    if status in {"failed", "cancelled"}:
        return "failed"
    if response.pending_user_actions or response.pending_actions:
        return "input-required"
    return "completed"


def _state_from_message_status(
    status: str,
    *,
    finish_reason: str | None = None,
    pending_actions: list[str] | None = None,
) -> str:
    if status == "need_user_input":
        return "input-required"
    if pending_actions:
        return "input-required"
    if finish_reason in {"collect-user-input", "requires_input"}:
        return "input-required"
    return {
        "completed": "completed",
        "success": "completed",
        "failed": "failed",
        "cancelled": "failed",
        "handoff": "working",
        "running": "working",
    }.get(status, "working")


def _load_messages_until_found(
    conversation_id: str,
    *,
    user_message_id: str,
    assistant_message_id: str,
) -> tuple[Any, Any]:
    cursor: str | None = None
    while True:
        page = _conversation_store.list_messages(conversation_id, cursor=cursor, page_size=200)
        messages_by_id = {item.message_id: item for item in page.items}
        user_message = messages_by_id.get(user_message_id)
        assistant_message = messages_by_id.get(assistant_message_id)
        if user_message is not None and assistant_message is not None:
            return user_message, assistant_message
        if not page.has_more or not page.next_cursor:
            break
        cursor = page.next_cursor
    raise KeyError(f"task '{user_message_id}' was not found in conversation '{conversation_id}'")


def _a2a_task(
    conversation_id: str,
    request_message_id: str,
    response,
    status: str,
    *,
    user_text: str,
) -> dict[str, Any]:
    assistant_message_id = ConversationStore.assistant_message_id(request_message_id)
    assistant_text = response.final_response_summary or response.route.summary
    return {
        "id": request_message_id,
        "contextId": conversation_id,
        "status": {
            "state": _state_from_response(status, response),
            "timestamp": _iso_now(),
            "message": _message_record(
                "agent",
                text=assistant_text,
                message_id=assistant_message_id,
                context_id=conversation_id,
                task_id=request_message_id,
            ),
        },
        "artifacts": [
            {
                "artifactId": "assistant-response",
                "name": "assistant-response",
                "parts": [_text_part(assistant_text)],
            }
        ],
        "history": [
            _message_record(
                "user",
                text=user_text,
                message_id=request_message_id,
                context_id=conversation_id,
                task_id=request_message_id,
            ),
            _message_record(
                "agent",
                text=assistant_text,
                message_id=assistant_message_id,
                context_id=conversation_id,
                task_id=request_message_id,
            ),
        ],
        "metadata": {
            "primaryAgent": response.route.primary_agent,
            "nextAction": response.next_action,
            "pendingActions": list(response.pending_actions),
            "pendingUserActions": [item.model_dump(mode="json") for item in response.pending_user_actions],
            "review": response.review.model_dump(mode="json") if response.review else None,
        },
    }


def _task_from_store(conversation_id: str, task_id: str) -> dict[str, Any]:
    resolved_request_id = _conversation_store.resolve_request_message_id(conversation_id, task_id)
    assistant_message_id = ConversationStore.assistant_message_id(resolved_request_id)
    user_message, assistant_message = _load_messages_until_found(
        conversation_id,
        user_message_id=resolved_request_id,
        assistant_message_id=assistant_message_id,
    )
    pending_actions = []
    conversation = _conversation_store.get(conversation_id) if hasattr(_conversation_store, "get") else None
    if conversation is not None:
        pending_actions = list(getattr(conversation, "pending_actions", []) or [])
    return {
        "id": resolved_request_id,
        "contextId": conversation_id,
        "status": {
            "state": _state_from_message_status(
                assistant_message.status,
                finish_reason=assistant_message.finish_reason,
                pending_actions=pending_actions,
            ),
            "timestamp": assistant_message.updated_at,
            "message": _message_record(
                "agent",
                text=assistant_message.content,
                message_id=assistant_message.message_id,
                context_id=conversation_id,
                task_id=resolved_request_id,
            ),
        },
        "artifacts": [
            {
                "artifactId": "assistant-response",
                "name": "assistant-response",
                "parts": [_text_part(assistant_message.content)],
            }
        ],
        "history": [
            _message_record(
                "user",
                text=user_message.content,
                message_id=user_message.message_id,
                context_id=conversation_id,
                task_id=resolved_request_id,
            ),
            _message_record(
                "agent",
                text=assistant_message.content,
                message_id=assistant_message.message_id,
                context_id=conversation_id,
                task_id=resolved_request_id,
            ),
        ],
        "metadata": {
            "assistantStatus": assistant_message.status,
            "finishReason": assistant_message.finish_reason,
            "agentName": assistant_message.agent_name,
            "citations": list(assistant_message.citations),
        },
    }


def _extract_text(message_payload: dict[str, Any]) -> str:
    if "parts" in message_payload:
        for part in message_payload.get("parts") or []:
            if isinstance(part, dict) and part.get("text"):
                return str(part["text"])
    content = message_payload.get("content")
    if isinstance(content, dict):
        for part in content.get("parts") or []:
            if isinstance(part, dict) and part.get("text"):
                return str(part["text"])
    if message_payload.get("text"):
        return str(message_payload["text"])
    raise ValueError("message payload did not contain a text part")


def _jsonrpc_error(request_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content={
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        },
    )


@router.get("/.well-known/agent-card.json")
def agent_card(request: Request) -> dict[str, Any]:
    base_url = str(request.base_url).rstrip("/")
    settings = get_settings()
    return {
        "name": "SmartCloud-X Orchestrator",
        "description": "A SmartCloud-X multi-agent orchestrator that routes cloud-service support tasks across billing, research, marketing, ICP, and support flows.",
        "version": settings.app_version,
        "url": f"{base_url}{settings.api_prefix}/a2a/jsonrpc",
        "provider": {"organization": "SmartCloud-X"},
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": True,
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "skills": [
            {
                "id": "smartcloud.orchestrator",
                "name": "SmartCloud Orchestrator",
                "description": "Routes multi-agent SmartCloud support tasks and returns structured task results.",
                "tags": ["billing", "research", "marketing", "support", "cloud"],
            }
        ],
    }


@jsonrpc_router.post("/a2a/jsonrpc")
def jsonrpc(payload: dict[str, Any], request: Request) -> JSONResponse:
    request_id = payload.get("id")
    if payload.get("jsonrpc") != "2.0":
        return _jsonrpc_error(request_id, -32600, "invalid jsonrpc version")
    method = payload.get("method")
    params = payload.get("params") or {}
    try:
        if method in {"SendMessage", "message/send"}:
            message_payload = params.get("message") or params.get("input")
            if not isinstance(message_payload, dict):
                raise ValueError("message payload is required")
            conversation_id = (
                params.get("contextId")
                or message_payload.get("contextId")
                or f"a2a_{uuid4().hex[:12]}"
            )
            text = _extract_text(message_payload)
            scene = params.get("metadata", {}).get("scene") or "customer_service"
            trace = TraceContext(
                requestId=request.headers.get("X-Request-Id", str(request_id or uuid4().hex)),
                conversationId=conversation_id,
                traceId=request.headers.get("X-Trace-Id", request.headers.get("X-Request-Id", str(request_id or uuid4().hex))),
            )
            _conversation, message_id, _assistant_message_id, response = _execute_message(
                conversation_id,
                MessageRequest(
                    user_query=text,
                    scene=scene,
                ),
                trace,
                strict_session=False,
            )
            status = _response_message_status(response)
            return JSONResponse(
                status_code=200,
                content={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"task": _a2a_task(conversation_id, message_id, response, status, user_text=text)},
                },
            )
        if method in {"GetTask", "tasks/get"}:
            conversation_id = params.get("contextId")
            task_id = params.get("id") or params.get("taskId")
            if not conversation_id or not task_id:
                raise ValueError("contextId and task id are required")
            return JSONResponse(
                status_code=200,
                content={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"task": _task_from_store(conversation_id, task_id)},
                },
            )
    except KeyError as exc:
        return _jsonrpc_error(request_id, -32004, str(exc))
    except ValueError as exc:
        return _jsonrpc_error(request_id, -32602, str(exc))
    except Exception as exc:  # noqa: BLE001 - jsonrpc surface should return protocol errors
        return _jsonrpc_error(request_id, -32000, str(exc))
    return _jsonrpc_error(request_id, -32601, f"unsupported method: {method}")
