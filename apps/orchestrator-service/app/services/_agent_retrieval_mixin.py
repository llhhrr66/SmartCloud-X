from __future__ import annotations

from typing import Any

from app.models.common import TraceContext
from app.models.orchestration import (
    AgentExecutionResult,
    AgentTask,
    MessageRequest,
    RetrievalResult,
    RetrievalSource,
)
from app.services.rag_client import (
    RagClientProtocolError,
    RagClientResponseError,
    RagClientUnavailableError,
)


class _AgentRetrievalMixin:
    """RAG retrieval helpers used by ``AgentRuntime``.

    Expects the host class to provide ``self._settings`` and ``self._rag_client``.
    """

    def _run_retrieval(
        self,
        task: AgentTask,
        request: MessageRequest,
        trace: TraceContext | None,
    ) -> dict[str, Any]:
        if not request.user_profile.user_id:
            failure_execution = self._missing_user_context_execution(task)
            return {
                "result": None,
                "citations": [],
                "risk_flags": ["missing_user_context"],
                "trace_tags": [task.agent, "missing_user_context"],
                "failure_execution": failure_execution,
            }
        payload = self._build_retrieval_payload(task, request)
        try:
            response = self._rag_client.retrieve(
                payload,
                trace=trace,
                tenant_id=request.user_profile.tenant_id,
                authorization=None,
                timeout=self._settings.request_timeout_ms / 1000,
            )
        except RagClientResponseError as exc:
            failure_execution = self._retrieval_failed_execution(task, message=exc.message)
            return {
                "result": None,
                "citations": [],
                "risk_flags": ["retrieval_failed"],
                "trace_tags": [task.agent, "retrieval_failed"],
                "failure_execution": failure_execution,
            }
        except (RagClientUnavailableError, RagClientProtocolError) as exc:
            failure_execution = self._retrieval_failed_execution(task, message=str(exc))
            return {
                "result": None,
                "citations": [],
                "risk_flags": ["retrieval_failed"],
                "trace_tags": [task.agent, "retrieval_failed"],
                "failure_execution": failure_execution,
            }
        retrieval_result = self._map_retrieval_result(response, fallback_query=request.user_query)
        return {
            "result": retrieval_result,
            "citations": self._citations_from_retrieval_sources(retrieval_result.sources),
            "risk_flags": ["retrieval_degraded"] if retrieval_result.degraded else [],
            "trace_tags": [task.agent, "retrieval", retrieval_result.backend_used],
            "failure_execution": None,
        }

    @staticmethod
    def _build_retrieval_payload(task: AgentTask, request: MessageRequest) -> dict[str, Any]:
        return {
            "query": request.user_query,
            "conversationId": request.trace.conversation_id if request.trace and request.trace.conversation_id else None,
            "messageId": request.message_id,
            "scene": request.scene,
            "agent": task.agent,
            "userId": request.user_profile.user_id,
            "tenantId": request.user_profile.tenant_id,
            "accountId": request.user_profile.account_id,
            "retrievalContext": list(request.retrieval_context),
            "attachments": list(request.attachments),
            "sessionContext": request.session_context.model_dump(mode="json"),
        }

    @staticmethod
    def _map_retrieval_result(payload: dict[str, Any], *, fallback_query: str) -> RetrievalResult:
        sources_payload = payload.get("sources") if isinstance(payload.get("sources"), list) else []
        return RetrievalResult(
            query=str(payload.get("query") or fallback_query),
            rewritten_query=str(
                payload.get("rewrittenQuery") or payload.get("rewritten_query") or payload.get("query") or fallback_query
            ),
            degraded=bool(payload.get("degraded", False)),
            degradation_note=(
                str(payload.get("degradationNote"))
                if payload.get("degradationNote") is not None
                else (
                    str(payload.get("degradation_note"))
                    if payload.get("degradation_note") is not None
                    else None
                )
            ),
            backend_used=str(payload.get("backendUsed") or payload.get("backend_used") or "rag-service"),
            sources=[
                _AgentRetrievalMixin._map_retrieval_source(item)
                for item in sources_payload
                if isinstance(item, dict)
            ],
            raw_meta={
                key: value
                for key, value in payload.items()
                if key not in {
                    "query",
                    "rewrittenQuery",
                    "rewritten_query",
                    "degraded",
                    "degradationNote",
                    "degradation_note",
                    "backendUsed",
                    "backend_used",
                    "sources",
                }
            },
        )

    @staticmethod
    def _map_retrieval_source(payload: dict[str, Any]) -> RetrievalSource:
        return RetrievalSource(
            source_id=str(payload.get("sourceId") or payload.get("source_id") or payload.get("id") or "unknown-source"),
            source_type=str(payload.get("sourceType") or payload.get("source_type") or "knowledge_base"),
            title=str(payload.get("title") or "Untitled source"),
            doc_id=(
                str(payload.get("docId") or payload.get("doc_id"))
                if (payload.get("docId") or payload.get("doc_id")) is not None
                else None
            ),
            chunk_id=(
                str(payload.get("chunkId") or payload.get("chunk_id"))
                if (payload.get("chunkId") or payload.get("chunk_id")) is not None
                else None
            ),
            score=float(payload.get("score")) if payload.get("score") is not None else None,
            uri=(str(payload.get("uri")) if payload.get("uri") is not None else None),
            snippet=(str(payload.get("snippet")) if payload.get("snippet") is not None else None),
            backend_used=(
                str(payload.get("backendUsed") or payload.get("backend_used"))
                if (payload.get("backendUsed") or payload.get("backend_used")) is not None
                else None
            ),
            domain=(str(payload.get("domain")) if payload.get("domain") is not None else None),
        )

    @staticmethod
    def _citations_from_retrieval_sources(sources: list[RetrievalSource]) -> list[str]:
        citations: list[str] = []
        for source in sources:
            citation = _AgentRetrievalMixin._citation_from_source(source)
            if citation is None or citation in citations:
                continue
            citations.append(citation)
        return citations

    @staticmethod
    def _citation_from_source(source: RetrievalSource) -> str | None:
        if isinstance(source.uri, str) and source.uri.strip() and not source.uri.startswith("baseline://"):
            return source.uri.strip()
        return None

    @staticmethod
    def _missing_user_context_execution(task: AgentTask) -> AgentExecutionResult:
        return AgentExecutionResult(
            agent=task.agent,
            status="failed",
            reasoning_summary="检索场景缺少 user_id，无法建立真实用户上下文。",
            tool_calls=[],
            citations=[],
            retrieval_result=None,
            confidence=0.2,
            final_answer=f"{task.agent} 缺少用户上下文，暂时无法完成检索，请补充后重试。",
            action_required="retry-or-escalate",
            risk_flags=["missing_user_context"],
            trace_tags=[task.agent, "missing_user_context"],
            handoff_payload={},
        )

    @staticmethod
    def _retrieval_failed_execution(task: AgentTask, *, message: str | None = None) -> AgentExecutionResult:
        detail = message.strip() if isinstance(message, str) and message.strip() else None
        return AgentExecutionResult(
            agent=task.agent,
            status="failed",
            reasoning_summary=detail or "RAG/Knowledge 检索链路当前不可用。",
            tool_calls=[],
            citations=[],
            retrieval_result=None,
            confidence=0.2,
            final_answer=f"{task.agent} 当前无法完成实时检索，请稍后重试。",
            action_required="retry-or-escalate",
            risk_flags=["retrieval_failed"],
            trace_tags=[task.agent, "retrieval_failed"],
            handoff_payload={},
        )
