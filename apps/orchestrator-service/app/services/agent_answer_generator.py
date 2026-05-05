from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Protocol

from app.core.config import Settings, get_settings
from app.models.orchestration import ToolInvocation
from app.services._compact_utils import normalize_openai_base_url


logger = logging.getLogger(__name__)


class AgentAnswerGenerator(Protocol):
    def generate(
        self,
        *,
        agent: str,
        user_query: str,
        status: str,
        next_agent: str | None,
        fallback_answer: str | None,
        tool_calls: list[ToolInvocation],
        compacted_history: str | None = None,
    ) -> str | None: ...

    def create_with_tools(
        self,
        *,
        agent: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        compacted_history: str | None = None,
    ) -> Any: ...


class OpenAICompatibleAgentAnswerGenerator:
    def __init__(self, settings: Settings | None = None, prompt_root: Path | None = None) -> None:
        self._settings = settings or get_settings()
        self._prompt_root = prompt_root or Path(__file__).resolve().parents[1] / "prompts"
        self._client = None
        self._client_ready = False

    def generate(
        self,
        *,
        agent: str,
        user_query: str,
        status: str,
        next_agent: str | None,
        fallback_answer: str | None,
        tool_calls: list[ToolInvocation],
        compacted_history: str | None = None,
    ) -> str | None:
        client = self._ensure_client()
        if client is None:
            return None

        fallback = fallback_answer or "请基于工具结果给出简洁、准确的中文答复。"

        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": self._system_prompt_for(agent),
            },
        ]

        # Inject compacted history as a system-level context message
        if compacted_history and compacted_history.strip():
            messages.append({
                "role": "system",
                "content": f"[对话历史压缩摘要]\n\n{compacted_history.strip()}",
                "name": "compacted_history",
            })

        messages.append({
            "role": "user",
            "content": self._build_user_content(
                user_query=user_query,
                status=status,
                next_agent=next_agent,
                fallback=fallback,
                tool_calls=tool_calls,
            ),
        })

        try:
            completion = client.chat.completions.create(
                model=getattr(self, "_model", None) or self._settings.llm_model,
                messages=messages,
            )
        except Exception as exc:  # noqa: BLE001 - runtime fallback handles provider errors
            logger.warning("agent answer generator failed, falling back to template answer: %s", exc)
            return None

        choice = completion.choices[0] if completion.choices else None
        message = choice.message if choice is not None else None
        content = getattr(message, "content", None)
        normalized = self._normalize_generated_content(content)
        if normalized:
            logger.info(
                "agent answer generator produced response for %s using model %s",
                agent,
                self._settings.llm_model,
            )
            return normalized
        return None

    def invalidate_cache(self) -> None:
        self._client = None
        self._client_ready = False
        self._model = None

    def create_with_tools(
        self,
        *,
        agent: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        compacted_history: str | None = None,
    ) -> Any:
        """Call LLM with ``tools=`` bound for function calling.

        Returns the raw ``ChatCompletion`` object so the caller can inspect
        ``choices[0].message.tool_calls`` or ``choices[0].message.content``.
        """
        client = self._ensure_client()
        if client is None:
            return None

        system_prompt = self._system_prompt_for(agent)
        full_messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        # Inject compacted history as a system-level context message
        if compacted_history and compacted_history.strip():
            full_messages.append({
                "role": "system",
                "content": f"[对话历史压缩摘要]\n\n{compacted_history.strip()}",
                "name": "compacted_history",
            })

        full_messages.extend(messages)

        try:
            completion = client.chat.completions.create(
                model=getattr(self, "_model", None) or self._settings.llm_model,
                messages=full_messages,
                tools=tools,
            )
        except Exception as exc:
            logger.warning("create_with_tools failed: %s", exc)
            return None

        return completion

    def _ensure_client(self):
        if self._client_ready:
            return self._client

        self._client_ready = True

        # Check database active provider first
        api_key = None
        base_url = None
        model = None
        try:
            from app.services import llm_provider_store
            active = llm_provider_store.get_active_provider()
            if active:
                api_key = str(active["api_key"])
                base_url = str(active["api_url"])
                model = str(active["model_name"])
        except Exception:
            pass  # Fall back to env settings

        # Fall back to env settings if no active provider in DB
        if not api_key:
            api_key = self._settings.llm_api_key
        if not base_url:
            base_url = self._settings.llm_base_url
        if not model:
            model = self._settings.llm_model

        if not api_key or not model:
            return None

        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover - exercised in runtime env only
            logger.warning("openai package unavailable for agent answer generator: %s", exc)
            return None

        kwargs: dict[str, object] = {
            "api_key": api_key,
            "timeout": float(self._settings.llm_timeout_seconds),
            "max_retries": 1,
        }
        normalized_base_url = normalize_openai_base_url(base_url)
        if normalized_base_url:
            kwargs["base_url"] = normalized_base_url

        self._client = OpenAI(**kwargs)
        self._model = model
        return self._client

    def _system_prompt_for(self, agent: str) -> str:
        agent_dir = {
            "product_tech_agent": "product_tech",
            "finance_order_agent": "finance_order",
            "icp_service_agent": "icp_service",
            "ops_marketing_agent": "ops_marketing",
            "deep_research_agent": "deep_research",
        }.get(agent, agent.removesuffix("_agent"))
        prompt_path = self._prompt_root / "agents" / agent_dir / "system.v1.0.md"
        if prompt_path.exists():
            content = prompt_path.read_text(encoding="utf-8").strip()
            if content:
                return content
        return self._fallback_system_prompt(agent)

    @staticmethod
    def _fallback_system_prompt(agent: str) -> str:
        return (
            f"你是 SmartCloud-X 的 {agent}。"
            "请用简洁、专业、自然的中文回答。"
            "只能基于给定的用户问题、保底事实答案和工具结果，不得编造。"
            "如果当前状态是 handoff，请明确说明将交接给下一个 agent。"
            "如果当前状态是 need_user_input，请明确说明还缺哪些信息或确认。"
            "不要暴露内部推理过程，不要输出 markdown 标题或列表。"
        )

    @staticmethod
    def _normalize_generated_content(content: Any) -> str | None:
        if not isinstance(content, str):
            return None
        text = content.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(parsed, dict):
            for key in ("final_answer", "answer", "finalAnswer"):
                value = parsed.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return text

    @staticmethod
    def _serialize_tool_calls(tool_calls: list[ToolInvocation]) -> str:
        items: list[dict[str, object]] = []
        for tool_call in tool_calls:
            items.append(
                {
                    "tool_name": tool_call.tool_name,
                    "status": tool_call.status,
                    "summary": tool_call.summary,
                    "payload": tool_call.payload,
                    "citations": tool_call.citations,
                }
            )
        return json.dumps(items, ensure_ascii=False)[:6000]

    def _build_user_content(
        self,
        *,
        user_query: str,
        status: str,
        next_agent: str | None,
        fallback: str,
        tool_calls: list[ToolInvocation],
    ) -> str:
        parts = [f"用户问题：{user_query}"]
        if tool_calls:
            parts.append(f"工具调用结果：{self._serialize_tool_calls(tool_calls)}")
        parts.append(f"处理状态：{status}")
        if next_agent:
            parts.append(f"下一个处理 agent：{next_agent}")
        parts.append(f"保底答案（如工具结果不足可参考）：{fallback}")
        parts.append(
            "请以顾问角色直接回答用户，不要提及内部工具、检索过程、置信度分数或系统细节。"
        )
        return "\n\n".join(parts)
