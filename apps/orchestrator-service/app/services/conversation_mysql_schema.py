from __future__ import annotations

from app.services import runtime_mysql

CONVERSATION_TABLE = "orchestrator_conversations"
MESSAGE_TABLE = "orchestrator_messages"
SNAPSHOT_TABLE = "orchestrator_request_snapshots"
ASSISTANT_SNAPSHOT_TABLE = "orchestrator_assistant_request_snapshots"
SAGA_EVENT_TABLE = "orchestrator_saga_events"


def ensure_schema(
    cursor,
    *,
    conversation_table: str,
    message_table: str,
    snapshot_table: str,
    assistant_snapshot_table: str,
    saga_event_table: str,
) -> None:
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS `{conversation_table}` (
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
        CREATE TABLE IF NOT EXISTS `{message_table}` (
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
        CREATE TABLE IF NOT EXISTS `{snapshot_table}` (
            conversation_id VARCHAR(128) NOT NULL,
            user_message_id VARCHAR(128) NOT NULL,
            assistant_message_id VARCHAR(128) NULL,
            request_json LONGTEXT NOT NULL,
            PRIMARY KEY (conversation_id, user_message_id)
        )
        """
    )
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS `{assistant_snapshot_table}` (
            conversation_id VARCHAR(128) NOT NULL,
            assistant_message_id VARCHAR(128) NOT NULL,
            user_message_id VARCHAR(128) NOT NULL,
            request_json LONGTEXT NOT NULL,
            PRIMARY KEY (conversation_id, assistant_message_id)
        )
        """
    )
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS `{saga_event_table}` (
            event_id VARCHAR(128) PRIMARY KEY,
            conversation_id VARCHAR(128) NOT NULL,
            user_message_id VARCHAR(128) NULL,
            assistant_message_id VARCHAR(128) NULL,
            saga_name VARCHAR(128) NOT NULL,
            step VARCHAR(128) NOT NULL,
            status VARCHAR(64) NOT NULL,
            error_type VARCHAR(128) NULL,
            error_message TEXT NULL,
            created_at VARCHAR(128) NOT NULL,
            payload_json LONGTEXT NOT NULL
        )
        """
    )
    runtime_mysql.create_index_if_missing(
        cursor,
        table_name=conversation_table,
        index_name=f"idx_{conversation_table}_updated",
        columns=("updated_at", "conversation_id"),
    )
    runtime_mysql.create_index_if_missing(
        cursor,
        table_name=conversation_table,
        index_name=f"idx_{conversation_table}_scene_status",
        columns=("scene", "status", "updated_at"),
    )
    runtime_mysql.create_index_if_missing(
        cursor,
        table_name=message_table,
        index_name=f"idx_{message_table}_conversation_sequence",
        columns=("conversation_id", "created_at", "sequence_no", "message_id"),
    )
    runtime_mysql.create_index_if_missing(
        cursor,
        table_name=snapshot_table,
        index_name=f"idx_{snapshot_table}_assistant_message",
        columns=("conversation_id", "assistant_message_id"),
    )
    runtime_mysql.create_index_if_missing(
        cursor,
        table_name=saga_event_table,
        index_name=f"idx_{saga_event_table}_conversation_created",
        columns=("conversation_id", "created_at"),
    )
    runtime_mysql.create_index_if_missing(
        cursor,
        table_name=saga_event_table,
        index_name=f"idx_{saga_event_table}_status_created",
        columns=("status", "created_at"),
    )
