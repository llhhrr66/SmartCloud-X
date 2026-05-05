from __future__ import annotations

"""Shared utility functions for compaction and session memory modules.

Avoids code duplication across compact.py and session_memory.py.
"""

from urllib.parse import urlparse


def normalize_openai_base_url(url: str | None) -> str | None:
    """Normalize an OpenAI-compatible base URL.

    Strips trailing slashes and appends ``/v1`` if the path is empty.
    """
    if not url:
        return None
    url = url.strip().rstrip("/")
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.path in {"", "/"}:
        return f"{url}/v1"
    return url


def now_iso() -> str:
    """Return the current UTC time in ISO 8601 format."""
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
