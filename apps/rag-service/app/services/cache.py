from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from threading import RLock
from time import monotonic

from app.core.config import get_settings
from app.core.metrics import (
    CACHE_BACKEND_ERRORS_TOTAL,
    CACHE_ENTRY_COUNT,
    CACHE_HITS_TOTAL,
    CACHE_MISSES_TOTAL,
)
from app.models.rag import KnowledgeSearchCandidate, QueryRewriteResult, RetrieveRequest

try:
    import redis
except ImportError:  # pragma: no cover - exercised in integration environments
    redis = None


@dataclass
class CachedSearchResult:
    rewrite: QueryRewriteResult
    candidates: list[KnowledgeSearchCandidate]
    expires_at: float


class RetrievalCacheService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._lock = RLock()
        self._entries: dict[str, CachedSearchResult] = {}
        self._redis_client = self._build_redis_client()

    def get(
        self,
        request: RetrieveRequest,
    ) -> tuple[QueryRewriteResult, list[KnowledgeSearchCandidate]] | None:
        if not self.settings.cache_enabled:
            CACHE_MISSES_TOTAL.inc()
            return None

        key = self._build_key(request)
        cached = self._get_from_redis(key)
        if cached is not None:
            CACHE_HITS_TOTAL.inc()
            return cached

        now = monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                CACHE_MISSES_TOTAL.inc()
                return None
            if entry.expires_at <= now:
                self._entries.pop(key, None)
                self._update_size_metric()
                CACHE_MISSES_TOTAL.inc()
                return None
            CACHE_HITS_TOTAL.inc()
            return (
                entry.rewrite.model_copy(deep=True),
                [candidate.model_copy(deep=True) for candidate in entry.candidates],
            )

    def set(
        self,
        request: RetrieveRequest,
        rewrite: QueryRewriteResult,
        candidates: list[KnowledgeSearchCandidate],
    ) -> None:
        if not self.settings.cache_enabled:
            return

        key = self._build_key(request)
        expires_at = monotonic() + max(self.settings.cache_ttl_seconds, 1)
        self._set_in_redis(key, rewrite, candidates)
        with self._lock:
            self._entries[key] = CachedSearchResult(
                rewrite=rewrite.model_copy(deep=True),
                candidates=[candidate.model_copy(deep=True) for candidate in candidates],
                expires_at=expires_at,
            )
            self._prune_locked(monotonic())
            self._update_size_metric()

    def clear(self) -> None:
        self._clear_redis()
        with self._lock:
            self._entries.clear()
            self._update_size_metric()

    def describe(self) -> dict[str, object]:
        self._prune()
        return {
            "enabled": self.settings.cache_enabled,
            "backend": "redis-ttl" if self._redis_client is not None else "memory-ttl",
            "namespace": self.settings.cache_namespace,
            "ttlSeconds": self.settings.cache_ttl_seconds,
            "entries": len(self._entries),
            "redisConfigured": bool(self.settings.redis_url),
            "redisConnected": self._redis_client is not None,
        }

    def _build_key(self, request: RetrieveRequest) -> str:
        payload = json.dumps(
            {
                "namespace": self.settings.cache_namespace,
                "query": request.query,
                "topK": request.top_k,
                "sourceIds": sorted(request.filters.source_ids),
                "tags": sorted(tag.lower() for tag in request.filters.tags),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return f"{self.settings.cache_namespace}:{payload}"

    def _prune(self) -> None:
        with self._lock:
            self._prune_locked(monotonic())
            self._update_size_metric()

    def _prune_locked(self, now: float) -> None:
        expired = [key for key, value in self._entries.items() if value.expires_at <= now]
        for key in expired:
            self._entries.pop(key, None)

    def _update_size_metric(self) -> None:
        CACHE_ENTRY_COUNT.set(len(self._entries))

    def _build_redis_client(self):
        if not self.settings.redis_url or redis is None:
            return None
        try:
            return redis.from_url(  # type: ignore[union-attr]
                self.settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
        except Exception:
            CACHE_BACKEND_ERRORS_TOTAL.labels(operation="connect").inc()
            return None

    def _get_from_redis(
        self,
        key: str,
    ) -> tuple[QueryRewriteResult, list[KnowledgeSearchCandidate]] | None:
        if self._redis_client is None:
            return None
        try:
            payload = self._redis_client.get(key)
        except Exception:
            CACHE_BACKEND_ERRORS_TOTAL.labels(operation="get").inc()
            return None
        if not isinstance(payload, str) or not payload.strip():
            return None
        try:
            parsed = json.loads(payload)
            rewrite = QueryRewriteResult.model_validate(parsed.get("rewrite") or {})
            candidates = [
                KnowledgeSearchCandidate.model_validate(candidate)
                for candidate in parsed.get("candidates") or []
            ]
        except Exception:
            CACHE_BACKEND_ERRORS_TOTAL.labels(operation="decode").inc()
            try:
                self._redis_client.delete(key)
            except Exception:
                CACHE_BACKEND_ERRORS_TOTAL.labels(operation="delete").inc()
            return None
        return rewrite, candidates

    def _set_in_redis(
        self,
        key: str,
        rewrite: QueryRewriteResult,
        candidates: list[KnowledgeSearchCandidate],
    ) -> None:
        if self._redis_client is None:
            return
        payload = json.dumps(
            {
                "rewrite": rewrite.model_dump(mode="json", by_alias=True),
                "candidates": [
                    candidate.model_dump(mode="json", by_alias=True) for candidate in candidates
                ],
            },
            ensure_ascii=False,
        )
        try:
            self._redis_client.setex(key, max(self.settings.cache_ttl_seconds, 1), payload)
        except Exception:
            CACHE_BACKEND_ERRORS_TOTAL.labels(operation="set").inc()

    def _clear_redis(self) -> None:
        if self._redis_client is None:
            return
        try:
            for key in self._redis_client.scan_iter(match=f"{self.settings.cache_namespace}:*"):
                self._redis_client.delete(key)
        except Exception:
            CACHE_BACKEND_ERRORS_TOTAL.labels(operation="clear").inc()


@lru_cache(maxsize=1)
def get_retrieval_cache() -> RetrievalCacheService:
    return RetrievalCacheService()
