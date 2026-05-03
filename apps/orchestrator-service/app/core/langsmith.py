from __future__ import annotations

import os
from contextlib import nullcontext

from langsmith.run_helpers import tracing_context

from app.core.config import Settings


def configure_langsmith_env(settings: Settings) -> None:
    os.environ["LANGSMITH_TRACING"] = "true" if settings.langsmith_tracing else "false"
    os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    if settings.langsmith_api_key:
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key


def langsmith_enabled(settings: Settings) -> bool:
    return settings.langsmith_tracing and bool(settings.langsmith_api_key)


def orchestrator_tracing_context(
    settings: Settings,
    *,
    conversation_id: str,
    message_id: str,
    scene: str | None,
    request_id: str | None,
    trace_id: str | None,
):
    if not langsmith_enabled(settings):
        return nullcontext()
    return tracing_context(
        project_name=settings.langsmith_project,
        enabled=True,
        tags=["smartcloud-x", "orchestrator", scene or "unknown-scene"],
        metadata={
            "conversation_id": conversation_id,
            "message_id": message_id,
            "scene": scene,
            "request_id": request_id,
            "trace_id": trace_id,
        },
    )
