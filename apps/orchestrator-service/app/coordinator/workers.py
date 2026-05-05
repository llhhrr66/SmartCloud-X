
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field


@dataclass
class ToolDefinition:
    name: str
    description: str = ""
    capability: str = ""
    mode: str = "query"
    parameters: dict[str, Any] = field(default_factory=dict)


class WorkerUsage(BaseModel):
    total_tokens: int = 0
    tool_uses: int = 0
    duration_ms: int = 0


class WorkerResult(BaseModel):
    worker_id: str
    role: str
    status: str = "success"
    content: str = ""
    usage: WorkerUsage = Field(default_factory=WorkerUsage)


class WorkerAgent:
    """Sub-agent with restricted tool execution via LLMToolCallLoop.

    Inspired by Claude Code's subagent spawning pattern — each worker
    operates within a constrained tool and round-count boundary.
    """

    def __init__(
        self,
        role: str,
        tools: list[str] | None = None,
        worker_id: str | None = None,
        settings: Any = None,
        max_rounds: int = 3,
    ):
        self.worker_id = worker_id or f"worker_{uuid.uuid4().hex[:8]}"
        self.role = role
        self.tools = tools or []
        self._settings = settings
        self._max_rounds = min(max_rounds, 5)  # Hard cap at 5 rounds
        self._started_at: float = 0.0

    def _build_self_contained_prompt(self, purpose: str, spec: str = "") -> str:
        tool_descriptions = ", ".join(self.tools) if self.tools else "(no tools)"

        templates = {
            "research": (
                "This is a RESEARCH task.\n"
                f"Purpose: {purpose}\n\n"
                "You are a research worker. Your only job is to investigate and report.\n"
                "DO NOT modify any files. DO NOT write code.\n"
                "Report: file paths, line numbers, type signatures, and relevant details.\n"
                f"Available tools: {tool_descriptions}\n"
            ),
            "implementation": (
                "This is an IMPLEMENTATION task.\n"
                f"Purpose: {purpose}\n"
                f"Specification: {spec}\n\n"
                "You are an implementation worker. Make the specified changes.\n"
                "After completing changes, run related tests.\n"
                "Commit your changes and report what was done.\n"
                f"Available tools: {tool_descriptions}\n"
            ),
            "verification": (
                "This is a VERIFICATION task.\n"
                f"Purpose: {purpose}\n"
                f"Implementation context: {spec}\n\n"
                "You are a verification worker. Your job is to PROVE the code works, "
                "not just confirm it exists.\n"
                "Run tests, type checks, and try edge cases.\n"
                "Report every issue you find. Do not let anything suspicious pass.\n"
                f"Available tools: {tool_descriptions}\n"
            ),
        }
        return templates.get(self.role, templates["research"])

    async def run(self, prompt: str, context: dict[str, Any] | None = None) -> WorkerResult:
        self._started_at = time.perf_counter()
        context = context or {}

        try:
            # If settings and tools are configured, use the real LLM tool call loop
            if self._settings is not None and self.tools:
                result = self._run_with_llm_loop(prompt, context)
                duration_ms = int((time.perf_counter() - self._started_at) * 1000)
                return result

            # Fallback: prompt-only mode (legacy behavior)
            purpose = context.get("purpose", prompt)
            spec = context.get("spec", "")
            full_prompt = self._build_self_contained_prompt(purpose, spec)

            duration_ms = int((time.perf_counter() - self._started_at) * 1000)
            return WorkerResult(
                worker_id=self.worker_id,
                role=self.role,
                status="success",
                content=full_prompt,
                usage=WorkerUsage(
                    total_tokens=0,
                    tool_uses=0,
                    duration_ms=duration_ms,
                ),
            )
        except Exception as exc:
            duration_ms = int((time.perf_counter() - self._started_at) * 1000)
            return WorkerResult(
                worker_id=self.worker_id,
                role=self.role,
                status="failed",
                content=str(exc),
                usage=WorkerUsage(duration_ms=duration_ms),
            )

    def _run_with_llm_loop(self, prompt: str, context: dict[str, Any]) -> WorkerResult:
        """Execute the sub-agent task using LLMToolCallLoop with restricted tools."""
        from app.models.orchestration import (
            MessageRequest,
            SessionContext,
            UserProfile,
            ToolInvocation,
        )
        from app.models.common import TraceContext
        from app.services.agent_answer_generator import OpenAICompatibleAgentAnswerGenerator
        from app.services.llm_tool_call_loop import LLMToolCallLoop
        from app.services.tool_hub_client import ToolHubClient
        from app.core.config import Settings

        settings: Settings = self._settings
        agent_name = context.get("agent", "product_tech_agent")

        # Build a minimal request for the sub-agent
        request = MessageRequest(
            user_query=prompt,
            scene=context.get("scene", "customer_service"),
            user_profile=UserProfile(user_id=context.get("user_id")),
            session_context=SessionContext(
                confirmed_tool_names=self.tools,  # Sub-agent tools are pre-approved
            ),
        )

        trace = context.get("trace")  # Optional TraceContext

        # Set up the LLM loop with restricted tool scope
        answer_generator = OpenAICompatibleAgentAnswerGenerator(settings=settings)
        tool_hub_client = ToolHubClient()
        llm_loop = LLMToolCallLoop(
            answer_generator=answer_generator,
            tool_hub_client=tool_hub_client,
            settings=settings,
        )

        # Override max rounds for sub-agent safety
        original_max = settings.max_tool_call_rounds
        settings.max_tool_call_rounds = self._max_rounds
        try:
            tool_calls, llm_answer = llm_loop.run(
                agent=agent_name,
                user_query=prompt,
                request=request,
                working_context=request.session_context,
                trace=trace,
            )
        finally:
            settings.max_tool_call_rounds = original_max

        duration_ms = int((time.perf_counter() - self._started_at) * 1000)

        # Count token usage from the answer generator if available
        total_tokens = 0
        if hasattr(answer_generator, "_last_usage") and answer_generator._last_usage:
            usage = answer_generator._last_usage
            total_tokens = getattr(usage, "total_tokens", 0) or 0

        return WorkerResult(
            worker_id=self.worker_id,
            role=self.role,
            status="success" if tool_calls or llm_answer else "failed",
            content=llm_answer or "",
            usage=WorkerUsage(
                total_tokens=total_tokens,
                tool_uses=len(tool_calls),
                duration_ms=duration_ms,
            ),
        )
