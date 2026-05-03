from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.models.orchestration import (
    MessageRequest,
    OrchestratorResponse,
    SessionContext,
)


class ConversationContextMerger:
    """Pure-utility class: all methods are static. No state."""

    @staticmethod
    def merge_session_context(
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
        merged.recent_messages = ConversationContextMerger._merge_recent_messages(
            merged.recent_messages,
            override.recent_messages,
            max_recent_messages=max_recent_messages,
        )
        merged.active_products = ConversationContextMerger._dedupe_strings(
            [*merged.active_products, *override.active_products]
        )
        if override.open_ticket_id:
            merged.open_ticket_id = override.open_ticket_id
        merged.attributes = ConversationContextMerger._merge_attributes(
            merged.attributes, override.attributes
        )
        if persist_confirmed_tool_names:
            merged.confirmed_tool_names = ConversationContextMerger._dedupe_strings(
                [*merged.confirmed_tool_names, *override.confirmed_tool_names]
            )
        else:
            merged.confirmed_tool_names = []
        return merged

    @staticmethod
    def derive_next_session_context(
        base_context: SessionContext | None,
        message_request: MessageRequest,
        response: OrchestratorResponse,
        *,
        max_recent_messages: int,
    ) -> SessionContext:
        merged = ConversationContextMerger.merge_session_context(
            base_context,
            message_request.session_context,
            persist_confirmed_tool_names=False,
            max_recent_messages=max_recent_messages,
        )
        assistant_summary = response.final_response_summary or response.route.summary
        merged.history_summary = ConversationContextMerger._merge_history_summary(
            merged.history_summary,
            message_request.user_query,
            assistant_summary,
        )
        merged.recent_messages = ConversationContextMerger._merge_recent_messages(
            merged.recent_messages,
            [
                {"role": "user", "content": ConversationContextMerger._compact_text(message_request.user_query)},
                {
                    "role": "assistant",
                    "content": ConversationContextMerger._compact_text(assistant_summary),
                    "agent": response.route.primary_agent,
                    "status": response.next_action,
                },
            ],
            max_recent_messages=max_recent_messages,
        )
        for execution in response.executions:
            for tool_call in execution.tool_calls:
                if tool_call.success:
                    ConversationContextMerger._apply_session_context_patch(
                        merged, tool_call.session_context_patch
                    )
        merged.confirmed_tool_names = ConversationContextMerger._dedupe_strings(
            [*merged.confirmed_tool_names, *message_request.session_context.confirmed_tool_names]
        )
        return merged

    @staticmethod
    def _apply_session_context_patch(context: SessionContext, patch: dict[str, object]) -> None:
        if not patch:
            return
        history_summary = patch.get("history_summary")
        if isinstance(history_summary, str) and history_summary.strip():
            context.history_summary = history_summary.strip()
        context.recent_messages = ConversationContextMerger._merge_recent_messages(
            context.recent_messages,
            patch.get("recent_messages") if isinstance(patch.get("recent_messages"), list) else [],
            max_recent_messages=20,
        )
        context.active_products = ConversationContextMerger._dedupe_strings(
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
            context.attributes = ConversationContextMerger._merge_attributes(
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
                f"用户：{ConversationContextMerger._compact_text(user_query, limit=72)}",
                f"助手：{ConversationContextMerger._compact_text(assistant_summary, limit=96)}",
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
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()
