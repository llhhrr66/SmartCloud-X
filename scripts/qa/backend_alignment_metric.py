from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_STATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "logs"
    / "supervisor-backend-alignment"
    / "state.json"
)


def read_unresolved_count(state_path: Path) -> int:
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    summary = payload.get("summary", {})
    unresolved_count = summary.get("unresolved_count")
    if not isinstance(unresolved_count, int):
        raise ValueError(f"state file does not expose an integer unresolved_count: {state_path}")
    return unresolved_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Read backend-alignment unresolved metric")
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    args = parser.parse_args()
    print(read_unresolved_count(args.state_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
