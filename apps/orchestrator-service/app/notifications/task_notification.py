from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.mailbox.mailbox import AgentMailbox, AgentMessage


class TaskNotification(BaseModel):
    """Task completion notification (JSON format, inspired by Claude Code's
    <<task-notification>> XML format).

    Enqueued into the completed agent's mailbox + published via Redis PUBLISH
    so that SSE listeners (gateway -> web-admin) can push in real time.
    """

    task_id: str
    status: Literal["completed", "failed", "killed"]
    summary: str  # e.g. "Agent 'researchAuth' completed"
    result: str  # human-readable outcome
    usage: dict[str, Any] = Field(default_factory=dict)
    # usage fields: total_tokens, tool_uses, duration_ms
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def enqueue_notification(
    mailbox: AgentMailbox,
    recipient_agent_id: str,
    notification: TaskNotification,
    *,
    sender: str = "orchestrator",
) -> None:
    """Write a TaskNotification into the recipient's mailbox as an AgentMessage
    and publish a Redis PUBLISH event for real-time SSE push.
    """
    message = AgentMessage(
        sender=sender,
        recipient=recipient_agent_id,
        msg_type="task_notification",
        content=notification.result,
        summary=notification.summary,
        metadata={
            "task_id": notification.task_id,
            "status": notification.status,
            "usage": notification.usage,
        },
    )
    mailbox.write(recipient_agent_id, message)
    # Publish to Redis channel so SSE endpoint can pick it up
    try:
        from app.mailbox.store import RedisMailbox

        store = getattr(mailbox, "_store", None)
        if isinstance(store, RedisMailbox) and store.available:
            client = getattr(store, "_redis_client", None)
            if client is not None:
                import json

                channel = f"smartcloud:mailbox:pubsub:{recipient_agent_id}"
                payload = json.dumps(
                    notification.model_dump(mode="json"), ensure_ascii=False
                )
                client.publish(channel, payload)
    except Exception:
        pass