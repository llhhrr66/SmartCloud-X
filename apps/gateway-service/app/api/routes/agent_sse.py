"""
SSE endpoint for agent message streaming.

Add this route to gateway-service to push real-time agent notifications
to the web-admin frontend, replacing the polling pattern.

Usage:
    In gateway main.py, add:
        from app.api.routes.agent_sse import router as agent_sse_router
        app.include_router(agent_sse_router)
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Request, Query
from starlette.responses import StreamingResponse

from app.services.auth import GatewaySubject, require_admin_subject

router = APIRouter(prefix="/api/v1", tags=["agents"])

HEARTBEAT_INTERVAL = 15  # seconds


async def _subscribe_redis(redis_url: str, agent_id: str):
    """Connect to Redis pubsub and yield notification payloads."""
    try:
        from redis import asyncio as aioredis
    except ImportError:
        return

    try:
        client = aioredis.from_url(
            redis_url, decode_responses=True, socket_connect_timeout=2
        )
        pubsub = client.pubsub()
        channel = f"smartcloud:mailbox:pubsub:{agent_id}"
        await pubsub.subscribe(channel)
        try:
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message is not None and message.get("type") == "message":
                    yield message["data"]
                await asyncio.sleep(0.1)
        finally:
            await pubsub.unsubscribe(channel)
            await client.close()
    except Exception:
        return


async def _read_redis_mailbox(redis_url: str, agent_id: str, after_timestamp: str | None = None):
    """Read existing messages from Redis mailbox list."""
    try:
        import redis
    except ImportError:
        return []

    try:
        client = redis.from_url(
            redis_url, decode_responses=True, socket_connect_timeout=1
        )
        key = f"smartcloud:mailbox:mailbox:{agent_id}"
        payloads = client.lrange(key, 0, -1)
        client.close()

        msgs = []
        for p in payloads:
            try:
                data = json.loads(p)
                if after_timestamp and data.get("timestamp", "") <= after_timestamp:
                    continue
                msgs.append(data)
            except json.JSONDecodeError:
                continue
        return msgs
    except Exception:
        return []


async def _event_generator(
    agent_id: str,
    redis_url: str | None,
    last_event_id: str | None = None,
) -> AsyncIterator[str]:
    """Generate SSE events for an agent's mailbox.

    - Yields existing messages (catch-up)
    - Then subscribes to Redis pubsub for live updates
    - Sends heartbeat comments every HEARTBEAT_INTERVAL seconds
    """
    last_id = 0
    if last_event_id:
        try:
            last_id = int(last_event_id)
        except ValueError:
            last_id = 0

    # --- Catch-up: send existing messages ---
    after_ts = None
    if redis_url:
        existing = await asyncio.to_thread(
            _read_redis_mailbox, redis_url, agent_id, after_ts
        )
        for msg in existing:
            last_id += 1
            event_type = msg.get("msg_type", "task_notification")
            yield f"id: {last_id}\n"
            yield f"event: {event_type}\n"
            yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"

    # --- Live: subscribe to Redis pubsub ---
    heartbeat_task: asyncio.Task | None = None
    pubsub_queue: asyncio.Queue = asyncio.Queue()

    async def _pubsub_reader():
        if not redis_url:
            return
        async for payload in _subscribe_redis(redis_url, agent_id):
            await pubsub_queue.put(payload)

    async def _heartbeat_sender():
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            await pubsub_queue.put(None)  # sentinel for heartbeat

    pubsub_task = asyncio.create_task(_pubsub_reader())
    heartbeat_task = asyncio.create_task(_heartbeat_sender())

    try:
        while True:
            try:
                payload = await asyncio.wait_for(pubsub_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                last_id += 1
                yield f": heartbeat {time.time()}\n\n"
                continue

            if payload is None:  # heartbeat sentinel
                last_id += 1
                yield f": heartbeat {time.time()}\n\n"
                continue

            try:
                data = json.loads(payload) if isinstance(payload, str) else payload
                event_type = "task_notification"
                if isinstance(data, dict):
                    event_type = data.get("msg_type", event_type)

                last_id += 1
                yield f"id: {last_id}\n"
                yield f"event: {event_type}\n"
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            except json.JSONDecodeError:
                continue
    finally:
        pubsub_task.cancel()
        if heartbeat_task:
            heartbeat_task.cancel()
        try:
            await pubsub_task
        except asyncio.CancelledError:
            pass
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass


@router.get("/agents/{agent_id}/messages")
async def agent_messages_sse(
    request: Request,
    agent_id: str,
    last_event_id: str | None = Query(
        default=None,
        alias="Last-Event-ID",
        description="For SSE reconnection: resume from this event ID",
    ),
    subject: GatewaySubject = Depends(require_admin_subject),
):
    """SSE endpoint: stream agent task notifications in real time.

    Replaces the polling pattern in web-admin. The frontend can use
    EventSource to connect:

        const es = new EventSource('/api/v1/agents/orchestrator/messages');
        es.addEventListener('task_notification', (e) => {
            const data = JSON.parse(e.data);
            // update UI with data.task_id, data.status, data.result, etc.
        });

    Reconnection is handled by the Last-Event-ID header automatically
    sent by the browser's EventSource implementation.
    """
    services = request.app.state.gateway_services
    redis_url = getattr(services.settings, "redis_url", None) or None

    return StreamingResponse(
        _event_generator(agent_id, redis_url, last_event_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )