from __future__ import annotations

from dataclasses import dataclass

from app.models.orchestration import (
    ChatMessageRecord,
    ConversationRecord,
    MessageRequest,
    SessionContext,
)

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
