from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable


async def tee_sse_stream(
    stream: AsyncIterator[bytes],
    on_event: Callable[[str, dict], Awaitable[None] | None],
) -> AsyncIterator[bytes]:
    buffer = b""
    async for chunk in stream:
        buffer += chunk
        while b"\n\n" in buffer:
            raw_event, buffer = buffer.split(b"\n\n", 1)
            await _dispatch(raw_event, on_event)
            yield raw_event + b"\n\n"
    if buffer:
        await _dispatch(buffer, on_event)
        yield buffer


async def _dispatch(
    raw_event: bytes,
    on_event: Callable[[str, dict], Awaitable[None] | None],
) -> None:
    text = raw_event.decode("utf-8", errors="ignore")
    event_name = "message"
    data_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("event:"):
            event_name = line.partition(":")[2].strip()
        elif line.startswith("data:"):
            data_lines.append(line.partition(":")[2].strip())
    if not data_lines:
        return
    try:
        payload = json.loads("\n".join(data_lines))
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {"value": payload}
    result = on_event(event_name, payload)
    if result is not None:
        await result
