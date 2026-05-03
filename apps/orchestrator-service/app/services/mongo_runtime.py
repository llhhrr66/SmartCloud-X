from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from pymongo import AsyncMongoClient

from app.core.config import Settings
from app.models.common import TraceContext
from app.models.orchestration import (
    ChatMessageRecord,
    ConversationRecord,
    MessageRequest,
    OrchestratorResponse,
    SessionContext,
)


class ConversationMongoRuntimeError(RuntimeError):
    pass


class DisabledConversationMongoRuntime:
    enabled = False

    def persist_exchange(self, **_: Any) -> None:
        return None

    def persist_assistant_message(self, **_: Any) -> None:
        return None

    def delete_exchange(self, **_: Any) -> None:
        return None

    def delete_assistant_continuation(self, **_: Any) -> None:
        return None

    def fetch_messages(self, conversation_id: str) -> list[ChatMessageRecord] | None:
        return None

    def get_request_snapshot(self, conversation_id: str, *, message_id: str) -> MessageRequest | None:
        return None

    def describe_backend(self) -> dict[str, object]:
        return {
            "backend": "inactive",
            "configured": False,
            "ready": False,
            "degradedFrom": None,
            "backendError": None,
            "database": None,
            "collections": {
                "conversation_messages": "conversation_messages",
                "agent_reasoning_logs": "agent_reasoning_logs",
                "raw_tool_payloads": "raw_tool_payloads",
                "session_snapshots": "session_snapshots",
            },
        }

    def clear(self) -> None:
        return None

    def close(self) -> None:
        return None


class UnavailableConversationMongoRuntime(DisabledConversationMongoRuntime):
    def __init__(self, error: str, *, database_name: str | None = None) -> None:
        self._error = error
        self._database_name = database_name

    def describe_backend(self) -> dict[str, object]:
        description = super().describe_backend()
        description.update(
            {
                "backend": "mongodb",
                "configured": True,
                "ready": False,
                "degradedFrom": "mongodb",
                "backendError": self._error,
                "database": self._database_name,
            }
        )
        return description


@dataclass
class ConversationMongoRuntime:
    client: AsyncMongoClient
    database_name: str
    loop: asyncio.AbstractEventLoop

    enabled = True

    @classmethod
    async def connect(cls, settings: Settings) -> "ConversationMongoRuntime":
        client = AsyncMongoClient(settings.mongodb_uri)
        await client.aconnect()
        return cls(
            client=client,
            database_name=settings.mongodb_database,
            loop=asyncio.get_running_loop(),
        )

    @property
    def database(self):
        return self.client[self.database_name]

    def _run(self, coro):
        # AsyncMongoClient is bound to the loop where it was created (`self.loop`).
        # Sync callers (FastAPI sync routes running in threadpool, or pure sync code)
        # must marshal coroutines back to that loop instead of spawning a fresh one.
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if current_loop is self.loop:
            # Caller is already on the runtime's loop — they should await the async
            # variant directly instead of using this sync bridge.
            coro.close()
            raise RuntimeError(
                "ConversationMongoRuntime sync bridge cannot run inside its owning event loop; "
                "await the async variant directly"
            )

        if not self.loop.is_running():
            coro.close()
            raise RuntimeError("ConversationMongoRuntime owning event loop is not running")

        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result()

    def persist_exchange(
        self,
        *,
        record: ConversationRecord,
        user_message: ChatMessageRecord,
        assistant_message: ChatMessageRecord,
        sequence_numbers: dict[str, int],
        message_request: MessageRequest,
        response: OrchestratorResponse | None,
        session_context: SessionContext,
        trace: TraceContext | None,
    ) -> dict[str, object]:
        try:
            return self._run(
                self.apersist_exchange(
                    record=record,
                    user_message=user_message,
                    assistant_message=assistant_message,
                    sequence_numbers=sequence_numbers,
                    message_request=message_request,
                    response=response,
                    session_context=session_context,
                    trace=trace,
                )
            )
        except Exception as exc:
            raise ConversationMongoRuntimeError(
                f"MongoDB conversation document store unavailable: {exc}"
            ) from exc

    async def apersist_exchange(
        self,
        *,
        record: ConversationRecord,
        user_message: ChatMessageRecord,
        assistant_message: ChatMessageRecord,
        sequence_numbers: dict[str, int],
        message_request: MessageRequest,
        response: OrchestratorResponse | None,
        session_context: SessionContext,
        trace: TraceContext | None,
    ) -> dict[str, object]:
        previous_snapshot = await self.database["session_snapshots"].find_one({"_id": record.conversation_id})
        for message in (user_message, assistant_message):
            await self.database["conversation_messages"].replace_one(
                {"_id": message.message_id},
                {
                    "_id": message.message_id,
                    "conversation_id": record.conversation_id,
                    "sequence_no": sequence_numbers[message.message_id],
                    "role": message.role,
                    "created_at": message.created_at,
                    "updated_at": message.updated_at,
                    "payload": message.model_dump(mode="json"),
                },
                upsert=True,
            )

        await self._replace_execution_documents(
            conversation_id=record.conversation_id,
            assistant_message=assistant_message,
            response=response,
        )

        request_payload = message_request.model_dump(mode="json")
        snapshot_document = self._build_snapshot_document(
            record=record,
            session_context=session_context,
            request_snapshots={
                user_message.message_id: request_payload,
                assistant_message.message_id: request_payload,
            },
            response=response,
            trace=trace,
            updated_at=assistant_message.updated_at,
        )
        await self.database["session_snapshots"].replace_one(
            {"_id": record.conversation_id},
            snapshot_document,
            upsert=True,
        )
        return {"previous_session_snapshot": previous_snapshot}

    def persist_assistant_message(
        self,
        *,
        record: ConversationRecord,
        source_user_message_id: str,
        assistant_message: ChatMessageRecord,
        message_request: MessageRequest,
        response: OrchestratorResponse | None,
        session_context: SessionContext,
        trace: TraceContext | None,
    ) -> dict[str, object]:
        try:
            return self._run(
                self.apersist_assistant_message(
                    record=record,
                    source_user_message_id=source_user_message_id,
                    assistant_message=assistant_message,
                    message_request=message_request,
                    response=response,
                    session_context=session_context,
                    trace=trace,
                )
            )
        except Exception as exc:
            raise ConversationMongoRuntimeError(
                f"MongoDB conversation document store unavailable: {exc}"
            ) from exc

    async def apersist_assistant_message(
        self,
        *,
        record: ConversationRecord,
        source_user_message_id: str,
        assistant_message: ChatMessageRecord,
        message_request: MessageRequest,
        response: OrchestratorResponse | None,
        session_context: SessionContext,
        trace: TraceContext | None,
    ) -> dict[str, object]:
        previous_snapshot = await self.database["session_snapshots"].find_one({"_id": record.conversation_id})
        sequence_no = await self._assistant_sequence_number(
            conversation_id=record.conversation_id,
            assistant_message_id=assistant_message.message_id,
        )
        await self.database["conversation_messages"].replace_one(
            {"_id": assistant_message.message_id},
            {
                "_id": assistant_message.message_id,
                "conversation_id": record.conversation_id,
                "sequence_no": sequence_no,
                "role": assistant_message.role,
                "created_at": assistant_message.created_at,
                "updated_at": assistant_message.updated_at,
                "payload": assistant_message.model_dump(mode="json"),
            },
            upsert=True,
        )

        await self._replace_execution_documents(
            conversation_id=record.conversation_id,
            assistant_message=assistant_message,
            response=response,
        )

        request_payload = message_request.model_dump(mode="json")
        request_snapshots = dict((previous_snapshot or {}).get("request_snapshots") or {})
        request_snapshots[source_user_message_id] = request_payload
        request_snapshots[assistant_message.message_id] = request_payload
        snapshot_document = self._build_snapshot_document(
            record=record,
            session_context=session_context,
            request_snapshots=request_snapshots,
            response=response,
            trace=trace,
            updated_at=assistant_message.updated_at,
        )
        await self.database["session_snapshots"].replace_one(
            {"_id": record.conversation_id},
            snapshot_document,
            upsert=True,
        )
        return {"previous_session_snapshot": previous_snapshot}

    async def _replace_execution_documents(
        self,
        *,
        conversation_id: str,
        assistant_message: ChatMessageRecord,
        response: OrchestratorResponse | None,
    ) -> None:
        await self.database["agent_reasoning_logs"].delete_many(
            {"conversation_id": conversation_id, "assistant_message_id": assistant_message.message_id}
        )
        reasoning_documents, tool_documents = self._build_execution_documents(
            conversation_id=conversation_id,
            assistant_message=assistant_message,
            response=response,
        )
        if reasoning_documents:
            await self.database["agent_reasoning_logs"].insert_many(reasoning_documents)
        await self.database["raw_tool_payloads"].delete_many(
            {"conversation_id": conversation_id, "assistant_message_id": assistant_message.message_id}
        )
        if tool_documents:
            await self.database["raw_tool_payloads"].insert_many(tool_documents)

    @staticmethod
    def _build_execution_documents(
        *,
        conversation_id: str,
        assistant_message: ChatMessageRecord,
        response: OrchestratorResponse | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        reasoning_documents: list[dict[str, Any]] = []
        tool_documents: list[dict[str, Any]] = []
        for index, execution in enumerate(response.executions if response else [], start=1):
            reasoning_documents.append(
                {
                    "_id": f"{assistant_message.message_id}:{index}",
                    "conversation_id": conversation_id,
                    "assistant_message_id": assistant_message.message_id,
                    "agent": execution.agent,
                    "status": execution.status,
                    "reasoning_summary": execution.reasoning_summary,
                    "confidence": execution.confidence,
                    "final_answer": execution.final_answer,
                    "risk_flags": list(execution.risk_flags),
                    "trace_tags": list(execution.trace_tags),
                    "handoff_received_from": execution.handoff_received_from,
                    "next_agent": execution.next_agent,
                    "action_required": execution.action_required,
                    "handoff_reason": execution.handoff_reason,
                    "handoff_payload": dict(execution.handoff_payload),
                    "created_at": assistant_message.created_at,
                }
            )
            for tool_call in execution.tool_calls:
                tool_documents.append(
                    {
                        "_id": f"{conversation_id}:{assistant_message.message_id}:{tool_call.tool_call_id}",
                        "conversation_id": conversation_id,
                        "assistant_message_id": assistant_message.message_id,
                        "tool_call_id": tool_call.tool_call_id,
                        "tool_name": tool_call.tool_name,
                        "operation": tool_call.operation,
                        "status": tool_call.status,
                        "payload": dict(tool_call.payload),
                        "summary": tool_call.summary,
                        "citations": list(tool_call.citations),
                        "provider": tool_call.provider,
                        "error_detail": dict(tool_call.error_detail),
                        "session_context_patch": dict(tool_call.session_context_patch),
                        "idempotency_key": tool_call.idempotency_key,
                        "latency_ms": tool_call.latency_ms,
                        "retryable": tool_call.retryable,
                        "code": tool_call.code,
                        "success": tool_call.success,
                        "created_at": assistant_message.created_at,
                    }
                )
        return reasoning_documents, tool_documents

    @staticmethod
    def _build_snapshot_document(
        *,
        record: ConversationRecord,
        session_context: SessionContext,
        request_snapshots: dict[str, Any],
        response: OrchestratorResponse | None,
        trace: TraceContext | None,
        updated_at: str,
    ) -> dict[str, Any]:
        return {
            "_id": record.conversation_id,
            "conversation_id": record.conversation_id,
            "conversation_record": record.model_dump(mode="json"),
            "session_context": session_context.model_dump(mode="json"),
            "request_snapshots": request_snapshots,
            "state_snapshot": response.state_snapshot.model_dump(mode="json") if response and response.state_snapshot else None,
            "review": response.review.model_dump(mode="json") if response and response.review else None,
            "trace": trace.model_dump(mode="json") if trace else None,
            "updated_at": updated_at,
        }

    async def _assistant_sequence_number(
        self,
        *,
        conversation_id: str,
        assistant_message_id: str,
    ) -> int:
        existing = await self.database["conversation_messages"].find_one(
            {"_id": assistant_message_id},
            {"sequence_no": 1},
        )
        if existing is not None and isinstance(existing.get("sequence_no"), int):
            return int(existing["sequence_no"])
        latest = await self.database["conversation_messages"].find_one(
            {"conversation_id": conversation_id},
            sort=[("sequence_no", -1), ("_id", -1)],
        )
        return int((latest or {}).get("sequence_no", 0)) + 1

    def delete_exchange(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
        cleanup_state: dict[str, object] | None,
    ) -> None:
        try:
            self._run(
                self.adelete_exchange(
                    conversation_id=conversation_id,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    cleanup_state=cleanup_state,
                )
            )
        except Exception as exc:
            raise ConversationMongoRuntimeError(
                f"MongoDB conversation cleanup failed: {exc}"
            ) from exc

    def delete_assistant_continuation(
        self,
        *,
        conversation_id: str,
        assistant_message_id: str,
        cleanup_state: dict[str, object] | None,
    ) -> None:
        try:
            self._run(
                self.adelete_assistant_continuation(
                    conversation_id=conversation_id,
                    assistant_message_id=assistant_message_id,
                    cleanup_state=cleanup_state,
                )
            )
        except Exception as exc:
            raise ConversationMongoRuntimeError(
                f"MongoDB continuation cleanup failed: {exc}"
            ) from exc

    async def adelete_exchange(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
        cleanup_state: dict[str, object] | None,
    ) -> None:
        await self.database["conversation_messages"].delete_many(
            {"_id": {"$in": [user_message_id, assistant_message_id]}}
        )
        await self.database["agent_reasoning_logs"].delete_many(
            {"conversation_id": conversation_id, "assistant_message_id": assistant_message_id}
        )
        await self.database["raw_tool_payloads"].delete_many(
            {"conversation_id": conversation_id, "assistant_message_id": assistant_message_id}
        )
        previous_snapshot = (cleanup_state or {}).get("previous_session_snapshot")
        if previous_snapshot is None:
            await self.database["session_snapshots"].delete_one({"_id": conversation_id})
        else:
            await self.database["session_snapshots"].replace_one(
                {"_id": conversation_id},
                previous_snapshot,
                upsert=True,
            )

    async def adelete_assistant_continuation(
        self,
        *,
        conversation_id: str,
        assistant_message_id: str,
        cleanup_state: dict[str, object] | None,
    ) -> None:
        await self.database["conversation_messages"].delete_one({"_id": assistant_message_id})
        await self.database["agent_reasoning_logs"].delete_many(
            {"conversation_id": conversation_id, "assistant_message_id": assistant_message_id}
        )
        await self.database["raw_tool_payloads"].delete_many(
            {"conversation_id": conversation_id, "assistant_message_id": assistant_message_id}
        )
        previous_snapshot = (cleanup_state or {}).get("previous_session_snapshot")
        if previous_snapshot is None:
            await self.database["session_snapshots"].delete_one({"_id": conversation_id})
        else:
            await self.database["session_snapshots"].replace_one(
                {"_id": conversation_id},
                previous_snapshot,
                upsert=True,
            )

    def fetch_messages(self, conversation_id: str) -> list[ChatMessageRecord] | None:
        try:
            return self._run(self.afetch_messages(conversation_id))
        except Exception as exc:
            raise ConversationMongoRuntimeError(
                f"MongoDB conversation message read failed: {exc}"
            ) from exc

    async def afetch_messages(self, conversation_id: str) -> list[ChatMessageRecord]:
        cursor = self.database["conversation_messages"].find({"conversation_id": conversation_id}).sort(
            [("created_at", 1), ("sequence_no", 1), ("_id", 1)]
        )
        documents = [document async for document in cursor]
        return [ChatMessageRecord.model_validate(document["payload"]) for document in documents]

    def get_request_snapshot(self, conversation_id: str, *, message_id: str) -> MessageRequest | None:
        try:
            return self._run(self.aget_request_snapshot(conversation_id, message_id=message_id))
        except Exception as exc:
            raise ConversationMongoRuntimeError(
                f"MongoDB conversation snapshot read failed: {exc}"
            ) from exc

    async def aping(self) -> None:
        await self.client.admin.command("ping")

    def ping(self) -> tuple[bool, str | None]:
        try:
            self._run(self.aping())
        except Exception as exc:
            return False, f"{exc.__class__.__name__}: {exc}"
        return True, None

    async def aget_request_snapshot(
        self,
        conversation_id: str,
        *,
        message_id: str,
    ) -> MessageRequest | None:
        snapshot = await self.database["session_snapshots"].find_one({"_id": conversation_id}, {"request_snapshots": 1})
        if snapshot is None:
            return None
        request_snapshots = snapshot.get("request_snapshots") or {}
        payload = request_snapshots.get(message_id)
        if payload is None:
            return None
        return MessageRequest.model_validate(payload)

    def describe_backend(self) -> dict[str, object]:
        ready, error = self.ping()
        return {
            "backend": "mongodb",
            "configured": True,
            "ready": ready,
            "degradedFrom": None if ready else "mongodb",
            "backendError": error,
            "database": self.database_name,
            "collections": {
                "conversation_messages": "conversation_messages",
                "agent_reasoning_logs": "agent_reasoning_logs",
                "raw_tool_payloads": "raw_tool_payloads",
                "session_snapshots": "session_snapshots",
            },
        }

    def clear(self) -> None:
        try:
            self._run(self.aclear())
        except Exception as exc:
            raise ConversationMongoRuntimeError(f"MongoDB conversation clear failed: {exc}") from exc

    async def aclear(self) -> None:
        for collection_name in (
            "conversation_messages",
            "agent_reasoning_logs",
            "raw_tool_payloads",
            "session_snapshots",
        ):
            await self.database[collection_name].delete_many({})

    def close(self) -> None:
        self.client.close()
