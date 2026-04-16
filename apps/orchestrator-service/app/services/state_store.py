from __future__ import annotations

import json
from pathlib import Path
from threading import RLock

from app.models.orchestration import SessionStateSnapshot


class OrchestrationStateStore:
    """Checkpoint/state store for orchestrator sessions with optional file persistence."""

    def __init__(self, file_path: str | Path | None = None) -> None:
        self._lock = RLock()
        self._snapshots: dict[str, SessionStateSnapshot] = {}
        self._file_path: Path | None = None
        self.configure_persistence(file_path)

    def configure_persistence(self, file_path: str | Path | None) -> None:
        path = Path(file_path).expanduser() if file_path else None
        with self._lock:
            self._file_path = path
            self._snapshots = self._load_snapshots(path)

    def save(self, snapshot: SessionStateSnapshot) -> SessionStateSnapshot:
        with self._lock:
            current = self._snapshots.get(snapshot.conversation_id)
            version = 1 if current is None else current.version + 1
            persisted = snapshot.model_copy(deep=True, update={"version": version})
            self._snapshots[snapshot.conversation_id] = persisted
            self._persist_unlocked()
        return persisted.model_copy(deep=True)

    def get(self, conversation_id: str) -> SessionStateSnapshot | None:
        with self._lock:
            snapshot = self._snapshots.get(conversation_id)
            return snapshot.model_copy(deep=True) if snapshot else None

    def clear(self) -> None:
        with self._lock:
            self._snapshots.clear()
            self._persist_unlocked()

    def _persist_unlocked(self) -> None:
        if self._file_path is None:
            return
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "snapshots": {
                conversation_id: snapshot.model_dump(mode="json")
                for conversation_id, snapshot in self._snapshots.items()
            }
        }
        tmp_path = self._file_path.with_suffix(f"{self._file_path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(self._file_path)

    @staticmethod
    def _load_snapshots(path: Path | None) -> dict[str, SessionStateSnapshot]:
        if path is None or not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {
            str(conversation_id): SessionStateSnapshot.model_validate(raw_snapshot)
            for conversation_id, raw_snapshot in payload.get("snapshots", {}).items()
        }
