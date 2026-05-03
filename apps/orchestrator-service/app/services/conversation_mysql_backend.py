from __future__ import annotations

import json

from app.models.orchestration import (
    ChatMessageRecord,
    ConversationRecord,
    MessageRequest,
    SceneName,
    SessionContext,
    SessionCreateRequest,
    SessionMessagesPage,
)
from app.services import runtime_mysql
from app.services.conversation_context_merge import ConversationContextMerger
from app.services.conversation_mysql_schema import (
    ASSISTANT_SNAPSHOT_TABLE,
    CONVERSATION_TABLE,
    MESSAGE_TABLE,
    SAGA_EVENT_TABLE,
    SNAPSHOT_TABLE,
    ensure_schema,
)
from app.services.conversation_mysql_writes import _MySQLWriteMixin
from app.services.conversation_types import (
    ConversationStoreError,
    _ConversationSnapshotBundle,
)
from app.services.mongo_runtime import DisabledConversationMongoRuntime


class _MySQLConversationBackend(_MySQLWriteMixin):
    """MySQL-backed conversation repository (authority store).

    Inherits write/exchange operations from _MySQLWriteMixin.
    Owns read operations, lifecycle, and schema management.
    """

    CONVERSATION_TABLE = CONVERSATION_TABLE
    MESSAGE_TABLE = MESSAGE_TABLE
    SNAPSHOT_TABLE = SNAPSHOT_TABLE
    ASSISTANT_SNAPSHOT_TABLE = ASSISTANT_SNAPSHOT_TABLE
    SAGA_EVENT_TABLE = SAGA_EVENT_TABLE

    def __init__(
        self,
        mysql_dsn: str,
        *,
        mongo_runtime: DisabledConversationMongoRuntime | object | None = None,
    ) -> None:
        self._mysql_dsn = mysql_dsn
        self._mongo_runtime = mongo_runtime or DisabledConversationMongoRuntime()

    def _ensure_schema(self, cursor) -> None:
        ensure_schema(
            cursor,
            conversation_table=self.CONVERSATION_TABLE,
            message_table=self.MESSAGE_TABLE,
            snapshot_table=self.SNAPSHOT_TABLE,
            assistant_snapshot_table=self.ASSISTANT_SNAPSHOT_TABLE,
            saga_event_table=self.SAGA_EVENT_TABLE,
        )

    def ensure_ready(self) -> None:
        connection = None
        try:
            connection = runtime_mysql.connect(self._mysql_dsn)
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
            connection.commit()
        finally:
            if connection is not None:
                connection.close()

    def clear(self) -> None:
        if getattr(self._mongo_runtime, "enabled", False):
            self._mongo_runtime.clear()
        connection = None
        try:
            connection = runtime_mysql.connect(self._mysql_dsn)
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(f"DELETE FROM `{self.SAGA_EVENT_TABLE}`")
                cursor.execute(f"DELETE FROM `{self.ASSISTANT_SNAPSHOT_TABLE}`")
                cursor.execute(f"DELETE FROM `{self.SNAPSHOT_TABLE}`")
                cursor.execute(f"DELETE FROM `{self.MESSAGE_TABLE}`")
                cursor.execute(f"DELETE FROM `{self.CONVERSATION_TABLE}`")
            connection.commit()
        finally:
            if connection is not None:
                connection.close()

    def create(self, request: SessionCreateRequest) -> ConversationRecord:
        conversation_id = ConversationContextMerger.new_conversation_id()
        now = ConversationContextMerger.now()
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
            now = ConversationContextMerger.now()
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
                    SELECT COUNT(*) AS total_count FROM `{self.CONVERSATION_TABLE}`
                    WHERE {where_clause}
                    """,
                    tuple(params),
                )
                total_row = cursor.fetchone() or {}
                cursor.execute(
                    f"""
                    SELECT payload_json FROM `{self.CONVERSATION_TABLE}`
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
        return [item.model_copy(deep=True) for item in records], int(total_row.get("total_count", 0))

    def update_title(self, conversation_id: str, title: str) -> ConversationRecord:
        record = self._require_record(conversation_id)
        record.title = title
        record.updated_at = ConversationContextMerger.now()
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
        record.updated_at = ConversationContextMerger.now()
        self._persist_record(record, context=self.get_context(conversation_id) or SessionContext())
        return record

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
                        SELECT created_at, sequence_no FROM `{self.MESSAGE_TABLE}`
                        WHERE conversation_id = %s AND message_id = %s LIMIT 1
                        """,
                        (conversation_id, cursor),
                    )
                    row = sql_cursor.fetchone()
                    if row:
                        cursor_created_at = str(row["created_at"])
                        cursor_sequence = int(row["sequence_no"])
                sql = f"SELECT payload_json FROM `{self.MESSAGE_TABLE}` WHERE conversation_id = %s"
                if cursor_created_at is not None:
                    sql += """
                        AND (
                            created_at > %s
                            OR (created_at = %s AND sequence_no > %s)
                            OR (created_at = %s AND sequence_no = %s AND message_id > %s)
                        )
                    """
                    params.extend([
                        cursor_created_at, cursor_created_at, cursor_sequence,
                        cursor_created_at, cursor_sequence, cursor,
                    ])
                sql += " ORDER BY created_at ASC, sequence_no ASC, message_id ASC LIMIT %s"
                params.append(page_size + 1)
                sql_cursor.execute(sql, tuple(params))
                rows = sql_cursor.fetchall() or []
        finally:
            connection.close()
        items = [ChatMessageRecord.model_validate(json.loads(row["payload_json"])) for row in rows]
        page_items = items[:page_size]
        has_more = len(items) > page_size
        return SessionMessagesPage(
            items=[item.model_copy(deep=True) for item in page_items],
            next_cursor=page_items[-1].message_id if has_more and page_items else None,
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
            update={"message_id": None, "user_query": override_input or snapshot.user_query, "trace": None},
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
                        SELECT message_id FROM `{self.MESSAGE_TABLE}`
                        WHERE conversation_id = %s
                        ORDER BY created_at DESC, sequence_no DESC, message_id DESC LIMIT 1
                        """,
                        (conversation_id,),
                    )
                else:
                    cursor.execute(
                        f"""
                        SELECT message_id FROM `{self.MESSAGE_TABLE}`
                        WHERE conversation_id = %s AND role = %s
                        ORDER BY created_at DESC, sequence_no DESC, message_id DESC LIMIT 1
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
                    SELECT user_message_id FROM `{self.ASSISTANT_SNAPSHOT_TABLE}`
                    WHERE conversation_id = %s AND assistant_message_id = %s LIMIT 1
                    """,
                    (conversation_id, message_id),
                )
                row = cursor.fetchone()
                if row is None:
                    cursor.execute(
                        f"""
                        SELECT user_message_id FROM `{self.SNAPSHOT_TABLE}`
                        WHERE conversation_id = %s AND assistant_message_id = %s LIMIT 1
                        """,
                        (conversation_id, message_id),
                    )
                    row = cursor.fetchone()
        finally:
            connection.close()
        return str(row["user_message_id"]) if row else message_id

    def list_saga_events(
        self,
        *,
        conversation_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        conditions: list[str] = []
        params: list[object] = []
        if conversation_id:
            conditions.append("conversation_id = %s")
            params.append(conversation_id)
        if status:
            conditions.append("status = %s")
            params.append(status)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"""
                    SELECT event_id, conversation_id, user_message_id, assistant_message_id,
                           saga_name, step, status, error_type, error_message, created_at, payload_json
                    FROM `{self.SAGA_EVENT_TABLE}`
                    {where_clause}
                    ORDER BY created_at DESC, event_id DESC
                    LIMIT %s
                    """,
                    (*params, max(min(limit, 200), 1)),
                )
                rows = cursor.fetchall() or []
        finally:
            connection.close()
        events: list[dict[str, object]] = []
        for row in rows:
            payload_raw = row.get("payload_json") or "{}"
            try:
                payload = json.loads(payload_raw)
            except Exception:
                payload = {}
            events.append(
                {
                    "event_id": row["event_id"],
                    "conversation_id": row["conversation_id"],
                    "user_message_id": row.get("user_message_id"),
                    "assistant_message_id": row.get("assistant_message_id"),
                    "saga_name": row["saga_name"],
                    "step": row["step"],
                    "status": row["status"],
                    "error_type": row.get("error_type"),
                    "error_message": row.get("error_message"),
                    "created_at": row["created_at"],
                    "payload": payload,
                }
            )
        return events

    def describe_backend(self) -> dict[str, object]:
        return {
            "backend": "mysql",
            "configured": True,
            "tables": {
                "conversations": self.CONVERSATION_TABLE,
                "messages": self.MESSAGE_TABLE,
                "snapshots": self.SNAPSHOT_TABLE,
                "assistantSnapshots": self.ASSISTANT_SNAPSHOT_TABLE,
                "sagaEvents": self.SAGA_EVENT_TABLE,
            },
            "documentStore": self._mongo_runtime.describe_backend(),
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
                    FROM `{self.SNAPSHOT_TABLE}` WHERE conversation_id = %s
                    """,
                    (conversation_id,),
                )
                rows = cursor.fetchall() or []
                cursor.execute(
                    f"""
                    SELECT user_message_id, assistant_message_id, request_json
                    FROM `{self.ASSISTANT_SNAPSHOT_TABLE}` WHERE conversation_id = %s
                    """,
                    (conversation_id,),
                )
                assistant_rows = cursor.fetchall() or []
        finally:
            connection.close()
        for row in rows:
            uid = str(row["user_message_id"])
            request_snapshots[(conversation_id, uid)] = MessageRequest.model_validate(
                json.loads(row["request_json"])
            )
            aid = row.get("assistant_message_id")
            if aid:
                assistant_to_user[(conversation_id, str(aid))] = uid
        for row in assistant_rows:
            uid = str(row["user_message_id"])
            aid = str(row["assistant_message_id"])
            request_snapshots[(conversation_id, aid)] = MessageRequest.model_validate(
                json.loads(row["request_json"])
            )
            assistant_to_user[(conversation_id, aid)] = uid
        return _ConversationSnapshotBundle(
            record=record.model_copy(deep=True),
            messages=[m.model_copy(deep=True) for m in messages],
            context=context.model_copy(deep=True),
            request_snapshots={k: v.model_copy(deep=True) for k, v in request_snapshots.items()},
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
            (conv_id, uid): aid
            for (conv_id, aid), uid in assistant_to_user.items()
        }
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                for conv_id, record in conversations.items():
                    context = contexts.get(conv_id) or record.initial_context
                    self._write_conversation(cursor, record, context=context)
                for conv_id, conv_messages in messages.items():
                    for seq, msg in enumerate(conv_messages, start=1):
                        cursor.execute(
                            f"""
                            REPLACE INTO `{self.MESSAGE_TABLE}` (
                                conversation_id, message_id, role, created_at, sequence_no, payload_json
                            ) VALUES (%s, %s, %s, %s, %s, %s)
                            """,
                            (
                                conv_id, msg.message_id, msg.role, msg.created_at, seq,
                                json.dumps(msg.model_dump(mode="json"), ensure_ascii=False),
                            ),
                        )
                for (conv_id, uid), request in request_snapshots.items():
                    aid = assistant_by_user.get((conv_id, uid))
                    if aid is None:
                        continue
                    self._write_assistant_request_snapshot(
                        cursor,
                        conversation_id=conv_id,
                        user_message_id=uid,
                        assistant_message_id=aid,
                        message_request=request,
                    )
                for (conv_id, aid), uid in assistant_to_user.items():
                    request = request_snapshots.get((conv_id, aid)) or request_snapshots.get((conv_id, uid))
                    if request is None:
                        continue
                    cursor.execute(
                        f"""
                        REPLACE INTO `{self.ASSISTANT_SNAPSHOT_TABLE}` (
                            conversation_id, assistant_message_id, user_message_id, request_json
                        ) VALUES (%s, %s, %s, %s)
                        """,
                        (
                            conv_id, aid, uid,
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
        if getattr(self._mongo_runtime, "enabled", False):
            msgs = self._mongo_runtime.fetch_messages(conversation_id)
            if msgs is not None:
                return msgs
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"""
                    SELECT payload_json FROM `{self.MESSAGE_TABLE}`
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
        if getattr(self._mongo_runtime, "enabled", False):
            snapshot = self._mongo_runtime.get_request_snapshot(conversation_id, message_id=message_id)
            if snapshot is not None:
                return snapshot
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"""
                    SELECT request_json FROM `{self.SNAPSHOT_TABLE}`
                    WHERE conversation_id = %s AND user_message_id = %s LIMIT 1
                    """,
                    (conversation_id, message_id),
                )
                row = cursor.fetchone()
                if row is None:
                    cursor.execute(
                        f"""
                        SELECT request_json FROM `{self.ASSISTANT_SNAPSHOT_TABLE}`
                        WHERE conversation_id = %s AND assistant_message_id = %s LIMIT 1
                        """,
                        (conversation_id, message_id),
                    )
                    row = cursor.fetchone()
        finally:
            connection.close()
        return MessageRequest.model_validate(json.loads(row["request_json"])) if row else None
