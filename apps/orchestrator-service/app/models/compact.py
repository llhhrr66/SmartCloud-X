from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CompactionStrategy(str, Enum):
    FULL = "full"
    PARTIAL = "partial"
    UP_TO = "up_to"


class CompactionMetadata(BaseModel):
    """Record of a single compaction operation, stored in SessionContext.attributes."""

    strategy: CompactionStrategy
    original_message_count: int
    original_token_estimate: int
    compacted_message_count: int
    compacted_token_estimate: int
    compacted_at: str
    compact_summary: str = ""
    rounds_compacted: list[int] = Field(default_factory=list)
    trigger_reason: str = "auto_threshold"


class SessionMemoryRecord(BaseModel):
    """Session memory persisted in Redis."""

    conversation_id: str
    sections: dict[str, str] = Field(default_factory=dict)
    total_tokens_estimate: int = 0
    version: int = 1
    extracted_at: str = ""
    updated_at: str = ""


class SessionMemoryConfig(BaseModel):
    """Thresholds for session memory extraction."""

    min_tokens_to_init: int = 8000
    tokens_between_updates: int = 4000
    tool_calls_between_updates: int = 3
    max_tokens_per_section: int = 2000
    max_total_tokens: int = 12000
