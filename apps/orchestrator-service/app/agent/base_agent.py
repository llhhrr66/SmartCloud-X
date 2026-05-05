from __future__ import annotations

import asyncio
from typing import Any

from app.mailbox.mailbox import AgentMailbox, AgentMessage
from app.notifications.task_notification import TaskNotification, enqueue_notification


class BaseAgent:
    """Agent base class with built-in mailbox communication capability.

    Subclasses call self.notify_completion() so that the orchestrator
    and the gateway SSE endpoint know when a task finishes.
    """

    agent_id: str

    def __init__(
        self, agent_id: str, mailbox: AgentMailbox | None = None
    ) -> None:
        self.agent_id = agent_id
        self.mailbox = mailbox or AgentMailbox()

    async def send_message(
        self, to: str, content: str, summary: str | None = None
    ) -> AgentMessage:
        """Send a message to another agent via the mailbox."""
        msg = AgentMessage(
            sender=self.agent_id,
            recipient=to,
            msg_type="follow_up",
            content=content,
            summary=summary,
        )
        self.mailbox.write(to, msg)
        return msg

    async def receive_messages(self) -> list[AgentMessage]:
        """Read all messages addressed to this agent."""
        return self.mailbox.read(self.agent_id)

    async def notify_completion(
        self,
        task_id: str,
        result: str,
        usage: dict[str, Any] | None = None,
        *,
        status: str = "completed",
    ) -> None:
        """Notify that a task completed. Writes a TaskNotification into the
        orchestrator's mailbox for SSE relay.
        """
        notification = TaskNotification(
            task_id=task_id,
            status=status,  # type: ignore[arg-type]
            summary=f"Agent '{self.agent_id}' {status}",
            result=result,
            usage=usage or {},
        )
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            enqueue_notification,
            self.mailbox,
            "orchestrator",
            notification,
            self.agent_id,
        )