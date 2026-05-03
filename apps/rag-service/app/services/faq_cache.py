from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from threading import RLock
from time import monotonic

from app.core.config import get_settings
from app.core.metrics import (
    FAQ_CACHE_ENTRIES,
    SMART_CACHE_REQUESTS_TOTAL,
    SMART_CACHE_TOKEN_SAVED_TOTAL,
)

try:
    import redis
except ImportError:
    redis = None


@dataclass
class FaqEntry:
    question: str
    aliases: list[str]
    answer: str
    token_estimate: int = 0
    confidence: float = 1.0


@dataclass
class FaqMatchResult:
    entry: FaqEntry
    match_reason: str
    token_saved_estimate: int


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s\u4e00-\u9fff]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


class FaqCacheService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._lock = RLock()
        self._entries: dict[str, FaqEntry] = {}
        self._redis_client = self._build_redis_client()
        self._load_bootstrap()

    def match(self, query: str) -> FaqMatchResult | None:
        if not self.settings.faq_cache_enabled:
            SMART_CACHE_REQUESTS_TOTAL.labels(layer="L1_FAQ", result="disabled").inc()
            return None

        normalized = _normalize(query)
        entry = self._match_local(normalized)
        if entry is None:
            entry = self._match_redis(normalized)

        if entry is None:
            SMART_CACHE_REQUESTS_TOTAL.labels(layer="L1_FAQ", result="miss").inc()
            return None

        SMART_CACHE_REQUESTS_TOTAL.labels(layer="L1_FAQ", result="hit").inc()
        token_saved = entry.token_estimate or max(len(entry.answer) // 2, 50)
        SMART_CACHE_TOKEN_SAVED_TOTAL.inc(token_saved)
        return FaqMatchResult(
            entry=entry,
            match_reason="faq_exact_match",
            token_saved_estimate=token_saved,
        )

    def add_entry(self, entry: FaqEntry) -> None:
        with self._lock:
            key = _normalize(entry.question)
            self._entries[key] = entry
            self._sync_to_redis(key, entry)
            FAQ_CACHE_ENTRIES.set(len(self._entries))

    def remove_entry(self, question: str) -> bool:
        key = _normalize(question)
        with self._lock:
            removed = self._entries.pop(key, None)
            if removed:
                self._delete_from_redis(key)
                FAQ_CACHE_ENTRIES.set(len(self._entries))
                return True
            return False

    def list_entries(self) -> list[dict[str, object]]:
        with self._lock:
            return [
                {
                    "question": entry.question,
                    "aliases": entry.aliases,
                    "answer": entry.answer,
                    "token_estimate": entry.token_estimate,
                    "confidence": entry.confidence,
                }
                for entry in self._entries.values()
            ]

    def describe(self) -> dict[str, object]:
        return {
            "enabled": self.settings.faq_cache_enabled,
            "backend": "redis" if self._redis_client else "memory",
            "entries": len(self._entries),
            "namespace": self.settings.faq_cache_namespace,
            "ttl_seconds": self.settings.faq_cache_ttl_seconds,
        }

    def _match_local(self, normalized_query: str) -> FaqEntry | None:
        with self._lock:
            entry = self._entries.get(normalized_query)
            if entry is not None:
                return entry
            for key, entry in self._entries.items():
                if any(_normalize(alias) == normalized_query for alias in entry.aliases):
                    return entry
        return None

    def _match_redis(self, normalized_query: str) -> FaqEntry | None:
        if self._redis_client is None:
            return None
        try:
            payload = self._redis_client.get(f"{self.settings.faq_cache_namespace}:q:{normalized_query}")
            if payload:
                data = json.loads(payload)
                return FaqEntry(**data)
            for key in self._redis_client.scan_iter(match=f"{self.settings.faq_cache_namespace}:q:*"):
                raw = self._redis_client.get(key)
                if raw:
                    data = json.loads(raw)
                    entry = FaqEntry(**data)
                    if any(_normalize(alias) == normalized_query for alias in entry.aliases):
                        return entry
        except Exception:
            pass
        return None

    def _load_bootstrap(self) -> None:
        default_faqs = [
            FaqEntry(
                question="怎么开发票",
                aliases=["发票", "开票", "如何开发票", "开发票流程"],
                answer="您好！开发票流程如下：\n1. 登录账户，进入「订单管理」页面\n2. 找到需要开票的订单，点击「申请发票」\n3. 填写发票抬头（个人/企业）和税号\n4. 提交后，电子发票将在 1-3 个工作日内发送至您的邮箱\n\n如需增值税专用发票，请联系客服提供企业资质。",
                token_estimate=120,
            ),
            FaqEntry(
                question="如何退款",
                aliases=["退款", "退款流程", "怎么退款", "申请退款"],
                answer="您好！退款流程如下：\n1. 登录账户，进入「订单管理」\n2. 选择需要退款的订单，点击「申请退款」\n3. 选择退款原因并提交\n4. 审核通过后，款项将在 3-5 个工作日内退回原支付方式\n\n如超过 5 个工作日未到账，请联系客服。",
                token_estimate=100,
            ),
            FaqEntry(
                question="如何联系客服",
                aliases=["客服", "联系客服", "人工客服", "在线客服"],
                answer="您好！您可以通过以下方式联系我们：\n- 在线客服：点击页面右下角的「在线咨询」按钮\n- 客服热线：请联系平台获取\n- 邮箱：请联系平台获取\n\n我们会在 24 小时内回复您的咨询。",
                token_estimate=80,
            ),
        ]
        for entry in default_faqs:
            key = _normalize(entry.question)
            self._entries[key] = entry
            self._sync_to_redis(key, entry)
        FAQ_CACHE_ENTRIES.set(len(self._entries))

    def _build_redis_client(self):
        if not self.settings.redis_url or redis is None:
            return None
        try:
            return redis.from_url(
                self.settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
        except Exception:
            return None

    def _sync_to_redis(self, key: str, entry: FaqEntry) -> None:
        if self._redis_client is None:
            return
        try:
            payload = json.dumps(
                {
                    "question": entry.question,
                    "aliases": entry.aliases,
                    "answer": entry.answer,
                    "token_estimate": entry.token_estimate,
                    "confidence": entry.confidence,
                },
                ensure_ascii=False,
            )
            ttl = max(self.settings.faq_cache_ttl_seconds, 60)
            redis_key = f"{self.settings.faq_cache_namespace}:q:{key}"
            self._redis_client.setex(redis_key, ttl, payload)
            for alias in entry.aliases:
                alias_key = _normalize(alias)
                alias_redis_key = f"{self.settings.faq_cache_namespace}:q:{alias_key}"
                self._redis_client.setex(alias_redis_key, ttl, payload)
        except Exception:
            pass

    def _delete_from_redis(self, key: str) -> None:
        if self._redis_client is None:
            return
        try:
            self._redis_client.delete(f"{self.settings.faq_cache_namespace}:q:{key}")
        except Exception:
            pass


@lru_cache(maxsize=1)
def get_faq_cache() -> FaqCacheService:
    return FaqCacheService()
