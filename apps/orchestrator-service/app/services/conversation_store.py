from __future__ import annotations

import json
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from app.core.config import get_settings
from app.models.common import TraceContext
from app.models.orchestration import (
    ChatMessageRecord,
    ConversationRecord,
    MessageRequest,
    OrchestratorResponse,
    SceneName,
    SessionContext,
    SessionCreateRequest,
    SessionMessagesPage,
)
from app.services import runtime_mysql
from app.services.runtime_redis import build_redis_client, normalize_namespace

RECOVERY_RETRY_SECONDS = 5.0


class ConversationStoreError(Exception):
    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass
class _ConversationSnapshotBundle:
    record: ConversationRecord
    messages: list[ChatMessageRecord]
    context: SessionContext
    request_snapshots: dict[tuple[str, str], MessageRequest]
    assistant_to_user: dict[tuple[str, str], str]


class _MySQLConversationBackend:
    CONVERSATION_TABLE = "orchestrator_conversations"
    MESSAGE_TABLE = "orchestrator_messages"
    SNAPSHOT_TABLE = "orchestrator_request_snapshots"

    def __init__(self, mysql_dsn: str) -> None:
        self._mysql_dsn = mysql_dsn

    def ensure_ready(self) -> None:
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
            connection.commit()
        finally:
            connection.close()

    def clear(self) -> None:
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(f"DELETE FROM `{self.SNAPSHOT_TABLE}`")
                cursor.execute(f"DELETE FROM `{self.MESSAGE_TABLE}`")
                cursor.execute(f"DELETE FROM `{self.CONVERSATION_TABLE}`")
            connection.commit()
        finally:
            connection.close()

    def create(self, request: SessionCreateRequest) -> ConversationRecord:
        conversation_id = ConversationStore.new_conversation_id()
        now = ConversationStore._now()
        record = ConversationRecord(
            conversation_id=conversation_id,
            scene=request.scene,
            status="active",
            title=request.title,
            created_at=now,
            updated_at=now,
            initial_context=request.initial_context,
            pending_actions=[],
            total_messages=0,
        )
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                self._write_conversation(cursor, record, context=request.initial_context)
            connection.commit()
        finally:
            connection.close()
        return record

    def ensure(
        self,
        conversation_id: str,
        *,
        scene: SceneName,
        title: str | None = None,
        initial_context: SessionContext | None = None,
    ) -> ConversationRecord:
        record = self.get(conversation_id)
        if record is None:
            now = ConversationStore._now()
            created = ConversationRecord(
                conversation_id=conversation_id,
                scene=scene,
                status="active",
                title=title,
                created_at=now,
                updated_at=now,
                initial_context=initial_context or SessionContext(),
                pending_actions=[],
                total_messages=0,
            )
            connection = runtime_mysql.connect(self._mysql_dsn)
            try:
                with connection.cursor() as cursor:
                    self._ensure_schema(cursor)
                    self._write_conversation(cursor, created, context=initial_context or SessionContext())
                connection.commit()
            finally:
                connection.close()
            return created
        if record.status == "archived":
            raise ConversationStoreError(
                status_code=409,
                code="CHAT_CONVERSATION_ARCHIVED",
                message=f"Conversation '{conversation_id}' is archived and cannot accept new messages.",
            )
        if record.status == "deleted":
            raise ConversationStoreError(
                status_code=404,
                code="CHAT_CONVERSATION_NOT_FOUND",
                message=f"Conversation '{conversation_id}' was not found.",
            )
        return record

    def get(self, conversation_id: str) -> ConversationRecord | None:
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"SELECT payload_json FROM `{self.CONVERSATION_TABLE}` WHERE conversation_id = %s",
                    (conversation_id,),
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        if not row:
            return None
        return ConversationRecord.model_validate(json.loads(row["payload_json"]))

    def get_context(self, conversation_id: str) -> SessionContext | None:
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"""
                    SELECT context_json, initial_context_json
                    FROM `{self.CONVERSATION_TABLE}`
                    WHERE conversation_id = %s
                    """,
                    (conversation_id,),
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        if not row:
            return None
        raw_context = row.get("context_json") or row.get("initial_context_json")
        if not raw_context:
            return SessionContext()
        return SessionContext.model_validate(json.loads(raw_context))

    def list(
        self,
        *,
        page: int,
        page_size: int,
        scene: SceneName | None,
        status: str | None,
        keyword: str | None,
    ) -> tuple[list[ConversationRecord], int]:
        conditions = ["status != %s"]
        params: list[object] = ["deleted"]
        if scene is not None:
            conditions.append("scene = %s")
            params.append(scene)
        if status is not None:
            conditions.append("status = %s")
            params.append(status)
        if keyword:
            like = f"%{keyword.strip().lower()}%"
            conditions.append(
                """
                LOWER(COALESCE(conversation_id, '')) LIKE %s
                OR LOWER(COALESCE(title, '')) LIKE %s
                OR LOWER(COALESCE(summary, '')) LIKE %s
                """
            )
            params.extend([like, like, like])
        where_clause = " AND ".join(f"({condition})" for condition in conditions)
        offset = max((page - 1) * page_size, 0)

        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"""
                    SELECT COUNT(*) AS total_count
                    FROM `{self.CONVERSATION_TABLE}`
                    WHERE {where_clause}
                    """,
                    tuple(params),
                )
                total_row = cursor.fetchone() or {}
                cursor.execute(
                    f"""
                    SELECT payload_json
                    FROM `{self.CONVERSATION_TABLE}`
                    WHERE {where_clause}
                    ORDER BY updated_at DESC, conversation_id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (*params, page_size, offset),
                )
                rows = cursor.fetchall() or []
        finally:
            connection.close()
        records = [ConversationRecord.model_validate(json.loads(row["payload_json"])) for row in rows]
        total = int(total_row.get("total_count", 0))
        return [item.model_copy(deep=True) for item in records], total

    def update_title(self, conversation_id: str, title: str) -> ConversationRecord:
        record = self._require_record(conversation_id)
        record.title = title
        record.updated_at = ConversationStore._now()
        self._persist_record(record, context=self.get_context(conversation_id) or SessionContext())
        return record

    def set_status(self, conversation_id: str, status: str) -> ConversationRecord:
        record = self._require_record(conversation_id)
        if record.status == "deleted" and status != "deleted":
            raise ConversationStoreError(
                status_code=404,
                code="CHAT_CONVERSATION_NOT_FOUND",
                message=f"Conversation '{conversation_id}' was not found.",
            )
        record.status = status  # type: ignore[assignment]
        record.updated_at = ConversationStore._now()
        self._persist_record(record, context=self.get_context(conversation_id) or SessionContext())
        return record

    def store_exchange(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
        message_request: MessageRequest,
        response: OrchestratorResponse,
        status: str,
        session_context: SessionContext | None = None,
        trace: TraceContext | None = None,
    ) -> tuple[ConversationRecord, list[ChatMessageRecord]]:
        return self._store_messages(
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            message_request=message_request,
            status=status,
            session_context=session_context,
            trace=trace,
            assistant_content=response.final_response_summary or response.route.summary,
            response=response,
            finish_reason=response.next_action,
        )

    def store_cancelled_exchange(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
        message_request: MessageRequest,
        reason: str,
        session_context: SessionContext | None = None,
        trace: TraceContext | None = None,
    ) -> tuple[ConversationRecord, list[ChatMessageRecord]]:
        return self._store_messages(
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            message_request=message_request,
            status="cancelled",
            session_context=session_context,
            trace=trace,
            assistant_content=reason,
            response=None,
            finish_reason="cancelled",
        )

    def list_messages(
        self,
        conversation_id: str,
        *,
        cursor: str | None,
        page_size: int,
    ) -> SessionMessagesPage:
        self._require_record(conversation_id)
        params: list[object] = [conversation_id]
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as sql_cursor:
                self._ensure_schema(sql_cursor)
                cursor_created_at: str | None = None
                cursor_sequence = 0
                if cursor:
                    sql_cursor.execute(
                        f"""
                        SELECT created_at, sequence_no
                        FROM `{self.MESSAGE_TABLE}`
                        WHERE conversation_id = %s AND message_id = %s
                        LIMIT 1
                        """,
                        (conversation_id, cursor),
                    )
                    row = sql_cursor.fetchone()
                    if row:
                        cursor_created_at = str(row["created_at"])
                        cursor_sequence = int(row["sequence_no"])
                sql = f"""
                    SELECT payload_json
                    FROM `{self.MESSAGE_TABLE}`
                    WHERE conversation_id = %s
                """
                if cursor_created_at is not None:
                    sql += """
                        AND (
                            created_at > %s
                            OR (created_at = %s AND sequence_no > %s)
                            OR (created_at = %s AND sequence_no = %s AND message_id > %s)
                        )
                    """
                    params.extend(
                        [
                            cursor_created_at,
                            cursor_created_at,
                            cursor_sequence,
                            cursor_created_at,
                            cursor_sequence,
                            cursor,
                        ]
                    )
                sql += """
                    ORDER BY created_at ASC, sequence_no ASC, message_id ASC
                    LIMIT %s
                """
                params.append(page_size + 1)
                sql_cursor.execute(sql, tuple(params))
                rows = sql_cursor.fetchall() or []
        finally:
            connection.close()
        items = [ChatMessageRecord.model_validate(json.loads(row["payload_json"])) for row in rows]
        page_items = items[:page_size]
        has_more = len(items) > page_size
        next_cursor = page_items[-1].message_id if has_more and page_items else None
        return SessionMessagesPage(
            items=[item.model_copy(deep=True) for item in page_items],
            next_cursor=next_cursor,
            has_more=has_more,
        )

    def build_retry_request(
        self,
        conversation_id: str,
        *,
        message_id: str,
        override_input: str | None,
    ) -> MessageRequest:
        snapshot = self.get_request_snapshot(conversation_id, message_id=message_id)
        if snapshot is None:
            raise ConversationStoreError(
                status_code=404,
                code="CHAT_MESSAGE_NOT_FOUND",
                message=f"Message '{message_id}' was not found in conversation '{conversation_id}'.",
            )
        return snapshot.model_copy(
            deep=True,
            update={
                "message_id": None,
                "user_query": override_input or snapshot.user_query,
                "trace": None,
            },
        )

    def latest_message_id(self, conversation_id: str, *, role: str | None) -> str:
        self._require_record(conversation_id)
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                if role is None:
                    cursor.execute(
                        f"""
                        SELECT message_id
                        FROM `{self.MESSAGE_TABLE}`
                        WHERE conversation_id = %s
                        ORDER BY created_at DESC, sequence_no DESC, message_id DESC
                        LIMIT 1
                        """,
                        (conversation_id,),
                    )
                else:
                    cursor.execute(
                        f"""
                        SELECT message_id
                        FROM `{self.MESSAGE_TABLE}`
                        WHERE conversation_id = %s AND role = %s
                        ORDER BY created_at DESC, sequence_no DESC, message_id DESC
                        LIMIT 1
                        """,
                        (conversation_id, role),
                    )
                row = cursor.fetchone()
        finally:
            connection.close()
        if row is None:
            raise ConversationStoreError(
                status_code=404,
                code="CHAT_MESSAGE_NOT_FOUND",
                message=f"No messages were found in conversation '{conversation_id}'.",
            )
        return str(row["message_id"])

    def resolve_request_message_id(self, conversation_id: str, message_id: str) -> str:
        self._require_record(conversation_id)
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"""
                    SELECT user_message_id
                    FROM `{self.SNAPSHOT_TABLE}`
                    WHERE conversation_id = %s AND assistant_message_id = %s
                    LIMIT 1
                    """,
                    (conversation_id, message_id),
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        return str(row["user_message_id"]) if row else message_id

    def describe_backend(self) -> dict[str, object]:
        return {
            "backend": "mysql",
            "configured": True,
            "tables": {
                "conversations": self.CONVERSATION_TABLE,
                "messages": self.MESSAGE_TABLE,
                "snapshots": self.SNAPSHOT_TABLE,
            },
        }

    def export_snapshot(self, conversation_id: str) -> _ConversationSnapshotBundle | None:
        record = self.get(conversation_id)
        if record is None:
            return None
        context = self.get_context(conversation_id) or record.initial_context
        messages = self.fetch_messages(conversation_id)
        request_snapshots: dict[tuple[str, str], MessageRequest] = {}
        assistant_to_user: dict[tuple[str, str], str] = {}
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"""
                    SELECT user_message_id, assistant_message_id, request_json
                    FROM `{self.SNAPSHOT_TABLE}`
                    WHERE conversation_id = %s
                    """,
                    (conversation_id,),
                )
                rows = cursor.fetchall() or []
        finally:
            connection.close()
        for row in rows:
            user_message_id = str(row["user_message_id"])
            request_snapshots[(conversation_id, user_message_id)] = MessageRequest.model_validate(
                json.loads(row["request_json"])
            )
            assistant_message_id = row.get("assistant_message_id")
            if assistant_message_id:
                assistant_to_user[(conversation_id, str(assistant_message_id))] = user_message_id
        return _ConversationSnapshotBundle(
            record=record.model_copy(deep=True),
            messages=[message.model_copy(deep=True) for message in messages],
            context=context.model_copy(deep=True),
            request_snapshots={
                key: snapshot.model_copy(deep=True)
                for key, snapshot in request_snapshots.items()
            },
            assistant_to_user=dict(assistant_to_user),
        )

    def import_snapshot(
        self,
        *,
        conversations: dict[str, ConversationRecord],
        messages: dict[str, list[ChatMessageRecord]],
        contexts: dict[str, SessionContext],
        request_snapshots: dict[tuple[str, str], MessageRequest],
        assistant_to_user: dict[tuple[str, str], str],
    ) -> None:
        assistant_by_user = {
            (conversation_id, user_message_id): assistant_message_id
            for (conversation_id, assistant_message_id), user_message_id in assistant_to_user.items()
        }
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                for conversation_id, record in conversations.items():
                    context = contexts.get(conversation_id) or record.initial_context
                    self._write_conversation(cursor, record, context=context)
                for conversation_id, conversation_messages in messages.items():
                    for sequence_no, message in enumerate(conversation_messages, start=1):
                        cursor.execute(
                            f"""
                            REPLACE INTO `{self.MESSAGE_TABLE}` (
                                conversation_id,
                                message_id,
                                role,
                                created_at,
                                sequence_no,
                                payload_json
                            ) VALUES (%s, %s, %s, %s, %s, %s)
                            """,
                            (
                                conversation_id,
                                message.message_id,
                                message.role,
                                message.created_at,
                                sequence_no,
                                json.dumps(message.model_dump(mode="json"), ensure_ascii=False),
                            ),
                        )
                for (conversation_id, user_message_id), request in request_snapshots.items():
                    cursor.execute(
                        f"""
                        REPLACE INTO `{self.SNAPSHOT_TABLE}` (
                            conversation_id,
                            user_message_id,
                            assistant_message_id,
                            request_json
                        ) VALUES (%s, %s, %s, %s)
                        """,
                        (
                            conversation_id,
                            user_message_id,
                            assistant_by_user.get((conversation_id, user_message_id)),
                            json.dumps(request.model_dump(mode="json"), ensure_ascii=False),
                        ),
                    )
            connection.commit()
        finally:
            connection.close()

    def _persist_record(self, record: ConversationRecord, *, context: SessionContext) -> None:
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                self._write_conversation(cursor, record, context=context)
            connection.commit()
        finally:
            connection.close()

    def _require_record(self, conversation_id: str) -> ConversationRecord:
        record = self.get(conversation_id)
        if record is None or record.status == "deleted":
            raise ConversationStoreError(
                status_code=404,
                code="CHAT_CONVERSATION_NOT_FOUND",
                message=f"Conversation '{conversation_id}' was not found.",
            )
        return record

    def fetch_messages(self, conversation_id: str) -> list[ChatMessageRecord]:
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"""
                    SELECT payload_json
                    FROM `{self.MESSAGE_TABLE}`
                    WHERE conversation_id = %s
                    ORDER BY created_at ASC, sequence_no ASC, message_id ASC
                    """,
                    (conversation_id,),
                )
                rows = cursor.fetchall() or []
        finally:
            connection.close()
        return [ChatMessageRecord.model_validate(json.loads(row["payload_json"])) for row in rows]

    def get_request_snapshot(
        self,
        conversation_id: str,
        *,
        message_id: str,
    ) -> MessageRequest | None:
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"""
                    SELECT request_json
                    FROM `{self.SNAPSHOT_TABLE}`
                    WHERE conversation_id = %s AND (user_message_id = %s OR assistant_message_id = %s)
                    LIMIT 1
                    """,
                    (conversation_id, message_id, message_id),
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return MessageRequest.model_validate(json.loads(row["request_json"]))

    def _store_messages(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
        message_request: MessageRequest,
        status: str,
        session_context: SessionContext | None,
        trace: TraceContext | None,
        assistant_content: str,
        response: OrchestratorResponse | None,
        finish_reason: str,
    ) -> tuple[ConversationRecord, list[ChatMessageRecord]]:
        record = self._require_record(conversation_id)
        if record.status == "archived":
            raise ConversationStoreError(
                status_code=409,
                code="CHAT_CONVERSATION_ARCHIVED",
                message=f"Conversation '{conversation_id}' is archived and cannot accept new messages.",
            )
        messages = self.fetch_messages(conversation_id)
        messages = [
            item
            for item in messages
            if item.message_id not in {user_message_id, assistant_message_id}
        ]
        sequence_base = len(messages)
        now = ConversationStore._now()
        previous_message_id = messages[-1].message_id if messages else None
        user_message = ChatMessageRecord(
            message_id=user_message_id,
            conversation_id=conversation_id,
            role="user",
            message_type="user_input",
            status="completed",
            created_at=now,
            updated_at=now,
            parent_message_id=previous_message_id,
            content=message_request.user_query,
            trace=trace,
        )
        assistant_message = ChatMessageRecord(
            message_id=assistant_message_id,
            conversation_id=conversation_id,
            role="assistant",
            message_type="assistant_response",
            status=status,
            created_at=now,
            updated_at=now,
            parent_message_id=user_message_id,
            agent_name=response.route.primary_agent if response else None,
            content=assistant_content,
            citations=list(
                dict.fromkeys(
                    citation
                    for execution in (response.executions if response else [])
                    for citation in execution.citations
                )
            ),
            tool_calls=[tool_call for execution in (response.executions if response else []) for tool_call in execution.tool_calls],
            finish_reason=finish_reason,
            trace=trace,
        )
        messages.extend([user_message, assistant_message])
        record.status = "active"
        record.current_agent = (
            response.state_snapshot.current_agent
            if response and response.state_snapshot and response.state_snapshot.current_agent
            else (response.route.primary_agent if response else None)
        )
        record.summary = assistant_content
        record.pending_actions = list(response.pending_actions) if response else []
        record.last_message_at = assistant_message.updated_at
        record.updated_at = assistant_message.updated_at
        record.total_messages = len(messages)
        if not record.title:
            record.title = ConversationStore.derive_title(message_request.user_query)
        effective_context = session_context.model_copy(deep=True) if session_context is not None else self.get_context(conversation_id) or SessionContext()

        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"""
                    DELETE FROM `{self.MESSAGE_TABLE}`
                    WHERE conversation_id = %s AND (message_id = %s OR message_id = %s)
                    """,
                    (conversation_id, user_message_id, assistant_message_id),
                )
                sequence_numbers = {
                    user_message_id: sequence_base + 1,
                    assistant_message_id: sequence_base + 2,
                }
                for message in (user_message, assistant_message):
                    sequence_no = sequence_numbers[message.message_id]
                    cursor.execute(
                        f"""
                        REPLACE INTO `{self.MESSAGE_TABLE}` (
                            conversation_id,
                            message_id,
                            role,
                            created_at,
                            sequence_no,
                            payload_json
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            conversation_id,
                            message.message_id,
                            message.role,
                            message.created_at,
                            sequence_no,
                            json.dumps(message.model_dump(mode="json"), ensure_ascii=False),
                        ),
                    )
                cursor.execute(
                    f"""
                    REPLACE INTO `{self.SNAPSHOT_TABLE}` (
                        conversation_id,
                        user_message_id,
                        assistant_message_id,
                        request_json
                    ) VALUES (%s, %s, %s, %s)
                    """,
                    (
                        conversation_id,
                        user_message_id,
                        assistant_message_id,
                        json.dumps(message_request.model_dump(mode="json"), ensure_ascii=False),
                    ),
                )
                self._write_conversation(cursor, record, context=effective_context)
            connection.commit()
        finally:
            connection.close()
        return record, [user_message, assistant_message]

    def _write_conversation(self, cursor, record: ConversationRecord, *, context: SessionContext) -> None:
        cursor.execute(
            f"""
            REPLACE INTO `{self.CONVERSATION_TABLE}` (
                conversation_id,
                scene,
                status,
                title,
                current_agent,
                summary,
                created_at,
                updated_at,
                last_message_at,
                total_messages,
                initial_context_json,
                context_json,
                pending_actions_json,
                payload_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                record.conversation_id,
                record.scene,
                record.status,
                record.title,
                record.current_agent,
                record.summary,
                record.created_at,
                record.updated_at,
                record.last_message_at,
                record.total_messages,
                json.dumps(record.initial_context.model_dump(mode="json"), ensure_ascii=False),
                json.dumps(context.model_dump(mode="json"), ensure_ascii=False),
                json.dumps(record.pending_actions, ensure_ascii=False),
                json.dumps(record.model_dump(mode="json"), ensure_ascii=False),
            ),
        )

    def _ensure_schema(self, cursor) -> None:
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{self.CONVERSATION_TABLE}` (
                conversation_id VARCHAR(128) PRIMARY KEY,
                scene VARCHAR(64) NOT NULL,
                status VARCHAR(64) NOT NULL,
                title TEXT NULL,
                current_agent VARCHAR(128) NULL,
                summary LONGTEXT NULL,
                created_at VARCHAR(128) NOT NULL,
                updated_at VARCHAR(128) NOT NULL,
                last_message_at VARCHAR(128) NULL,
                total_messages INT NOT NULL,
                initial_context_json LONGTEXT NOT NULL,
                context_json LONGTEXT NOT NULL,
                pending_actions_json LONGTEXT NOT NULL,
                payload_json LONGTEXT NOT NULL
            )
            """
        )
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{self.MESSAGE_TABLE}` (
                conversation_id VARCHAR(128) NOT NULL,
                message_id VARCHAR(128) NOT NULL,
                role VARCHAR(32) NOT NULL,
                created_at VARCHAR(128) NOT NULL,
                sequence_no INT NOT NULL,
                payload_json LONGTEXT NOT NULL,
                PRIMARY KEY (conversation_id, message_id)
            )
            """
        )
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{self.SNAPSHOT_TABLE}` (
                conversation_id VARCHAR(128) NOT NULL,
                user_message_id VARCHAR(128) NOT NULL,
                assistant_message_id VARCHAR(128) NULL,
                request_json LONGTEXT NOT NULL,
                PRIMARY KEY (conversation_id, user_message_id)
            )
            """
        )
        runtime_mysql.create_index_if_missing(
            cursor,
            table_name=self.CONVERSATION_TABLE,
            index_name=f"idx_{self.CONVERSATION_TABLE}_updated",
            columns=("updated_at", "conversation_id"),
        )
        runtime_mysql.create_index_if_missing(
            cursor,
            table_name=self.CONVERSATION_TABLE,
            index_name=f"idx_{self.CONVERSATION_TABLE}_scene_status",
            columns=("scene", "status", "updated_at"),
        )
        runtime_mysql.create_index_if_missing(
            cursor,
            table_name=self.MESSAGE_TABLE,
            index_name=f"idx_{self.MESSAGE_TABLE}_conversation_sequence",
            columns=("conversation_id", "created_at", "sequence_no", "message_id"),
        )
        runtime_mysql.create_index_if_missing(
            cursor,
            table_name=self.SNAPSHOT_TABLE,
            index_name=f"idx_{self.SNAPSHOT_TABLE}_assistant_message",
            columns=("conversation_id", "assistant_message_id"),
        )


class ConversationStore:
    """Session/message store with MySQL authority, Redis runtime cache, and JSON fallback."""

    def __init__(
        self,
        file_path: str | Path | None = None,
        *,
        mysql_dsn: str | None = None,
        redis_url: str | None = None,
        redis_namespace: str = "smartcloud:orchestrator:conversation",
    ) -> None:
        settings = get_settings()
        self._lock = RLock()
        self._conversations: dict[str, ConversationRecord] = {}
        self._messages: dict[str, list[ChatMessageRecord]] = {}
        self._contexts: dict[str, SessionContext] = {}
        self._request_snapshots: dict[tuple[str, str], MessageRequest] = {}
        self._assistant_to_user: dict[tuple[str, str], str] = {}
        self._max_recent_messages = max(settings.max_history_turns, 20)
        self._file_path: Path | None = None
        self._mysql_dsn: str | None = None
        self._backend: _MySQLConversationBackend | None = None
        self._backend_error: str | None = None
        self._next_backend_recovery_at = 0.0
        self._redis_url: str | None = None
        self._redis_namespace = normalize_namespace(redis_namespace)
        self._redis_client = None
        self._cache_error: str | None = None
        self._next_cache_recovery_at = 0.0
        self.configure_persistence(
            file_path,
            mysql_dsn=mysql_dsn,
            redis_url=redis_url,
            redis_namespace=redis_namespace,
        )

    def configure_persistence(
        self,
        file_path: str | Path | None,
        *,
        mysql_dsn: str | None = None,
        redis_url: str | None = None,
        redis_namespace: str | None = None,
    ) -> None:
        path = Path(file_path).expanduser() if file_path else None
        with self._lock:
            self._file_path = path
            self._mysql_dsn = mysql_dsn
            self._backend = _MySQLConversationBackend(mysql_dsn) if mysql_dsn else None
            self._backend_error = None
            self._next_backend_recovery_at = 0.0
            self._redis_url = redis_url
            if redis_namespace:
                self._redis_namespace = normalize_namespace(redis_namespace)
            self._redis_client = build_redis_client(redis_url) if self._backend is not None else None
            self._cache_error = (
                "Redis connection unavailable."
                if redis_url and self._backend is not None and self._redis_client is None
                else None
            )
            self._next_cache_recovery_at = 0.0
            self._load_unlocked(path)
            if self._backend is not None:
                try:
                    self._backend.ensure_ready()
                    self._bootstrap_backend_from_local_unlocked()
                    self._bootstrap_runtime_cache_from_local_unlocked()
                    self._persist_unlocked()
                except Exception as exc:
                    self._degrade_backend(exc)

    def clear(self) -> None:
        self._maybe_restore_runtime_cache()
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                backend.clear()
                self._clear_runtime_cache()
                with self._lock:
                    self._conversations.clear()
                    self._messages.clear()
                    self._contexts.clear()
                    self._request_snapshots.clear()
                    self._assistant_to_user.clear()
                    self._persist_unlocked()
                return
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            self._conversations.clear()
            self._messages.clear()
            self._contexts.clear()
            self._request_snapshots.clear()
            self._assistant_to_user.clear()
            self._persist_unlocked()
        self._clear_runtime_cache()

    @property
    def max_recent_messages(self) -> int:
        return self._max_recent_messages

    def create(self, request: SessionCreateRequest) -> ConversationRecord:
        self._maybe_restore_runtime_cache()
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                record = backend.create(request).model_copy(deep=True)
                self._save_record_to_runtime_cache(record, context=request.initial_context)
                with self._lock:
                    self._mirror_record_unlocked(
                        record,
                        context=request.initial_context.model_copy(deep=True),
                    )
                return record
            except Exception as exc:
                self._degrade_backend(exc)
        conversation_id = self.new_conversation_id()
        now = self._now()
        record = ConversationRecord(
            conversation_id=conversation_id,
            scene=request.scene,
            status="active",
            title=request.title,
            created_at=now,
            updated_at=now,
            initial_context=request.initial_context,
            pending_actions=[],
            total_messages=0,
        )
        with self._lock:
            self._conversations[conversation_id] = record
            self._messages[conversation_id] = []
            self._contexts[conversation_id] = request.initial_context.model_copy(deep=True)
            self._persist_unlocked()
        return record.model_copy(deep=True)

    def ensure(
        self,
        conversation_id: str,
        *,
        scene: SceneName,
        title: str | None = None,
        initial_context: SessionContext | None = None,
    ) -> ConversationRecord:
        self._maybe_restore_runtime_cache()
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                record = backend.ensure(
                    conversation_id,
                    scene=scene,
                    title=title,
                    initial_context=initial_context,
                ).model_copy(deep=True)
                context = backend.get_context(conversation_id) or initial_context or record.initial_context
                self._save_record_to_runtime_cache(record, context=context)
                with self._lock:
                    self._mirror_record_unlocked(
                        record,
                        context=context.model_copy(deep=True),
                    )
                return record
            except ConversationStoreError:
                raise
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            record = self._conversations.get(conversation_id)
            if record is None:
                now = self._now()
                record = ConversationRecord(
                    conversation_id=conversation_id,
                    scene=scene,
                    status="active",
                    title=title,
                    created_at=now,
                    updated_at=now,
                    initial_context=initial_context or SessionContext(),
                    pending_actions=[],
                    total_messages=0,
                )
                self._conversations[conversation_id] = record
                self._messages[conversation_id] = []
                self._contexts[conversation_id] = (initial_context or SessionContext()).model_copy(deep=True)
                self._persist_unlocked()
            elif record.status == "archived":
                raise ConversationStoreError(
                    status_code=409,
                    code="CHAT_CONVERSATION_ARCHIVED",
                    message=f"Conversation '{conversation_id}' is archived and cannot accept new messages.",
                )
            elif record.status == "deleted":
                raise ConversationStoreError(
                    status_code=404,
                    code="CHAT_CONVERSATION_NOT_FOUND",
                    message=f"Conversation '{conversation_id}' was not found.",
                )
            return record.model_copy(deep=True)

    def get(self, conversation_id: str) -> ConversationRecord | None:
        self._maybe_restore_runtime_cache()
        cached = self._get_record_from_runtime_cache(conversation_id)
        if cached is not None:
            with self._lock:
                self._conversations[conversation_id] = cached.model_copy(deep=True)
            return cached.model_copy(deep=True)
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                record = backend.get(conversation_id)
                if record is not None:
                    context = backend.get_context(conversation_id) or self._contexts.get(conversation_id) or record.initial_context
                    self._save_record_to_runtime_cache(record, context=context)
                    with self._lock:
                        self._conversations[conversation_id] = record.model_copy(deep=True)
                        self._contexts[conversation_id] = context.model_copy(deep=True)
                return record.model_copy(deep=True) if record else None
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            record = self._conversations.get(conversation_id)
            return record.model_copy(deep=True) if record else None

    def require(self, conversation_id: str) -> ConversationRecord:
        record = self.get(conversation_id)
        if record is None or record.status == "deleted":
            raise ConversationStoreError(
                status_code=404,
                code="CHAT_CONVERSATION_NOT_FOUND",
                message=f"Conversation '{conversation_id}' was not found.",
            )
        return record

    def get_context(self, conversation_id: str) -> SessionContext | None:
        self._maybe_restore_runtime_cache()
        cached = self._get_context_from_runtime_cache(conversation_id)
        if cached is not None:
            with self._lock:
                self._contexts[conversation_id] = cached.model_copy(deep=True)
            return cached.model_copy(deep=True)
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                context = backend.get_context(conversation_id)
                if context is not None:
                    self._save_context_to_runtime_cache(conversation_id, context)
                    with self._lock:
                        self._contexts[conversation_id] = context.model_copy(deep=True)
                return context.model_copy(deep=True) if context else None
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            context = self._contexts.get(conversation_id)
            return context.model_copy(deep=True) if context else None

    def compose_context(
        self,
        conversation_id: str,
        incoming: SessionContext | None = None,
    ) -> SessionContext:
        base = self.get_context(conversation_id) or SessionContext()
        if incoming is not None and base.model_dump() == incoming.model_dump():
            return incoming.model_copy(deep=True)
        return self.merge_session_context(
            base,
            incoming,
            persist_confirmed_tool_names=True,
            max_recent_messages=self._max_recent_messages,
        )

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        scene: SceneName | None = None,
        status: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[ConversationRecord], int]:
        self._maybe_restore_runtime_cache()
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                items, total = backend.list(
                    page=page,
                    page_size=page_size,
                    scene=scene,
                    status=status,
                    keyword=keyword,
                )
                return [item.model_copy(deep=True) for item in items], total
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            records = list(self._conversations.values())
        normalized_keyword = keyword.strip().lower() if keyword else None
        filtered = [
            record
            for record in records
            if record.status != "deleted"
            and (scene is None or record.scene == scene)
            and (status is None or record.status == status)
            and (
                normalized_keyword is None
                or normalized_keyword in record.conversation_id.lower()
                or normalized_keyword in (record.title or "").lower()
                or normalized_keyword in (record.summary or "").lower()
            )
        ]
        filtered.sort(key=lambda item: item.updated_at, reverse=True)
        total = len(filtered)
        start = max((page - 1) * page_size, 0)
        end = start + page_size
        return [item.model_copy(deep=True) for item in filtered[start:end]], total

    def update_title(self, conversation_id: str, title: str) -> ConversationRecord:
        self._maybe_restore_runtime_cache()
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                record = backend.update_title(conversation_id, title).model_copy(deep=True)
                context = backend.get_context(conversation_id) or self._contexts.get(conversation_id) or record.initial_context
                self._save_record_to_runtime_cache(
                    record,
                    context=context,
                )
                with self._lock:
                    self._mirror_record_unlocked(
                        record,
                        context=context,
                    )
                return record
            except ConversationStoreError:
                raise
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            record = self._conversations.get(conversation_id)
            if record is None or record.status == "deleted":
                raise ConversationStoreError(
                    status_code=404,
                    code="CHAT_CONVERSATION_NOT_FOUND",
                    message=f"Conversation '{conversation_id}' was not found.",
                )
            record.title = title
            record.updated_at = self._now()
            self._persist_unlocked()
            return record.model_copy(deep=True)

    def archive(self, conversation_id: str) -> ConversationRecord:
        return self._set_status(conversation_id, "archived")

    def delete(self, conversation_id: str) -> ConversationRecord:
        return self._set_status(conversation_id, "deleted")

    def activate(self, conversation_id: str) -> ConversationRecord:
        return self._set_status(conversation_id, "active")

    def restore(self, conversation_id: str) -> ConversationRecord:
        record = self.require(conversation_id)
        if record.status != "archived":
            raise ConversationStoreError(
                status_code=409,
                code="CHAT_CONVERSATION_RESTORE_INVALID",
                message=f"Conversation '{conversation_id}' is not archived.",
            )
        return self._set_status(conversation_id, "active")

    def mark_running(
        self,
        conversation_id: str,
        *,
        scene: SceneName,
        title: str | None = None,
        initial_context: SessionContext | None = None,
    ) -> ConversationRecord:
        self.ensure(
            conversation_id,
            scene=scene,
            title=title,
            initial_context=initial_context,
        )
        return self._set_status(conversation_id, "running")

    def store_exchange(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
        message_request: MessageRequest,
        response: OrchestratorResponse,
        status: str,
        session_context: SessionContext | None = None,
        trace: TraceContext | None = None,
    ) -> tuple[ConversationRecord, list[ChatMessageRecord]]:
        self._maybe_restore_runtime_cache()
        effective_context = (
            session_context.model_copy(deep=True)
            if session_context is not None
            else self.derive_next_session_context(
                self.get_context(conversation_id),
                message_request,
                response,
                max_recent_messages=self._max_recent_messages,
            )
        )
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                record, messages = backend.store_exchange(
                    conversation_id=conversation_id,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    message_request=message_request,
                    response=response,
                    status=status,
                    session_context=effective_context,
                    trace=trace,
                )
                self._save_exchange_to_runtime_cache(
                    record,
                    messages,
                    context=effective_context,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    message_request=message_request,
                )
                with self._lock:
                    self._mirror_exchange_unlocked(
                        record,
                        messages,
                        context=effective_context,
                        user_message_id=user_message_id,
                        assistant_message_id=assistant_message_id,
                        message_request=message_request,
                    )
                return record.model_copy(deep=True), [item.model_copy(deep=True) for item in messages]
            except ConversationStoreError:
                raise
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            record = self._conversations.get(conversation_id)
            if record is None:
                raise ConversationStoreError(
                    status_code=404,
                    code="CHAT_CONVERSATION_NOT_FOUND",
                    message=f"Conversation '{conversation_id}' was not found.",
                )
            if record.status == "archived":
                raise ConversationStoreError(
                    status_code=409,
                    code="CHAT_CONVERSATION_ARCHIVED",
                    message=f"Conversation '{conversation_id}' is archived and cannot accept new messages.",
                )
            messages = list(self._messages.get(conversation_id, []))
            messages = [
                item
                for item in messages
                if item.message_id not in {user_message_id, assistant_message_id}
            ]
            now = self._now()
            previous_message_id = messages[-1].message_id if messages else None
            user_message = ChatMessageRecord(
                message_id=user_message_id,
                conversation_id=conversation_id,
                role="user",
                message_type="user_input",
                status="completed",
                created_at=now,
                updated_at=now,
                parent_message_id=previous_message_id,
                content=message_request.user_query,
                trace=trace,
            )
            assistant_message = ChatMessageRecord(
                message_id=assistant_message_id,
                conversation_id=conversation_id,
                role="assistant",
                message_type="assistant_response",
                status=status,
                created_at=now,
                updated_at=now,
                parent_message_id=user_message_id,
                agent_name=response.route.primary_agent,
                content=response.final_response_summary or response.route.summary,
                citations=list(
                    dict.fromkeys(
                        citation
                        for execution in response.executions
                        for citation in execution.citations
                    )
                ),
                tool_calls=[tool_call for execution in response.executions for tool_call in execution.tool_calls],
                finish_reason=response.next_action,
                trace=trace,
            )
            messages.extend([user_message, assistant_message])
            record.status = "active"
            record.current_agent = (
                response.state_snapshot.current_agent
                if response.state_snapshot and response.state_snapshot.current_agent
                else response.route.primary_agent
            )
            record.summary = response.final_response_summary or response.route.summary
            record.pending_actions = list(response.pending_actions)
            record.last_message_at = assistant_message.updated_at
            record.updated_at = assistant_message.updated_at
            record.total_messages = len(messages)
            if not record.title:
                record.title = self.derive_title(message_request.user_query)
            self._messages[conversation_id] = messages
            self._contexts[conversation_id] = effective_context.model_copy(deep=True)
            self._request_snapshots[(conversation_id, user_message_id)] = message_request.model_copy(deep=True)
            self._assistant_to_user[(conversation_id, assistant_message_id)] = user_message_id
            self._persist_unlocked()
            return record.model_copy(deep=True), [user_message, assistant_message]

    def list_messages(
        self,
        conversation_id: str,
        *,
        cursor: str | None = None,
        page_size: int = 20,
    ) -> SessionMessagesPage:
        self._maybe_restore_runtime_cache()
        self.require(conversation_id)
        cached_messages = self._get_messages_from_runtime_cache(conversation_id)
        if cached_messages is not None:
            with self._lock:
                self._messages[conversation_id] = [item.model_copy(deep=True) for item in cached_messages]
            return self._build_message_page(cached_messages, cursor=cursor, page_size=page_size)
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                items = backend.fetch_messages(conversation_id)
                self._save_messages_to_runtime_cache(conversation_id, items)
                with self._lock:
                    self._messages[conversation_id] = [item.model_copy(deep=True) for item in items]
                return self._build_message_page(items, cursor=cursor, page_size=page_size)
            except ConversationStoreError:
                raise
            except Exception as exc:
                self._degrade_backend(exc)
        self.require(conversation_id)
        with self._lock:
            items = list(self._messages.get(conversation_id, []))
        return self._build_message_page(items, cursor=cursor, page_size=page_size)

    def store_cancelled_exchange(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
        message_request: MessageRequest,
        reason: str = "生成已取消。",
        session_context: SessionContext | None = None,
        trace: TraceContext | None = None,
    ) -> tuple[ConversationRecord, list[ChatMessageRecord]]:
        self._maybe_restore_runtime_cache()
        effective_context = (
            session_context.model_copy(deep=True)
            if session_context is not None
            else self.get_context(conversation_id) or SessionContext()
        )
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                record, messages = backend.store_cancelled_exchange(
                    conversation_id=conversation_id,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    message_request=message_request,
                    reason=reason,
                    session_context=effective_context,
                    trace=trace,
                )
                self._save_exchange_to_runtime_cache(
                    record,
                    messages,
                    context=effective_context,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    message_request=message_request,
                )
                with self._lock:
                    self._mirror_exchange_unlocked(
                        record,
                        messages,
                        context=effective_context,
                        user_message_id=user_message_id,
                        assistant_message_id=assistant_message_id,
                        message_request=message_request,
                    )
                return record.model_copy(deep=True), [item.model_copy(deep=True) for item in messages]
            except ConversationStoreError:
                raise
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            record = self._conversations.get(conversation_id)
            if record is None:
                raise ConversationStoreError(
                    status_code=404,
                    code="CHAT_CONVERSATION_NOT_FOUND",
                    message=f"Conversation '{conversation_id}' was not found.",
                )
            messages = list(self._messages.get(conversation_id, []))
            messages = [
                item
                for item in messages
                if item.message_id not in {user_message_id, assistant_message_id}
            ]
            now = self._now()
            previous_message_id = messages[-1].message_id if messages else None
            user_message = ChatMessageRecord(
                message_id=user_message_id,
                conversation_id=conversation_id,
                role="user",
                message_type="user_input",
                status="completed",
                created_at=now,
                updated_at=now,
                parent_message_id=previous_message_id,
                content=message_request.user_query,
                trace=trace,
            )
            assistant_message = ChatMessageRecord(
                message_id=assistant_message_id,
                conversation_id=conversation_id,
                role="assistant",
                message_type="assistant_response",
                status="cancelled",
                created_at=now,
                updated_at=now,
                parent_message_id=user_message_id,
                content=reason,
                finish_reason="cancelled",
                trace=trace,
            )
            messages.extend([user_message, assistant_message])
            record.status = "active"
            record.summary = reason
            record.pending_actions = []
            record.last_message_at = assistant_message.updated_at
            record.updated_at = assistant_message.updated_at
            record.total_messages = len(messages)
            if not record.title:
                record.title = self.derive_title(message_request.user_query)
            self._messages[conversation_id] = messages
            self._contexts[conversation_id] = effective_context.model_copy(deep=True)
            self._request_snapshots[(conversation_id, user_message_id)] = message_request.model_copy(deep=True)
            self._assistant_to_user[(conversation_id, assistant_message_id)] = user_message_id
            self._persist_unlocked()
            return record.model_copy(deep=True), [user_message, assistant_message]

    def build_retry_request(
        self,
        conversation_id: str,
        *,
        message_id: str,
        override_input: str | None = None,
    ) -> MessageRequest:
        self._maybe_restore_runtime_cache()
        user_message_id = self.resolve_request_message_id(conversation_id, message_id)
        cached_snapshot = self._get_request_snapshot_from_runtime_cache(conversation_id, user_message_id)
        if cached_snapshot is not None:
            return self._build_retry_request_from_snapshot(cached_snapshot, override_input=override_input)
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                snapshot = backend.get_request_snapshot(conversation_id, message_id=user_message_id)
                if snapshot is None:
                    raise ConversationStoreError(
                        status_code=404,
                        code="CHAT_MESSAGE_NOT_FOUND",
                        message=f"Message '{message_id}' was not found in conversation '{conversation_id}'.",
                    )
                self._save_request_snapshot_to_runtime_cache(conversation_id, user_message_id, snapshot)
                if user_message_id != message_id:
                    self._save_assistant_mapping_to_runtime_cache(conversation_id, message_id, user_message_id)
                with self._lock:
                    self._request_snapshots[(conversation_id, user_message_id)] = snapshot.model_copy(deep=True)
                    if user_message_id != message_id:
                        self._assistant_to_user[(conversation_id, message_id)] = user_message_id
                return self._build_retry_request_from_snapshot(snapshot, override_input=override_input)
            except ConversationStoreError:
                raise
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            snapshot = self._request_snapshots.get((conversation_id, user_message_id))
        if snapshot is None:
            raise ConversationStoreError(
                status_code=404,
                code="CHAT_MESSAGE_NOT_FOUND",
                message=f"Message '{message_id}' was not found in conversation '{conversation_id}'.",
            )
        return self._build_retry_request_from_snapshot(snapshot, override_input=override_input)

    def latest_message_id(
        self,
        conversation_id: str,
        *,
        role: str | None = None,
    ) -> str:
        self._maybe_restore_runtime_cache()
        self.require(conversation_id)
        cached_messages = self._get_messages_from_runtime_cache(conversation_id)
        if cached_messages is not None:
            with self._lock:
                self._messages[conversation_id] = [item.model_copy(deep=True) for item in cached_messages]
            return self._latest_message_id_from_items(
                cached_messages,
                conversation_id=conversation_id,
                role=role,
            )
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                items = backend.fetch_messages(conversation_id)
                self._save_messages_to_runtime_cache(conversation_id, items)
                with self._lock:
                    self._messages[conversation_id] = [item.model_copy(deep=True) for item in items]
                return self._latest_message_id_from_items(
                    items,
                    conversation_id=conversation_id,
                    role=role,
                )
            except ConversationStoreError:
                raise
            except Exception as exc:
                self._degrade_backend(exc)
        self.require(conversation_id)
        with self._lock:
            items = list(self._messages.get(conversation_id, []))
        return self._latest_message_id_from_items(items, conversation_id=conversation_id, role=role)

    def resolve_request_message_id(
        self,
        conversation_id: str,
        message_id: str,
    ) -> str:
        self._maybe_restore_runtime_cache()
        self.require(conversation_id)
        cached_mapping = self._get_assistant_mapping_from_runtime_cache(conversation_id, message_id)
        if cached_mapping is not None:
            with self._lock:
                self._assistant_to_user[(conversation_id, message_id)] = cached_mapping
            return cached_mapping
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                resolved = backend.resolve_request_message_id(conversation_id, message_id)
                if resolved != message_id:
                    self._save_assistant_mapping_to_runtime_cache(conversation_id, message_id, resolved)
                    with self._lock:
                        self._assistant_to_user[(conversation_id, message_id)] = resolved
                return resolved
            except Exception as exc:
                self._degrade_backend(exc)
        self.require(conversation_id)
        with self._lock:
            if (conversation_id, message_id) in self._assistant_to_user:
                return self._assistant_to_user[(conversation_id, message_id)]
        return message_id

    @classmethod
    def merge_session_context(
        cls,
        base: SessionContext | None,
        override: SessionContext | None,
        *,
        persist_confirmed_tool_names: bool,
        max_recent_messages: int,
    ) -> SessionContext:
        base_context = base.model_copy(deep=True) if base else SessionContext()
        if override is None:
            if not persist_confirmed_tool_names:
                base_context.confirmed_tool_names = []
            return base_context

        merged = base_context.model_copy(deep=True)
        if override.history_summary:
            merged.history_summary = override.history_summary
        merged.recent_messages = cls._merge_recent_messages(
            merged.recent_messages,
            override.recent_messages,
            max_recent_messages=max_recent_messages,
        )
        merged.active_products = cls._dedupe_strings(
            [*merged.active_products, *override.active_products]
        )
        if override.open_ticket_id:
            merged.open_ticket_id = override.open_ticket_id
        merged.attributes = cls._merge_attributes(merged.attributes, override.attributes)
        if persist_confirmed_tool_names:
            merged.confirmed_tool_names = cls._dedupe_strings(
                [*merged.confirmed_tool_names, *override.confirmed_tool_names]
            )
        else:
            merged.confirmed_tool_names = []
        return merged

    @classmethod
    def derive_next_session_context(
        cls,
        base_context: SessionContext | None,
        message_request: MessageRequest,
        response: OrchestratorResponse,
        *,
        max_recent_messages: int,
    ) -> SessionContext:
        merged = cls.merge_session_context(
            base_context,
            message_request.session_context,
            persist_confirmed_tool_names=False,
            max_recent_messages=max_recent_messages,
        )
        assistant_summary = response.final_response_summary or response.route.summary
        merged.history_summary = cls._merge_history_summary(
            merged.history_summary,
            message_request.user_query,
            assistant_summary,
        )
        merged.recent_messages = cls._merge_recent_messages(
            merged.recent_messages,
            [
                {"role": "user", "content": cls._compact_text(message_request.user_query)},
                {
                    "role": "assistant",
                    "content": cls._compact_text(assistant_summary),
                    "agent": response.route.primary_agent,
                    "status": response.next_action,
                },
            ],
            max_recent_messages=max_recent_messages,
        )
        for execution in response.executions:
            for tool_call in execution.tool_calls:
                if tool_call.success:
                    cls._apply_session_context_patch(merged, tool_call.session_context_patch)
        merged.confirmed_tool_names = []
        return merged

    @classmethod
    def _apply_session_context_patch(cls, context: SessionContext, patch: dict[str, object]) -> None:
        if not patch:
            return
        history_summary = patch.get("history_summary")
        if isinstance(history_summary, str) and history_summary.strip():
            context.history_summary = history_summary.strip()
        context.recent_messages = cls._merge_recent_messages(
            context.recent_messages,
            patch.get("recent_messages") if isinstance(patch.get("recent_messages"), list) else [],
            max_recent_messages=20,
        )
        context.active_products = cls._dedupe_strings(
            [
                *context.active_products,
                *(
                    patch.get("active_products")
                    if isinstance(patch.get("active_products"), list)
                    else []
                ),
            ]
        )
        open_ticket_id = patch.get("open_ticket_id")
        if isinstance(open_ticket_id, str) and open_ticket_id.strip():
            context.open_ticket_id = open_ticket_id
        if isinstance(patch.get("attributes"), dict):
            context.attributes = cls._merge_attributes(
                context.attributes,
                patch["attributes"],  # type: ignore[arg-type]
            )

    @staticmethod
    def _merge_recent_messages(
        current: list[dict[str, object]],
        new_items: list[dict[str, object]],
        *,
        max_recent_messages: int,
    ) -> list[dict[str, object]]:
        merged = [dict(item) for item in current]
        merged.extend(dict(item) for item in new_items if isinstance(item, dict))
        if len(merged) <= max_recent_messages:
            return merged
        return merged[-max_recent_messages:]

    @staticmethod
    def _merge_attributes(base: dict[str, object], update: dict[str, object]) -> dict[str, object]:
        merged = dict(base)
        for key, value in update.items():
            existing_value = merged.get(key)
            if isinstance(value, dict) and isinstance(existing_value, dict):
                merged[key] = {**existing_value, **value}
            else:
                merged[key] = value
        return merged

    @staticmethod
    def _merge_history_summary(
        existing: str | None,
        user_query: str,
        assistant_summary: str,
    ) -> str:
        parts = [part.strip() for part in (existing or "").split(" | ") if part.strip()]
        parts.extend(
            [
                f"用户：{ConversationStore._compact_text(user_query, limit=72)}",
                f"助手：{ConversationStore._compact_text(assistant_summary, limit=96)}",
            ]
        )
        return " | ".join(parts[-6:])[:480]

    @staticmethod
    def _dedupe_strings(values: list[object]) -> list[str]:
        deduped: list[str] = []
        for value in values:
            if value is None:
                continue
            normalized = str(value).strip()
            if normalized and normalized not in deduped:
                deduped.append(normalized)
        return deduped

    @staticmethod
    def _compact_text(value: object, *, limit: int = 80) -> str:
        text = " ".join(str(value or "").split())
        return text[:limit] if len(text) > limit else text

    @staticmethod
    def derive_title(user_query: str, *, max_length: int = 48) -> str:
        title = " ".join(user_query.strip().split())
        return title[:max_length] if len(title) > max_length else title

    @staticmethod
    def new_conversation_id() -> str:
        return f"conv_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def new_message_id() -> str:
        return f"msg_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def assistant_message_id(user_message_id: str) -> str:
        return f"asst_{user_message_id}"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _set_status(self, conversation_id: str, status: str) -> ConversationRecord:
        self._maybe_restore_runtime_cache()
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                record = backend.set_status(conversation_id, status).model_copy(deep=True)
                context = backend.get_context(conversation_id) or self._contexts.get(conversation_id) or record.initial_context
                self._save_record_to_runtime_cache(
                    record,
                    context=context,
                )
                with self._lock:
                    self._mirror_record_unlocked(
                        record,
                        context=context,
                    )
                return record
            except ConversationStoreError:
                raise
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            record = self._conversations.get(conversation_id)
            if record is None or (record.status == "deleted" and status != "deleted"):
                raise ConversationStoreError(
                    status_code=404,
                    code="CHAT_CONVERSATION_NOT_FOUND",
                    message=f"Conversation '{conversation_id}' was not found.",
                )
            record.status = status  # type: ignore[assignment]
            record.updated_at = self._now()
            self._persist_unlocked()
            return record.model_copy(deep=True)

    def describe_backend(self) -> dict[str, object]:
        self._maybe_restore_runtime_cache()
        self._maybe_restore_backend()
        runtime_cache = self._describe_runtime_cache()
        backend = self._backend
        if backend is not None:
            description = backend.describe_backend()
            description["fallbackBackend"] = "json-file" if self._file_path else "memory"
            description["fallbackPath"] = str(self._file_path) if self._file_path else None
            description["fallbackWriteMode"] = "degraded-only"
            description["runtimeCache"] = runtime_cache
            return description
        description = {
            "backend": "json-file" if self._file_path else "memory",
            "configured": self._file_path is not None,
            "path": str(self._file_path) if self._file_path else None,
            "degradedFrom": "mysql" if self._backend_error else None,
            "backendError": self._backend_error,
        }
        description["runtimeCache"] = runtime_cache
        return description

    def _maybe_restore_backend(self) -> _MySQLConversationBackend | None:
        if self._backend is not None or not self._mysql_dsn:
            return self._backend
        now = time.monotonic()
        if now < self._next_backend_recovery_at:
            return None
        with self._lock:
            if self._backend is not None or not self._mysql_dsn:
                return self._backend
            now = time.monotonic()
            if now < self._next_backend_recovery_at:
                return None
            backend = _MySQLConversationBackend(self._mysql_dsn)
            try:
                backend.ensure_ready()
            except Exception as exc:
                self._backend_error = f"{exc.__class__.__name__}: {exc}"
                self._next_backend_recovery_at = now + RECOVERY_RETRY_SECONDS
                self._persist_unlocked(force=True)
                return None
            self._backend = backend
            self._backend_error = None
            self._next_backend_recovery_at = 0.0
            self._bootstrap_backend_from_local_unlocked()
            self._maybe_restore_runtime_cache()
            self._bootstrap_runtime_cache_from_local_unlocked()
            self._persist_unlocked()
            return self._backend

    def _degrade_backend(self, exc: Exception) -> None:
        with self._lock:
            self._backend = None
            self._backend_error = f"{exc.__class__.__name__}: {exc}"
            self._next_backend_recovery_at = time.monotonic() + RECOVERY_RETRY_SECONDS
            self._persist_unlocked(force=True)

    def _bootstrap_backend_from_local_unlocked(self) -> None:
        backend = self._backend
        if backend is None or not self._conversations:
            return
        authoritative_conversations: dict[str, ConversationRecord] = {}
        authoritative_messages: dict[str, list[ChatMessageRecord]] = {}
        authoritative_contexts: dict[str, SessionContext] = {}
        authoritative_request_snapshots: dict[tuple[str, str], MessageRequest] = {}
        authoritative_assistant_to_user: dict[tuple[str, str], str] = {}

        for conversation_id, record in self._conversations.items():
            local_context = (self._contexts.get(conversation_id) or record.initial_context).model_copy(deep=True)
            local_messages = [
                item.model_copy(deep=True) for item in self._messages.get(conversation_id, [])
            ]
            local_request_snapshots = {
                key: snapshot.model_copy(deep=True)
                for key, snapshot in self._request_snapshots.items()
                if key[0] == conversation_id
            }
            local_assistant_to_user = {
                key: value
                for key, value in self._assistant_to_user.items()
                if key[0] == conversation_id
            }
            remote_snapshot = backend.export_snapshot(conversation_id)

            if remote_snapshot is None or self._prefer_local_snapshot(
                local_record=record,
                local_message_count=len(local_messages),
                remote_record=remote_snapshot.record,
                remote_message_count=len(remote_snapshot.messages),
            ):
                backend.import_snapshot(
                    conversations={conversation_id: record.model_copy(deep=True)},
                    messages={conversation_id: [item.model_copy(deep=True) for item in local_messages]},
                    contexts={conversation_id: local_context.model_copy(deep=True)},
                    request_snapshots={
                        key: snapshot.model_copy(deep=True)
                        for key, snapshot in local_request_snapshots.items()
                    },
                    assistant_to_user=dict(local_assistant_to_user),
                )
                authoritative_conversations[conversation_id] = record.model_copy(deep=True)
                authoritative_messages[conversation_id] = [
                    item.model_copy(deep=True) for item in local_messages
                ]
                authoritative_contexts[conversation_id] = local_context.model_copy(deep=True)
                authoritative_request_snapshots.update(local_request_snapshots)
                authoritative_assistant_to_user.update(local_assistant_to_user)
                continue

            authoritative_conversations[conversation_id] = remote_snapshot.record.model_copy(deep=True)
            authoritative_messages[conversation_id] = [
                item.model_copy(deep=True) for item in remote_snapshot.messages
            ]
            authoritative_contexts[conversation_id] = remote_snapshot.context.model_copy(deep=True)
            authoritative_request_snapshots.update(
                {
                    key: snapshot.model_copy(deep=True)
                    for key, snapshot in remote_snapshot.request_snapshots.items()
                }
            )
            authoritative_assistant_to_user.update(remote_snapshot.assistant_to_user)

        self._conversations = authoritative_conversations
        self._messages = authoritative_messages
        self._contexts = authoritative_contexts
        self._request_snapshots = authoritative_request_snapshots
        self._assistant_to_user = authoritative_assistant_to_user

    @staticmethod
    def _prefer_local_snapshot(
        *,
        local_record: ConversationRecord,
        local_message_count: int,
        remote_record: ConversationRecord,
        remote_message_count: int,
    ) -> bool:
        local_updated_at = ConversationStore._parse_timestamp(local_record.updated_at)
        remote_updated_at = ConversationStore._parse_timestamp(remote_record.updated_at)
        if local_updated_at is not None and remote_updated_at is not None and local_updated_at != remote_updated_at:
            return local_updated_at > remote_updated_at
        if local_updated_at is not None and remote_updated_at is None:
            return True
        if remote_updated_at is not None and local_updated_at is None:
            return False
        if local_record.total_messages != remote_record.total_messages:
            return local_record.total_messages > remote_record.total_messages
        return local_message_count > remote_message_count

    @staticmethod
    def _parse_timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _record_cache_key(self, conversation_id: str) -> str:
        return f"{self._redis_namespace}:conversation:{conversation_id}"

    def _context_cache_key(self, conversation_id: str) -> str:
        return f"{self._redis_namespace}:context:{conversation_id}"

    def _messages_cache_key(self, conversation_id: str) -> str:
        return f"{self._redis_namespace}:messages:{conversation_id}"

    def _request_snapshot_cache_key(self, conversation_id: str, user_message_id: str) -> str:
        return f"{self._redis_namespace}:request:{conversation_id}:{user_message_id}"

    def _assistant_mapping_cache_key(self, conversation_id: str, assistant_message_id: str) -> str:
        return f"{self._redis_namespace}:assistant:{conversation_id}:{assistant_message_id}"

    def _runtime_cache_enabled(self) -> bool:
        return self._backend is not None and self._redis_client is not None

    def _get_record_from_runtime_cache(self, conversation_id: str) -> ConversationRecord | None:
        if not self._runtime_cache_enabled():
            return None
        client = self._redis_client
        try:
            payload = client.get(self._record_cache_key(conversation_id))
        except Exception as exc:
            self._degrade_runtime_cache(exc)
            return None
        if not isinstance(payload, str) or not payload.strip():
            return None
        try:
            return ConversationRecord.model_validate(json.loads(payload))
        except Exception:
            try:
                client.delete(self._record_cache_key(conversation_id))
            except Exception:
                pass
            return None

    def _get_context_from_runtime_cache(self, conversation_id: str) -> SessionContext | None:
        if not self._runtime_cache_enabled():
            return None
        client = self._redis_client
        try:
            payload = client.get(self._context_cache_key(conversation_id))
        except Exception as exc:
            self._degrade_runtime_cache(exc)
            return None
        if not isinstance(payload, str) or not payload.strip():
            return None
        try:
            return SessionContext.model_validate(json.loads(payload))
        except Exception:
            try:
                client.delete(self._context_cache_key(conversation_id))
            except Exception:
                pass
            return None

    def _get_messages_from_runtime_cache(self, conversation_id: str) -> list[ChatMessageRecord] | None:
        if not self._runtime_cache_enabled():
            return None
        client = self._redis_client
        try:
            payload = client.get(self._messages_cache_key(conversation_id))
        except Exception as exc:
            self._degrade_runtime_cache(exc)
            return None
        if not isinstance(payload, str) or not payload.strip():
            return None
        try:
            raw_items = json.loads(payload)
            if not isinstance(raw_items, list):
                raise ValueError("messages cache payload must be a list")
            return [
                ChatMessageRecord.model_validate(item)
                for item in raw_items
                if isinstance(item, dict)
            ]
        except Exception:
            try:
                client.delete(self._messages_cache_key(conversation_id))
            except Exception:
                pass
            return None

    def _get_request_snapshot_from_runtime_cache(
        self,
        conversation_id: str,
        user_message_id: str,
    ) -> MessageRequest | None:
        if not self._runtime_cache_enabled():
            return None
        client = self._redis_client
        try:
            payload = client.get(self._request_snapshot_cache_key(conversation_id, user_message_id))
        except Exception as exc:
            self._degrade_runtime_cache(exc)
            return None
        if not isinstance(payload, str) or not payload.strip():
            return None
        try:
            return MessageRequest.model_validate(json.loads(payload))
        except Exception:
            try:
                client.delete(self._request_snapshot_cache_key(conversation_id, user_message_id))
            except Exception:
                pass
            return None

    def _get_assistant_mapping_from_runtime_cache(
        self,
        conversation_id: str,
        assistant_message_id: str,
    ) -> str | None:
        if not self._runtime_cache_enabled():
            return None
        client = self._redis_client
        try:
            payload = client.get(self._assistant_mapping_cache_key(conversation_id, assistant_message_id))
        except Exception as exc:
            self._degrade_runtime_cache(exc)
            return None
        if not isinstance(payload, str) or not payload.strip():
            return None
        return payload

    def _save_record_to_runtime_cache(
        self,
        record: ConversationRecord,
        *,
        context: SessionContext,
    ) -> None:
        if not self._runtime_cache_enabled():
            return
        client = self._redis_client
        try:
            client.set(
                self._record_cache_key(record.conversation_id),
                json.dumps(record.model_dump(mode="json"), ensure_ascii=False),
            )
            client.set(
                self._context_cache_key(record.conversation_id),
                json.dumps(context.model_dump(mode="json"), ensure_ascii=False),
            )
        except Exception as exc:
            self._degrade_runtime_cache(exc)

    def _save_context_to_runtime_cache(self, conversation_id: str, context: SessionContext) -> None:
        if not self._runtime_cache_enabled():
            return
        client = self._redis_client
        try:
            client.set(
                self._context_cache_key(conversation_id),
                json.dumps(context.model_dump(mode="json"), ensure_ascii=False),
            )
        except Exception as exc:
            self._degrade_runtime_cache(exc)

    def _save_messages_to_runtime_cache(
        self,
        conversation_id: str,
        messages: list[ChatMessageRecord],
    ) -> None:
        if not self._runtime_cache_enabled():
            return
        client = self._redis_client
        try:
            client.set(
                self._messages_cache_key(conversation_id),
                json.dumps([item.model_dump(mode="json") for item in messages], ensure_ascii=False),
            )
        except Exception as exc:
            self._degrade_runtime_cache(exc)

    def _save_request_snapshot_to_runtime_cache(
        self,
        conversation_id: str,
        user_message_id: str,
        message_request: MessageRequest,
    ) -> None:
        if not self._runtime_cache_enabled():
            return
        client = self._redis_client
        try:
            client.set(
                self._request_snapshot_cache_key(conversation_id, user_message_id),
                json.dumps(message_request.model_dump(mode="json"), ensure_ascii=False),
            )
        except Exception as exc:
            self._degrade_runtime_cache(exc)

    def _save_assistant_mapping_to_runtime_cache(
        self,
        conversation_id: str,
        assistant_message_id: str,
        user_message_id: str,
    ) -> None:
        if not self._runtime_cache_enabled():
            return
        client = self._redis_client
        try:
            client.set(
                self._assistant_mapping_cache_key(conversation_id, assistant_message_id),
                user_message_id,
            )
        except Exception as exc:
            self._degrade_runtime_cache(exc)

    def _save_exchange_to_runtime_cache(
        self,
        record: ConversationRecord,
        messages: list[ChatMessageRecord],
        *,
        context: SessionContext,
        user_message_id: str,
        assistant_message_id: str,
        message_request: MessageRequest,
    ) -> None:
        self._save_record_to_runtime_cache(record, context=context)
        self._save_messages_to_runtime_cache(record.conversation_id, messages)
        self._save_request_snapshot_to_runtime_cache(record.conversation_id, user_message_id, message_request)
        self._save_assistant_mapping_to_runtime_cache(record.conversation_id, assistant_message_id, user_message_id)

    def _bootstrap_runtime_cache_from_local_unlocked(self) -> None:
        if not self._runtime_cache_enabled() or not self._conversations:
            return
        for conversation_id, record in self._conversations.items():
            context = self._contexts.get(conversation_id) or record.initial_context
            self._save_record_to_runtime_cache(record.model_copy(deep=True), context=context.model_copy(deep=True))
            self._save_messages_to_runtime_cache(
                conversation_id,
                [item.model_copy(deep=True) for item in self._messages.get(conversation_id, [])],
            )
        for (conversation_id, user_message_id), snapshot in self._request_snapshots.items():
            self._save_request_snapshot_to_runtime_cache(
                conversation_id,
                user_message_id,
                snapshot.model_copy(deep=True),
            )
        for (conversation_id, assistant_message_id), user_message_id in self._assistant_to_user.items():
            self._save_assistant_mapping_to_runtime_cache(
                conversation_id,
                assistant_message_id,
                user_message_id,
            )

    def _clear_runtime_cache(self) -> None:
        client = self._redis_client
        if client is None:
            return
        try:
            for key in client.scan_iter(match=f"{self._redis_namespace}:*"):
                client.delete(key)
        except Exception as exc:
            self._degrade_runtime_cache(exc)

    def _describe_runtime_cache(self) -> dict[str, object]:
        return {
            "backend": "redis-json" if self._runtime_cache_enabled() else "memory",
            "redisConfigured": bool(self._redis_url),
            "redisNamespace": self._redis_namespace if self._redis_url else None,
            "degradedFrom": "redis-json" if self._cache_error else None,
            "backendError": self._cache_error,
        }

    def _maybe_restore_runtime_cache(self) -> None:
        if self._redis_client is not None or not self._redis_url or self._backend is None:
            return
        now = time.monotonic()
        if now < self._next_cache_recovery_at:
            return
        with self._lock:
            if self._redis_client is not None or not self._redis_url or self._backend is None:
                return
            now = time.monotonic()
            if now < self._next_cache_recovery_at:
                return
            client = build_redis_client(self._redis_url)
            if client is None:
                self._cache_error = "Redis connection unavailable."
                self._next_cache_recovery_at = now + RECOVERY_RETRY_SECONDS
                return
            self._redis_client = client
            self._cache_error = None
            self._next_cache_recovery_at = 0.0
            self._bootstrap_runtime_cache_from_local_unlocked()

    def _degrade_runtime_cache(self, exc: Exception) -> None:
        with self._lock:
            self._redis_client = None
            self._cache_error = f"{exc.__class__.__name__}: {exc}"
            self._next_cache_recovery_at = time.monotonic() + RECOVERY_RETRY_SECONDS

    def _persist_unlocked(self, *, force: bool = False) -> None:
        if self._file_path is None:
            return
        if not force and self._backend is not None:
            self._remove_fallback_file_unlocked()
            return
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "conversations": {
                conversation_id: record.model_dump(mode="json")
                for conversation_id, record in self._conversations.items()
            },
            "messages": {
                conversation_id: [item.model_dump(mode="json") for item in messages]
                for conversation_id, messages in self._messages.items()
            },
            "contexts": {
                conversation_id: context.model_dump(mode="json")
                for conversation_id, context in self._contexts.items()
            },
            "request_snapshots": {
                f"{conversation_id}::{message_id}": snapshot.model_dump(mode="json")
                for (conversation_id, message_id), snapshot in self._request_snapshots.items()
            },
            "assistant_to_user": {
                f"{conversation_id}::{assistant_message_id}": user_message_id
                for (conversation_id, assistant_message_id), user_message_id in self._assistant_to_user.items()
            },
        }
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self._file_path.parent,
            prefix=f"{self._file_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            tmp_path = Path(handle.name)
        tmp_path.replace(self._file_path)

    def _remove_fallback_file_unlocked(self) -> None:
        if self._file_path is None:
            return
        try:
            self._file_path.unlink()
        except FileNotFoundError:
            return
        except OSError:
            return

    def _mirror_record_unlocked(
        self,
        record: ConversationRecord,
        *,
        context: SessionContext,
    ) -> None:
        conversation_id = record.conversation_id
        self._conversations[conversation_id] = record.model_copy(deep=True)
        self._messages.setdefault(conversation_id, [])
        self._contexts[conversation_id] = context.model_copy(deep=True)
        self._persist_unlocked()

    def _mirror_exchange_unlocked(
        self,
        record: ConversationRecord,
        messages: list[ChatMessageRecord],
        *,
        context: SessionContext,
        user_message_id: str,
        assistant_message_id: str,
        message_request: MessageRequest,
    ) -> None:
        conversation_id = record.conversation_id
        self._conversations[conversation_id] = record.model_copy(deep=True)
        self._messages[conversation_id] = [item.model_copy(deep=True) for item in messages]
        self._contexts[conversation_id] = context.model_copy(deep=True)
        self._request_snapshots[(conversation_id, user_message_id)] = message_request.model_copy(deep=True)
        self._assistant_to_user[(conversation_id, assistant_message_id)] = user_message_id
        self._persist_unlocked()

    @staticmethod
    def _build_message_page(
        items: list[ChatMessageRecord],
        *,
        cursor: str | None,
        page_size: int,
    ) -> SessionMessagesPage:
        start_index = 0
        if cursor:
            for index, item in enumerate(items):
                if item.message_id == cursor:
                    start_index = index + 1
                    break
        page_items = items[start_index : start_index + page_size]
        has_more = start_index + page_size < len(items)
        next_cursor = page_items[-1].message_id if has_more and page_items else None
        return SessionMessagesPage(
            items=[item.model_copy(deep=True) for item in page_items],
            next_cursor=next_cursor,
            has_more=has_more,
        )

    @staticmethod
    def _build_retry_request_from_snapshot(
        snapshot: MessageRequest,
        *,
        override_input: str | None,
    ) -> MessageRequest:
        return snapshot.model_copy(
            deep=True,
            update={
                "message_id": None,
                "user_query": override_input or snapshot.user_query,
                "trace": None,
            },
        )

    @staticmethod
    def _latest_message_id_from_items(
        items: list[ChatMessageRecord],
        *,
        conversation_id: str,
        role: str | None,
    ) -> str:
        for item in reversed(items):
            if role is None or item.role == role:
                return item.message_id
        raise ConversationStoreError(
            status_code=404,
            code="CHAT_MESSAGE_NOT_FOUND",
            message=f"No messages were found in conversation '{conversation_id}'.",
        )

    def _load_unlocked(self, file_path: Path | None) -> None:
        self._conversations.clear()
        self._messages.clear()
        self._contexts.clear()
        self._request_snapshots.clear()
        self._assistant_to_user.clear()
        if file_path is None or not file_path.exists():
            return
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        self._conversations = {
            str(conversation_id): ConversationRecord.model_validate(raw_record)
            for conversation_id, raw_record in payload.get("conversations", {}).items()
        }
        self._messages = {
            str(conversation_id): [
                ChatMessageRecord.model_validate(item)
                for item in raw_messages
                if isinstance(item, dict)
            ]
            for conversation_id, raw_messages in payload.get("messages", {}).items()
            if isinstance(raw_messages, list)
        }
        self._contexts = {
            str(conversation_id): SessionContext.model_validate(raw_context)
            for conversation_id, raw_context in payload.get("contexts", {}).items()
        }
        self._request_snapshots = {
            (conversation_id, message_id): MessageRequest.model_validate(raw_snapshot)
            for composite_key, raw_snapshot in payload.get("request_snapshots", {}).items()
            for conversation_id, _, message_id in [str(composite_key).partition("::")]
            if conversation_id and message_id
        }
        self._assistant_to_user = {
            (conversation_id, assistant_message_id): str(user_message_id)
            for composite_key, user_message_id in payload.get("assistant_to_user", {}).items()
            for conversation_id, _, assistant_message_id in [str(composite_key).partition("::")]
            if conversation_id and assistant_message_id
        }
