from __future__ import annotations

import json
from pathlib import Path
from threading import RLock

from app.models.orchestration import StreamEventPage, StreamEventRecord


class SseEventStore:
    """Process-local SSE event store with optional file persistence."""

    def __init__(self, file_path: str | Path | None = None) -> None:
        self._lock = RLock()
        self._events: dict[tuple[str, str], list[StreamEventRecord]] = {}
        self._file_path: Path | None = None
        self.configure_persistence(file_path)

    def configure_persistence(self, file_path: str | Path | None) -> None:
        path = Path(file_path).expanduser() if file_path else None
        with self._lock:
            self._file_path = path
            self._events = self._load_events(path)

    def save(
        self,
        conversation_id: str,
        message_id: str,
        events: list[StreamEventRecord],
    ) -> list[StreamEventRecord]:
        stored_events = [event.model_copy(deep=True) for event in events]
        with self._lock:
            self._events[(conversation_id, message_id)] = stored_events
            self._persist_unlocked()
        return [event.model_copy(deep=True) for event in stored_events]

    def get_page(
        self,
        conversation_id: str,
        message_id: str,
        *,
        after_event_id: str | None = None,
        limit: int = 100,
    ) -> StreamEventPage | None:
        with self._lock:
            stored = self._events.get((conversation_id, message_id))
            if stored is None:
                return None
            events = [event.model_copy(deep=True) for event in stored]
        start_index = self._start_index(events, after_event_id)
        page_items = events[start_index : start_index + limit]
        has_more = start_index + limit < len(events)
        next_event_id = page_items[-1].event_id if has_more and page_items else None
        return StreamEventPage(
            conversation_id=conversation_id,
            message_id=message_id,
            items=page_items,
            next_event_id=next_event_id,
            has_more=has_more,
        )

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._persist_unlocked()

    @staticmethod
    def _start_index(events: list[StreamEventRecord], after_event_id: str | None) -> int:
        if not after_event_id:
            return 0
        for index, event in enumerate(events):
            if event.event_id == after_event_id:
                return index + 1
        return 0

    def _persist_unlocked(self) -> None:
        if self._file_path is None:
            return
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "streams": {
                f"{conversation_id}::{message_id}": [event.model_dump(mode="json") for event in events]
                for (conversation_id, message_id), events in self._events.items()
            }
        }
        tmp_path = self._file_path.with_suffix(f"{self._file_path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(self._file_path)

    @staticmethod
    def _load_events(path: Path | None) -> dict[tuple[str, str], list[StreamEventRecord]]:
        if path is None or not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        events: dict[tuple[str, str], list[StreamEventRecord]] = {}
        for composite_key, raw_events in payload.get("streams", {}).items():
            conversation_id, _, message_id = str(composite_key).partition("::")
            if not conversation_id or not message_id or not isinstance(raw_events, list):
                continue
            events[(conversation_id, message_id)] = [
                StreamEventRecord.model_validate(raw_event)
                for raw_event in raw_events
                if isinstance(raw_event, dict)
            ]
        return events
