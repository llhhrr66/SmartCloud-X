from __future__ import annotations

import logging
import re
from typing import Any

from app.core.config import Settings, get_settings
from app.models.compact import SessionMemoryConfig, SessionMemoryRecord
from app.services.token_counter import TokenCounter
from app.services._compact_utils import normalize_openai_base_url

logger = logging.getLogger(__name__)


class SessionMemoryExtractor:
    """Background session memory extractor inspired by Claude Code SessionMemory.

    Threshold controls:
    - First extraction: estimated tokens >= min_tokens_to_init
    - Incremental update: token delta >= tokens_between_updates
      or tool call delta >= tool_calls_between_updates
    """

    def __init__(
        self,
        settings: Settings | None = None,
        token_counter: TokenCounter | None = None,
        config: SessionMemoryConfig | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._counter = token_counter or TokenCounter()
        if config is not None:
            self._config = config
        else:
            # Build config from Settings so env overrides are respected
            self._config = SessionMemoryConfig(
                min_tokens_to_init=self._settings.session_memory_min_tokens_to_init,
                tokens_between_updates=self._settings.session_memory_tokens_between_updates,
                max_tokens_per_section=self._settings.session_memory_max_tokens_per_section,
                max_total_tokens=12000,  # default; no Settings field yet
            )

    def should_extract(
        self,
        existing_memory: SessionMemoryRecord | None,
        messages: list[dict[str, Any]],
    ) -> bool:
        """Determine if memory extraction should be triggered."""
        total_tokens = self._counter.estimate_messages(messages)

        if existing_memory is None:
            # First extraction
            return total_tokens >= self._config.min_tokens_to_init

        # Incremental update: compare token delta
        delta_tokens = total_tokens - existing_memory.total_tokens_estimate
        if delta_tokens >= self._config.tokens_between_updates:
            return True

        # Also check tool call count delta
        tool_call_count = sum(
            1 for msg in messages if msg.get("role") == "tool"
        )
        # Count tool calls recorded in the existing memory version
        existing_tool_calls = existing_memory.sections.get("_tool_call_count")
        if existing_tool_calls is not None:
            try:
                prev_count = int(existing_tool_calls)
            except (ValueError, TypeError):
                prev_count = 0
        else:
            prev_count = 0
        delta_tool_calls = tool_call_count - prev_count
        return delta_tool_calls >= self._config.tool_calls_between_updates

    def extract_memory(
        self,
        conversation_id: str,
        messages: list[dict[str, Any]],
        existing_memory: SessionMemoryRecord | None = None,
    ) -> SessionMemoryRecord | None:
        """Extract session memory. First time or incremental update."""
        from app.services.session_memory_prompts import (
            SESSION_MEMORY_INIT_PROMPT,
            SESSION_MEMORY_UPDATE_PROMPT,
            MEMORY_SECTIONS_TEMPLATE,
            MEMORY_SECTIONS,
        )

        messages_text = self._format_messages(messages)
        section_count = len(MEMORY_SECTIONS)

        fmt_kwargs = {
            "sections_template": MEMORY_SECTIONS_TEMPLATE,
            "section_count": section_count,
            "max_tokens_per_section": self._config.max_tokens_per_section,
            "max_total_tokens": self._config.max_total_tokens,
        }

        if existing_memory is None:
            prompt = SESSION_MEMORY_INIT_PROMPT.format(
                **fmt_kwargs,
                messages_text=messages_text,
            )
        else:
            existing_text = self._format_sections(existing_memory.sections)
            prompt = SESSION_MEMORY_UPDATE_PROMPT.format(
                **fmt_kwargs,
                existing_memory=existing_text,
                new_messages_text=messages_text,
            )

        result_text = self._call_llm(prompt)
        if not result_text:
            return None

        sections = self._parse_sections(result_text)
        total_tokens = self._counter.estimate_messages(messages)
        now = self._now_iso()

        return SessionMemoryRecord(
            conversation_id=conversation_id,
            sections=sections,
            total_tokens_estimate=total_tokens,
            version=(existing_memory.version + 1) if existing_memory else 1,
            extracted_at=existing_memory.extracted_at if existing_memory else now,
            updated_at=now,
        )

    def _format_messages(self, messages: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = str(msg.get("content", ""))[:3000]
            lines.append(f"[{role}] {content}")
            # Include tool call info for assistant messages
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

    def _format_sections(self, sections: dict[str, str]) -> str:
        return "\n\n".join(f"### {k}\n{v}" for k, v in sections.items())

    def _parse_sections(self, text: str) -> dict[str, str]:
        """Parse sections from LLM output, validating against known section titles."""
        sections: dict[str, str] = {}
        # Match ### Title pattern
        pattern = r"###\s*(.+?)\s*\n(.*?)(?=###|$)"
        # Build lookup of known section titles (lowered) for validation
        from app.services.session_memory_prompts import MEMORY_SECTIONS
        known_titles = {title.lower(): title for title, _ in MEMORY_SECTIONS}

        for match in re.finditer(pattern, text, re.DOTALL):
            title = match.group(1).strip()
            content = match.group(2).strip()
            if not content:
                continue
            # Truncate overly long sections
            max_chars = self._config.max_tokens_per_section * 2
            if len(content) > max_chars:
                content = content[:max_chars]
            # Use canonical title if it matches a known one
            canonical = known_titles.get(title.lower(), title)
            sections[canonical] = content
        return sections

    def _call_llm(self, prompt: str) -> str:
        """Call LLM to generate memory."""
        try:
            from openai import OpenAI
        except ImportError:
            logger.error("openai package not available for session memory extraction")
            return ""

        api_key = self._settings.llm_api_key
        base_url = self._settings.llm_base_url
        model = self._settings.compact_model or self._settings.llm_model

        if not api_key:
            return ""

        try:
            client = OpenAI(
                api_key=api_key,
                base_url=normalize_openai_base_url(base_url),
                timeout=float(self._settings.compact_timeout_seconds),
                max_retries=1,
            )
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=self._settings.compact_max_output_tokens * 2,  # memory can be longer
            )
            return response.choices[0].message.content or "" if response.choices else ""
        except Exception as exc:
            logger.error("session memory LLM call failed: %s", exc)
            return ""

    @staticmethod
    def _now_iso() -> str:
        from app.services._compact_utils import now_iso
        return now_iso()
