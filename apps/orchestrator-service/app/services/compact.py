from __future__ import annotations

import logging
import re
from typing import Any

from app.core.config import Settings, get_settings
from app.models.compact import (
    CompactionMetadata,
    CompactionStrategy,
)
from app.services.token_counter import TokenCounter, get_context_window_size
from app.services._compact_utils import normalize_openai_base_url, now_iso

logger = logging.getLogger(__name__)

# Auto-compact buffer tokens (like Claude Code's 13K buffer)
_COMPACT_BUFFER_TOKENS = 13000

# Circuit breaker: max consecutive failures before tripping
_CIRCUIT_BREAKER_MAX_FAILURES = 3

# Max tokens per group for partial compaction split point
_MAX_TOKENS_PER_GROUP = 40000


class AutoCompactTrigger:
    """Auto-compaction trigger with circuit breaker.

    Inspired by Claude Code's autoCompact.ts:
    - threshold = context_window - buffer_tokens
    - If estimated tokens >= threshold, trigger compaction
    - Circuit breaker: after N consecutive failures, stop trying
    """

    def __init__(
        self,
        settings: Settings | None = None,
        token_counter: TokenCounter | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._counter = token_counter or TokenCounter()
        self._consecutive_failures: int = 0
        self._circuit_open: bool = False

    def should_compact(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
    ) -> tuple[bool, int, int]:
        """Determine if compaction should be triggered.

        Returns:
            (should_compact, estimated_tokens, threshold)
        """
        if self._circuit_open:
            logger.debug("auto-compact circuit breaker open, skipping")
            return False, 0, 0

        context_window = get_context_window_size(model or self._settings.llm_model)
        threshold = max(
            context_window - _COMPACT_BUFFER_TOKENS,
            self._settings.compact_min_threshold_tokens,
        )
        estimated = self._counter.estimate_messages(messages)
        should = estimated >= threshold
        if should:
            logger.info(
                "auto-compact triggered: estimated=%d >= threshold=%d (window=%d)",
                estimated,
                threshold,
                context_window,
            )
        return should, estimated, threshold

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._circuit_open = False

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= _CIRCUIT_BREAKER_MAX_FAILURES:
            self._circuit_open = True
            logger.warning(
                "auto-compact circuit breaker opened after %d consecutive failures",
                self._consecutive_failures,
            )


def _extract_summary_from_response(text: str) -> str:
    """Extract <summary> tag content from LLM response."""
    match = re.search(r"<summary>(.*?)</summary>", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fallback: if no tags, use everything after </analysis>
    analysis_match = re.search(r"</analysis>(.*)", text, re.DOTALL)
    if analysis_match:
        return analysis_match.group(1).strip()
    return text.strip()


def _format_messages_for_compact(messages: list[dict[str, Any]]) -> str:
    """Format messages as plain text for compaction prompt."""
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, list):
            # Multimodal: extract text parts only
            text_parts = [
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            content = " ".join(text_parts)
        content = str(content) if content else ""
        # Truncate overly long single messages
        if len(content) > 2000:
            content = content[:2000] + "...[truncated]"
        lines.append(f"[{role}] {content}")
        # Tool call info
        tool_calls = msg.get("tool_calls")
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                func = tc.get("function", {})
                name = func.get("name", "")
                args = func.get("arguments", "")
                if len(args) > 500:
                    args = args[:500] + "...[truncated]"
                lines.append(f"  [tool_call] {name}({args})")
    return "\n".join(lines)


def _group_messages_by_round(
    messages: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Group messages by API round.

    Inspired by Claude Code's groupMessagesByApiRound():
    A new assistant message (without tool_calls) starts a new round.
    """
    if not messages:
        return []
    groups: list[list[dict[str, Any]]] = []
    current_group: list[dict[str, Any]] = [messages[0]]
    for msg in messages[1:]:
        role = msg.get("role", "")
        # New assistant message (not a tool result) = new round
        if role == "assistant" and not msg.get("tool_calls"):
            groups.append(current_group)
            current_group = [msg]
        else:
            current_group.append(msg)
    if current_group:
        groups.append(current_group)
    return groups


def compact_conversation(
    messages: list[dict[str, Any]],
    *,
    strategy: CompactionStrategy = CompactionStrategy.FULL,
    pivot_message_id: str | None = None,
    settings: Settings | None = None,
    token_counter: TokenCounter | None = None,
) -> tuple[list[dict[str, Any]], CompactionMetadata]:
    """Core compaction function.

    Args:
        messages: Original message list (OpenAI format)
        strategy: Compaction strategy
        pivot_message_id: Pivot message ID for UP_TO strategy

    Returns:
        (compacted_messages, metadata)
    """
    _settings = settings or get_settings()
    _counter = token_counter or TokenCounter()
    original_token_est = _counter.estimate_messages(messages)

    groups = _group_messages_by_round(messages)

    if strategy == CompactionStrategy.FULL:
        return _compact_full(messages, groups, original_token_est, _settings, _counter)
    elif strategy == CompactionStrategy.PARTIAL:
        return _compact_partial(messages, groups, original_token_est, _settings, _counter)
    elif strategy == CompactionStrategy.UP_TO:
        return _compact_up_to(
            messages,
            groups,
            original_token_est,
            pivot_message_id,
            _settings,
            _counter,
        )
    else:
        raise ValueError(f"unknown compaction strategy: {strategy}")


def _compact_full(
    all_messages: list[dict[str, Any]],
    groups: list[list[dict[str, Any]]],
    original_token_est: int,
    settings: Settings,
    counter: TokenCounter,
) -> tuple[list[dict[str, Any]], CompactionMetadata]:
    """Full compaction: all messages → LLM summary, keep recent N rounds raw."""
    from app.services.compact_prompts import build_base_compact_prompt

    retain_rounds = settings.compact_retain_recent_rounds
    if retain_rounds < len(groups):
        # Split by round groups, not by raw message count
        groups_to_compact = groups[: len(groups) - retain_rounds]
        groups_to_retain = groups[len(groups) - retain_rounds :]
        messages_to_compact = [msg for g in groups_to_compact for msg in g]
        retained = [msg for g in groups_to_retain for msg in g]
    else:
        messages_to_compact = []
        retained = all_messages

    if not messages_to_compact:
        meta = CompactionMetadata(
            strategy=CompactionStrategy.FULL,
            original_message_count=len(all_messages),
            original_token_estimate=original_token_est,
            compacted_message_count=0,
            compacted_token_estimate=0,
            compacted_at=_now_iso(),
            compact_summary="",
            rounds_compacted=[],
            trigger_reason="no_messages_to_compact",
        )
        return all_messages, meta

    text_to_compact = _format_messages_for_compact(messages_to_compact)
    prompt = build_base_compact_prompt(text_to_compact)
    summary = _call_llm_for_compact(prompt, settings)

    summary_message = {
        "role": "system",
        "content": f"[对话历史压缩摘要]\n\n{summary}",
        "name": "compacted_history",
    }
    compacted = [summary_message, *retained]

    compacted_token_est = counter.estimate_messages(compacted)
    meta = CompactionMetadata(
        strategy=CompactionStrategy.FULL,
        original_message_count=len(all_messages),
        original_token_estimate=original_token_est,
        compacted_message_count=len(messages_to_compact),
        compacted_token_estimate=compacted_token_est,
        compacted_at=_now_iso(),
        compact_summary=summary[:500],
        rounds_compacted=list(range(len(groups_to_compact))) if retain_rounds < len(groups) else [],
        trigger_reason="auto_threshold",
    )
    return compacted, meta


def _compact_partial(
    all_messages: list[dict[str, Any]],
    groups: list[list[dict[str, Any]]],
    original_token_est: int,
    settings: Settings,
    counter: TokenCounter,
) -> tuple[list[dict[str, Any]], CompactionMetadata]:
    """Partial compaction: compress oldest group, keep recent ones."""
    from app.services.compact_prompts import build_partial_compact_prompt

    if len(groups) <= 1:
        return _compact_full(all_messages, groups, original_token_est, settings, counter)

    # Find split point: earliest groups whose cumulative tokens exceed threshold
    token_accum = 0
    split_idx = len(groups)

    for i, group in enumerate(groups):
        group_tokens = counter.estimate_messages(group)
        token_accum += group_tokens
        if token_accum >= _MAX_TOKENS_PER_GROUP and i < len(groups) - 1:
            split_idx = i + 1
            break

    older_messages = [msg for g in groups[:split_idx] for msg in g]
    recent_messages = [msg for g in groups[split_idx:] for msg in g]

    if not older_messages:
        meta = CompactionMetadata(
            strategy=CompactionStrategy.PARTIAL,
            original_message_count=len(all_messages),
            original_token_estimate=original_token_est,
            compacted_message_count=0,
            compacted_token_estimate=0,
            compacted_at=_now_iso(),
            compact_summary="",
            rounds_compacted=[],
            trigger_reason="no_older_messages",
        )
        return all_messages, meta

    older_text = _format_messages_for_compact(older_messages)
    recent_text = _format_messages_for_compact(recent_messages)
    prompt = build_partial_compact_prompt(older_text, recent_text)
    summary = _call_llm_for_compact(prompt, settings)

    summary_message = {
        "role": "system",
        "content": f"[早期对话压缩摘要]\n\n{summary}",
        "name": "compacted_older_history",
    }
    compacted = [summary_message, *recent_messages]

    compacted_token_est = counter.estimate_messages(compacted)
    meta = CompactionMetadata(
        strategy=CompactionStrategy.PARTIAL,
        original_message_count=len(all_messages),
        original_token_estimate=original_token_est,
        compacted_message_count=len(older_messages),
        compacted_token_estimate=compacted_token_est,
        compacted_at=_now_iso(),
        compact_summary=summary[:500],
        rounds_compacted=list(range(split_idx)),
        trigger_reason="auto_threshold",
    )
    return compacted, meta


def _compact_up_to(
    all_messages: list[dict[str, Any]],
    groups: list[list[dict[str, Any]]],
    original_token_est: int,
    pivot_message_id: str | None,
    settings: Settings,
    counter: TokenCounter,
) -> tuple[list[dict[str, Any]], CompactionMetadata]:
    """Up-to compaction: compress up to a pivot message."""
    from app.services.compact_prompts import build_up_to_compact_prompt

    if not pivot_message_id:
        return _compact_partial(all_messages, groups, original_token_est, settings, counter)

    # Find pivot message position
    pivot_idx = None
    for i, msg in enumerate(all_messages):
        if msg.get("message_id") == pivot_message_id or msg.get("id") == pivot_message_id:
            pivot_idx = i
            break

    if pivot_idx is None:
        logger.warning("pivot message %s not found, falling back to partial compact", pivot_message_id)
        return _compact_partial(all_messages, groups, original_token_est, settings, counter)

    older_messages = all_messages[:pivot_idx]
    recent_messages = all_messages[pivot_idx:]

    if not older_messages:
        meta = CompactionMetadata(
            strategy=CompactionStrategy.UP_TO,
            original_message_count=len(all_messages),
            original_token_estimate=original_token_est,
            compacted_message_count=0,
            compacted_token_estimate=0,
            compacted_at=_now_iso(),
            compact_summary="",
            rounds_compacted=[],
            trigger_reason="no_older_messages",
        )
        return all_messages, meta

    older_text = _format_messages_for_compact(older_messages)
    recent_text = _format_messages_for_compact(recent_messages)
    pivot_msg = all_messages[pivot_idx]
    pivot_summary = str(pivot_msg.get("content", ""))[:300]

    prompt = build_up_to_compact_prompt(older_text, pivot_summary, recent_text)
    summary = _call_llm_for_compact(prompt, settings)

    summary_message = {
        "role": "system",
        "content": f"[切换点之前对话压缩摘要]\n\n{summary}",
        "name": "compacted_pre_pivot_history",
    }
    compacted = [summary_message, *recent_messages]

    compacted_token_est = counter.estimate_messages(compacted)
    meta = CompactionMetadata(
        strategy=CompactionStrategy.UP_TO,
        original_message_count=len(all_messages),
        original_token_estimate=original_token_est,
        compacted_message_count=len(older_messages),
        compacted_token_estimate=compacted_token_est,
        compacted_at=_now_iso(),
        compact_summary=summary[:500],
        rounds_compacted=[],
        trigger_reason="manual_pivot",
    )
    return compacted, meta


def _call_llm_for_compact(prompt: str, settings: Settings) -> str:
    """Call LLM to generate compaction summary. Uses lightweight model if configured."""
    try:
        from openai import OpenAI
    except ImportError:
        logger.error("openai package not available for compaction")
        return ""

    api_key = settings.llm_api_key
    base_url = settings.llm_base_url
    model = settings.compact_model or settings.llm_model

    if not api_key:
        logger.warning("no LLM API key configured for compaction")
        return ""

    try:
        client = OpenAI(
            api_key=api_key,
            base_url=normalize_openai_base_url(base_url),
            timeout=float(settings.compact_timeout_seconds),
            max_retries=1,
        )
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=settings.compact_max_output_tokens,
        )
        content = response.choices[0].message.content if response.choices else ""
        return _extract_summary_from_response(content or "")
    except Exception as exc:
        logger.error("LLM compaction call failed: %s", exc)
        raise


def _now_iso() -> str:
    return now_iso()
