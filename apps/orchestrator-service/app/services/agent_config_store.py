from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from app.models.orchestration import AgentConfigOverride, AgentName


class AgentConfigStore:
    """Process-local agent override store with optional file persistence."""

    def __init__(self, file_path: str | Path | None = None) -> None:
        self._lock = RLock()
        self._overrides: dict[str, AgentConfigOverride] = {}
        self._file_path: Path | None = None
        self.configure_persistence(file_path)

    def configure_persistence(self, file_path: str | Path | None) -> None:
        path = Path(file_path).expanduser() if file_path else None
        with self._lock:
            self._file_path = path
            self._overrides = self._load_overrides(path)

    def clear(self) -> None:
        with self._lock:
            self._overrides.clear()
            self._persist_unlocked()

    def list(self) -> list[AgentConfigOverride]:
        with self._lock:
            return [
                override.model_copy(deep=True)
                for _, override in sorted(self._overrides.items(), key=lambda item: item[0])
            ]

    def get(self, agent_name: AgentName) -> AgentConfigOverride | None:
        with self._lock:
            override = self._overrides.get(agent_name)
            return override.model_copy(deep=True) if override else None

    def upsert(
        self,
        *,
        agent_name: AgentName,
        agent_code: str,
        values: dict[str, Any],
    ) -> AgentConfigOverride:
        with self._lock:
            current = self._overrides.get(agent_name)
            payload = current.model_dump() if current is not None else {
                "agent_name": agent_name,
                "agent_code": agent_code,
            }
            payload.update(values)
            payload["agent_name"] = agent_name
            payload["agent_code"] = agent_code
            payload["updated_at"] = datetime.now(timezone.utc).isoformat()
            override = AgentConfigOverride.model_validate(payload)
            self._overrides[agent_name] = override
            self._persist_unlocked()
            return override.model_copy(deep=True)

    def _persist_unlocked(self) -> None:
        if self._file_path is None:
            return
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "overrides": {
                agent_name: override.model_dump(mode="json")
                for agent_name, override in self._overrides.items()
            }
        }
        tmp_path = self._file_path.with_suffix(f"{self._file_path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(self._file_path)

    @staticmethod
    def _load_overrides(path: Path | None) -> dict[str, AgentConfigOverride]:
        if path is None or not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {
            str(agent_name): AgentConfigOverride.model_validate(raw_override)
            for agent_name, raw_override in payload.get("overrides", {}).items()
        }
