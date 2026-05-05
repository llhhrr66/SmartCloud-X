from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field


class AgentMessage(BaseModel):
    """Structured message for inter-agent communication via Mailbox."""

    msg_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    sender: str
    recipient: str  # agent_id | "*" for broadcast
    msg_type: Literal[
        "task_notification",
        "shutdown_request",
        "shutdown_response",
        "plan_approval",
        "follow_up",
    ]
    content: str
    summary: str | None = None  # 5-10 char preview for UI
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = Field(default_factory=dict)


class Subscription:
    """Active subscription to an agent's mailbox."""

    def __init__(self, agent_id: str, callback: Callable[["AgentMessage"], None]) -> None:
        self.agent_id = agent_id
        self._callback = callback
        self._active = True

    def invoke(self, message: AgentMessage) -> None:
        if self._active:
            self._callback(message)

    def cancel(self) -> None:
        self._active = False

    @property
    def active(self) -> bool:
        return self._active


class AgentMailbox:
    """Inter-agent mailbox with subscribe/notify semantics.

    write(recipient, message)  -> persist + notify subscribers
    read(agent_id)             -> return all messages
    subscribe(agent_id, cb)    -> register live callback
    broadcast(message)         -> send to all known agents
    """

    def __init__(self, store: Any = None) -> None:
        self._subscriptions: dict[str, list[Subscription]] = {}
        self._store = store

    def set_store(self, store: Any) -> None:
        self._store = store

    def write(self, recipient: str, message: AgentMessage) -> None:
        """Persist message to store and notify live subscribers."""
        if self._store is not None:
            self._store.write(recipient, message)
        self._notify_subscribers(recipient, message)

    def read(self, agent_id: str) -> list[AgentMessage]:
        """Read all messages for an agent from the store."""
        if self._store is not None:
            return self._store.read(agent_id)
        return []

    def subscribe(
        self, agent_id: str, callback: Callable[[AgentMessage], None]
    ) -> Subscription:
        """Register a live callback. Returns a Subscription handle."""
        sub = Subscription(agent_id, callback)
        if agent_id not in self._subscriptions:
            self._subscriptions[agent_id] = []
        self._subscriptions[agent_id].append(sub)
        return sub

    def broadcast(self, message: AgentMessage) -> list[str]:
        """Send message to all agents. Returns list of recipient IDs."""
        message.recipient = "*"
        recipients: set[str] = set()
        if self._store is not None:
            rids = self._store.broadcast(message)
            recipients.update(rids)
            for rid in rids:
                self._notify_subscribers(rid, message)
        else:
            for agent_id in list(self._subscriptions.keys()):
                recipients.add(agent_id)
                self._notify_subscribers(agent_id, message)
        return sorted(recipients)

    def unsubscribe(self, agent_id: str, subscription: Subscription) -> None:
        """Remove a subscription."""
        subs = self._subscriptions.get(agent_id, [])
        if subscription in subs:
            subs.remove(subscription)
            subscription.cancel()

    def message_count(self, agent_id: str) -> int:
        """Return the number of messages for an agent."""
        if self._store is not None:
            return self._store.count(agent_id)
        return 0

    def _notify_subscribers(self, agent_id: str, message: AgentMessage) -> None:
        subs = self._subscriptions.get(agent_id, [])
        for sub in subs:
            try:
                sub.invoke(message)
            except Exception:
                pass