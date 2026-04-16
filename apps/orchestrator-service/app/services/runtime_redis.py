from __future__ import annotations

try:
    import redis
except ImportError:  # pragma: no cover - exercised in integration environments
    redis = None


def normalize_namespace(value: str) -> str:
    return ":".join(part for part in value.strip().strip(":").split(":") if part) or "smartcloud:orchestrator"


def build_redis_client(redis_url: str | None):
    if not redis_url or redis is None:
        return None
    try:
        client = redis.from_url(  # type: ignore[union-attr]
            redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        ping = getattr(client, "ping", None)
        if callable(ping):
            ping()
        return client
    except Exception:
        return None
