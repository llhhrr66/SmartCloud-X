from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    limit: int
    window_seconds: int
    retry_after_seconds: int
    key: str
    bucket_name: str


class SimpleRateLimiter:
    def __init__(
        self,
        *,
        request_limit: int,
        window_seconds: int,
        stream_request_limit: int | None = None,
        key_prefix: str = "gateway",
    ) -> None:
        self.request_limit = request_limit
        self.window_seconds = window_seconds
        self.stream_request_limit = max(1, stream_request_limit or max(1, request_limit // 3))
        self.key_prefix = key_prefix
        self._lock = Lock()
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def allow(self, key: str, *, limit: int | None = None, bucket_name: str = "default") -> tuple[bool, int]:
        decision = self.allow_detailed(key, limit=limit, bucket_name=bucket_name)
        return decision.allowed, decision.remaining

    def allow_detailed(
        self,
        key: str,
        *,
        limit: int | None = None,
        bucket_name: str = "default",
    ) -> RateLimitDecision:
        now = time.time()
        effective_limit = max(1, limit or self.request_limit)
        bucket_key = f"{self.key_prefix}:{bucket_name}:{key}"
        with self._lock:
            bucket = [
                timestamp
                for timestamp in self._buckets[bucket_key]
                if now - timestamp < self.window_seconds
            ]
            if len(bucket) >= effective_limit:
                self._buckets[bucket_key] = bucket
                oldest = bucket[0] if bucket else now
                retry_after = max(1, int(self.window_seconds - (now - oldest) + 0.999))
                return RateLimitDecision(
                    allowed=False,
                    remaining=0,
                    limit=effective_limit,
                    window_seconds=self.window_seconds,
                    retry_after_seconds=retry_after,
                    key=key,
                    bucket_name=bucket_name,
                )
            bucket.append(now)
            remaining = max(0, effective_limit - len(bucket))
            self._buckets[bucket_key] = bucket
            return RateLimitDecision(
                allowed=True,
                remaining=remaining,
                limit=effective_limit,
                window_seconds=self.window_seconds,
                retry_after_seconds=0,
                key=key,
                bucket_name=bucket_name,
            )
