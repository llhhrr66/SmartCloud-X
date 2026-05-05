from __future__ import annotations

import json
import time
import uuid
from typing import Any

import pytest

from app.mailbox.mailbox import AgentMailbox, AgentMessage, Subscription
from app.mailbox.store import MemoryMailbox, RedisMailbox, build_mailbox_store
from app.notifications.task_notification import TaskNotification, enqueue_notification


# ---------------------------------------------------------------------------
# AgentMessage model
# ---------------------------------------------------------------------------

class TestAgentMessage:
    def test_defaults(self):
        msg = AgentMessage(sender="a1", recipient="a2", msg_type="follow_up", content="hello")
        assert len(msg.msg_id) == 32
        assert msg.sender == "a1"
        assert msg.recipient == "a2"
        assert msg.msg_type == "follow_up"
        assert msg.content == "hello"
        assert msg.summary is None
        assert isinstance(msg.timestamp, str)
        assert msg.metadata == {}

    def test_full_construction(self):
        msg = AgentMessage(
            msg_id="custom-id",
            sender="agent-A",
            recipient="*",
            msg_type="task_notification",
            content="Task done",
            summary="Done",
            timestamp="2025-01-01T00:00:00Z",
            metadata={"task_id": "t1", "status": "completed"},
        )
        assert msg.msg_id == "custom-id"
        assert msg.summary == "Done"
        assert msg.metadata["task_id"] == "t1"

    def test_serialization_roundtrip(self):
        msg = AgentMessage(
            sender="x", recipient="y", msg_type="plan_approval", content="approved"
        )
        data = msg.model_dump(mode="json")
        reloaded = AgentMessage.model_validate(data)
        assert reloaded.msg_id == msg.msg_id
        assert reloaded.sender == msg.sender
        assert reloaded.content == msg.content


# ---------------------------------------------------------------------------
# AgentMailbox with MemoryMailbox
# ---------------------------------------------------------------------------

class TestAgentMailboxMemory:
    @pytest.fixture
    def mailbox(self):
        store = MemoryMailbox()
        mb = AgentMailbox(store=store)
        return mb

    def test_write_and_read(self, mailbox):
        msg = AgentMessage(sender="a1", recipient="a2", msg_type="follow_up", content="ping")
        mailbox.write("a2", msg)
        msgs = mailbox.read("a2")
        assert len(msgs) == 1
        assert msgs[0].content == "ping"

    def test_read_empty(self, mailbox):
        msgs = mailbox.read("nonexistent")
        assert msgs == []

    def test_broadcast(self, mailbox):
        msg1 = AgentMessage(sender="a1", recipient="a2", msg_type="follow_up", content="pre-seed a2")
        msg2 = AgentMessage(sender="a1", recipient="a3", msg_type="follow_up", content="pre-seed a3")
        mailbox.write("a2", msg1)
        mailbox.write("a3", msg2)

        broadcast_msg = AgentMessage(
            sender="admin",
            recipient="*",
            msg_type="shutdown_request",
            content="shutdown now",
        )
        recipients = mailbox.broadcast(broadcast_msg)
        assert set(recipients) == {"a2", "a3"}
        assert len(mailbox.read("a2")) == 2
        assert len(mailbox.read("a3")) == 2

    def test_broadcast_no_subscribers(self, mailbox):
        broadcast_msg = AgentMessage(
            sender="admin", recipient="*", msg_type="shutdown_request", content="nobody"
        )
        recipients = mailbox.broadcast(broadcast_msg)
        assert recipients == []

    def test_subscribe_callback(self, mailbox):
        received: list[AgentMessage] = []

        def callback(msg: AgentMessage):
            received.append(msg)

        sub = mailbox.subscribe("a1", callback)
        msg = AgentMessage(sender="x", recipient="a1", msg_type="follow_up", content="hello")
        mailbox.write("a1", msg)
        assert len(received) == 1
        assert received[0].content == "hello"
        assert sub.active

        sub.cancel()
        assert not sub.active

        mailbox.write("a1", AgentMessage(sender="y", recipient="a1", msg_type="follow_up", content="world"))
        assert len(received) == 1  # not called after cancel

    def test_unsubscribe(self, mailbox):
        received: list[AgentMessage] = []

        def callback(msg: AgentMessage):
            received.append(msg)

        sub = mailbox.subscribe("a1", callback)
        mailbox.unsubscribe("a1", sub)
        mailbox.write("a1", AgentMessage(sender="x", recipient="a1", msg_type="follow_up", content="x"))
        assert received == []

    def test_multiple_subscribers(self, mailbox):
        r1: list[AgentMessage] = []
        r2: list[AgentMessage] = []

        mailbox.subscribe("a1", lambda m: r1.append(m))
        mailbox.subscribe("a1", lambda m: r2.append(m))

        mailbox.write("a1", AgentMessage(sender="x", recipient="a1", msg_type="follow_up", content="multi"))
        assert len(r1) == 1
        assert len(r2) == 1

    def test_subscriber_exception_does_not_break_others(self, mailbox):
        r: list[AgentMessage] = []

        def bad(_):
            raise RuntimeError("boom")

        mailbox.subscribe("a1", bad)
        mailbox.subscribe("a1", lambda m: r.append(m))
        mailbox.write("a1", AgentMessage(sender="x", recipient="a1", msg_type="follow_up", content="ok"))
        assert len(r) == 1

    def test_message_count(self, mailbox):
        assert mailbox.message_count("a1") == 0
        mailbox.write("a1", AgentMessage(sender="x", recipient="a1", msg_type="follow_up", content="1"))
        mailbox.write("a1", AgentMessage(sender="x", recipient="a1", msg_type="follow_up", content="2"))
        assert mailbox.message_count("a1") == 2


# ---------------------------------------------------------------------------
# AgentMailbox without store (pure in-memory subscriptions)
# ---------------------------------------------------------------------------

class TestAgentMailboxNoStore:
    @pytest.fixture
    def mailbox(self):
        return AgentMailbox()

    def test_read_returns_empty(self, mailbox):
        assert mailbox.read("a1") == []

    def test_write_notifies_subscribers(self, mailbox):
        received: list[AgentMessage] = []
        mailbox.subscribe("a1", lambda m: received.append(m))
        mailbox.write("a1", AgentMessage(sender="x", recipient="a1", msg_type="follow_up", content="test"))
        assert len(received) == 1

    def test_broadcast_no_store(self, mailbox):
        r1: list[AgentMessage] = []
        r2: list[AgentMessage] = []
        mailbox.subscribe("a1", lambda m: r1.append(m))
        mailbox.subscribe("a2", lambda m: r2.append(m))
        msg = AgentMessage(sender="admin", recipient="*", msg_type="shutdown_request", content="all")
        recipients = mailbox.broadcast(msg)
        assert set(recipients) == {"a1", "a2"}
        assert len(r1) == 1
        assert len(r2) == 1


# ---------------------------------------------------------------------------
# MemoryMailbox direct tests
# ---------------------------------------------------------------------------

class TestMemoryMailboxDirect:
    @pytest.fixture
    def store(self):
        return MemoryMailbox()

    def test_clear(self, store):
        store.write("a1", AgentMessage(sender="x", recipient="a1", msg_type="follow_up", content="x"))
        store.clear()
        assert store.count("a1") == 0

    def test_broadcast_empty(self, store):
        assert store.broadcast(AgentMessage(sender="x", recipient="*", msg_type="follow_up", content="x")) == []


# ---------------------------------------------------------------------------
# RedisMailbox tests (skip if no Redis)
# ---------------------------------------------------------------------------

class TestRedisMailbox:
    @pytest.fixture
    def redis_store(self):
        """Try to connect to Redis; skip tests if unavailable."""
        import os

        redis_url = os.environ.get("SMARTCLOUD_REDIS_URL", "redis://localhost:6379/0")
        store = RedisMailbox(redis_url, redis_namespace="smartcloud:mailbox:test")
        if not store.available:
            pytest.skip("Redis not available")
        store.clear()
        yield store
        store.clear()

    def test_write_and_read(self, redis_store):
        msg = AgentMessage(sender="a1", recipient="a2", msg_type="follow_up", content="redis-ping")
        redis_store.write("a2", msg)
        msgs = redis_store.read("a2")
        assert len(msgs) == 1
        assert msgs[0].content == "redis-ping"
        assert msgs[0].sender == "a1"

    def test_read_empty(self, redis_store):
        assert redis_store.read("ghost") == []

    def test_count(self, redis_store):
        redis_store.write("a1", AgentMessage(sender="x", recipient="a1", msg_type="follow_up", content="1"))
        redis_store.write("a1", AgentMessage(sender="x", recipient="a1", msg_type="follow_up", content="2"))
        assert redis_store.count("a1") == 2

    def test_broadcast(self, redis_store):
        redis_store.write("a2", AgentMessage(sender="x", recipient="a2", msg_type="follow_up", content="seed"))
        redis_store.write("a3", AgentMessage(sender="x", recipient="a3", msg_type="follow_up", content="seed"))
        bmsg = AgentMessage(sender="admin", recipient="*", msg_type="shutdown_request", content="bye")
        recipients = redis_store.broadcast(bmsg)
        assert "a2" in recipients
        assert "a3" in recipients
        assert len(redis_store.read("a2")) >= 2
        assert len(redis_store.read("a3")) >= 2

    def test_agent_mailbox_with_redis(self, redis_store):
        mb = AgentMailbox(store=redis_store)
        msg = AgentMessage(sender="x", recipient="a1", msg_type="follow_up", content="via-mailbox")
        mb.write("a1", msg)
        msgs = mb.read("a1")
        assert len(msgs) == 1
        assert msgs[0].content == "via-mailbox"

    def test_subscriber_with_redis_persist(self, redis_store):
        received: list[AgentMessage] = []
        mb = AgentMailbox(store=redis_store)
        mb.subscribe("a1", lambda m: received.append(m))
        msg = AgentMessage(sender="x", recipient="a1", msg_type="follow_up", content="live+persist")
        mb.write("a1", msg)
        assert len(received) == 1
        # Also persisted
        assert mb.message_count("a1") == 1


# ---------------------------------------------------------------------------
# build_mailbox_store factory
# ---------------------------------------------------------------------------

class TestBuildMailboxStore:
    def test_returns_memory_when_no_redis(self):
        store = build_mailbox_store(redis_url=None)
        assert isinstance(store, MemoryMailbox)

    def test_returns_memory_when_bad_url(self):
        store = build_mailbox_store(redis_url="redis://nonexistent:9999/0")
        assert isinstance(store, MemoryMailbox)


# ---------------------------------------------------------------------------
# TaskNotification
# ---------------------------------------------------------------------------

class TestTaskNotification:
    def test_defaults(self):
        notif = TaskNotification(
            task_id="task-1",
            status="completed",
            summary="Agent done",
            result="All good",
        )
        assert notif.task_id == "task-1"
        assert notif.status == "completed"
        assert notif.usage == {}
        assert isinstance(notif.timestamp, str)

    def test_enqueue_notification_writes_to_mailbox(self):
        store = MemoryMailbox()
        mb = AgentMailbox(store=store)
        notif = TaskNotification(
            task_id="agent-xyz",
            status="completed",
            summary="Agent 'deep_research_agent' completed",
            result="Report generated: 15 pages",
            usage={"total_tokens": 1500, "tool_uses": 3, "duration_ms": 8000},
        )
        enqueue_notification(mb, "orchestrator", notif, sender="deep_research_agent")
        msgs = mb.read("orchestrator")
        assert len(msgs) == 1
        assert msgs[0].msg_type == "task_notification"
        assert msgs[0].summary == "Agent 'deep_research_agent' completed"
        assert msgs[0].metadata["task_id"] == "agent-xyz"
        assert msgs[0].metadata["status"] == "completed"
        assert msgs[0].metadata["usage"]["total_tokens"] == 1500


# ---------------------------------------------------------------------------
# SSE format verification
# ---------------------------------------------------------------------------

class TestSSEFormat:
    def test_message_serializes_to_sse_friendly_json(self):
        msg = AgentMessage(
            sender="agent-1",
            recipient="orchestrator",
            msg_type="task_notification",
            content="Task completed successfully",
            summary="completed",
            metadata={
                "task_id": "task-001",
                "status": "completed",
                "usage": {"total_tokens": 500, "tool_uses": 2, "duration_ms": 3000},
            },
        )
        payload = json.dumps(msg.model_dump(mode="json"), ensure_ascii=False)
        assert "\n" not in payload  # SSE data must be single-line
        parsed = json.loads(payload)
        assert parsed["msg_type"] == "task_notification"
        assert parsed["metadata"]["task_id"] == "task-001"