from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_CLEAR_MARKER = "[旧工具结果已清理]"

# Default: clear tool results older than 60 minutes
_DEFAULT_TIME_GAP_MINUTES = 60

# Clear tool results exceeding this character count
_DEFAULT_SIZE_THRESHOLD_CHARS = 3000


def micro_compact_messages(
    messages: list[dict[str, Any]],
    *,
    time_gap_minutes: int = _DEFAULT_TIME_GAP_MINUTES,
    size_threshold_chars: int = _DEFAULT_SIZE_THRESHOLD_CHARS,
    now_iso: str | None = None,
) -> list[dict[str, Any]]:
    """Lightweight old tool result cleanup. No LLM needed.

    Rules:
    1. If a tool role message's content length > size_threshold_chars
       and it's more than time_gap_minutes old → clear it.
    2. Clearing: replace content with _CLEAR_MARKER, keep tool_call_id.
    """
    if not messages:
        return messages

    now = datetime.fromisoformat(now_iso) if now_iso else datetime.now(UTC)
    result: list[dict[str, Any]] = []
    most_recent_timestamp: datetime | None = None

    for msg in messages:
        role = msg.get("role", "")
        created_at = msg.get("created_at")

        # Track most recent message timestamp (from any role)
        if created_at:
            try:
                msg_time = datetime.fromisoformat(created_at)
                if most_recent_timestamp is None or msg_time > most_recent_timestamp:
                    most_recent_timestamp = msg_time
            except (ValueError, TypeError):
                pass

        # Check if tool result needs clearing
        if role == "tool":
            # Skip messages already micro-compacted
            if msg.get("_micro_compacted"):
                result.append(msg)
                continue

            content = msg.get("content", "")
            content_len = len(str(content)) if content else 0
            should_clear = False

            # Condition 1: content too large
            if content_len > size_threshold_chars:
                should_clear = True

            # Condition 2: time gap too long (and content not trivially small)
            if (
                most_recent_timestamp
                and created_at
                and content_len > 500
            ):
                try:
                    msg_time = datetime.fromisoformat(created_at)
                    gap = (most_recent_timestamp - msg_time).total_seconds() / 60
                    if gap > time_gap_minutes:
                        should_clear = True
                except (ValueError, TypeError):
                    pass

            if should_clear:
                cleaned = dict(msg)
                cleaned["content"] = _CLEAR_MARKER
                cleaned["_micro_compacted"] = True
                result.append(cleaned)
                continue

        result.append(msg)

    cleared_count = sum(1 for m in result if m.get("_micro_compacted"))
    if cleared_count:
        logger.info("micro-compact cleared %d tool results", cleared_count)

    return result
