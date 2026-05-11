from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from threading import RLock
from time import monotonic

from app.core.config import get_settings
from app.core.metrics import (
    FAQ_BM25_HITS_TOTAL,
    FAQ_CACHE_ENTRIES,
    FAQ_TFIDF_HITS_TOTAL,
    SMART_CACHE_REQUESTS_TOTAL,
    SMART_CACHE_TOKEN_SAVED_TOTAL,
)

try:
    import redis
except ImportError:
    redis = None


@dataclass
class FaqDocumentRef:
    doc_id: str
    title: str
    url: str | None = None

    def to_dict(self) -> dict:
        result = {"docId": self.doc_id, "title": self.title}
        if self.url:
            result["url"] = self.url
        return result


@dataclass
class FaqEntry:
    question: str
    aliases: list[str]
    answer: str
    token_estimate: int = 0
    confidence: float = 1.0
    category: str = "general"  # general | operations | billing | product | compliance
    document_refs: list[FaqDocumentRef] | None = None  # knowledge-service doc references
    prerequisites: list[str] | None = None  # prerequisite conditions
    related_topics: list[str] | None = None  # related FAQ question keys


@dataclass
class FaqMatchResult:
    entry: FaqEntry
    match_reason: str
    token_saved_estimate: int


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s\u4e00-\u9fff]", "", text)
    text = re.sub(r"\s+", "", text)
    return text


def _jieba_tokenize(text: str) -> list[str]:
    """Segment Chinese text with jieba, filtering single-char tokens."""
    import jieba

    tokens = jieba.lcut(text)
    return [t.strip() for t in tokens if len(t.strip()) > 1]


def _build_entry_text(entry: FaqEntry) -> str:
    """Combine question + aliases into a single text for indexing."""
    parts = [entry.question] + entry.aliases
    return " ".join(parts)


class FaqCacheService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._lock = RLock()
        self._entries: dict[str, FaqEntry] = {}
        self._redis_client = self._build_redis_client()
        self._load_bootstrap()
        # BM25 state
        self._bm25_scorer: object | None = None  # BM25Scorer instance
        self._bm25_corpus: list[list[str]] = []
        self._bm25_entries: list[FaqEntry] = []
        # TF-IDF state
        self._tfidf_vectorizer: object | None = None
        self._tfidf_matrix: object | None = None
        self._tfidf_entries: list[FaqEntry] = []
        # Build initial indices
        self._rebuild_indices()

    def match(self, query: str) -> FaqMatchResult | None:
        if not self.settings.faq_cache_enabled:
            SMART_CACHE_REQUESTS_TOTAL.labels(layer="L1_FAQ", result="disabled").inc()
            return None

        normalized = _normalize(query)

        # Layer 1: Exact normalized match
        entry = self._match_local(normalized)
        if entry is None:
            entry = self._match_redis(normalized)
        if entry is not None:
            SMART_CACHE_REQUESTS_TOTAL.labels(layer="L1_FAQ", result="hit").inc()
            token_saved = entry.token_estimate or max(len(entry.answer) // 2, 50)
            SMART_CACHE_TOKEN_SAVED_TOTAL.inc(token_saved)
            return FaqMatchResult(
                entry=entry,
                match_reason="faq_exact_match",
                token_saved_estimate=token_saved,
            )

        # Layer 2: BM25 keyword match
        entry, score = self._match_bm25(query)
        if entry is not None:
            SMART_CACHE_REQUESTS_TOTAL.labels(layer="L1_FAQ", result="hit").inc()
            FAQ_BM25_HITS_TOTAL.inc()
            token_saved = entry.token_estimate or max(len(entry.answer) // 2, 50)
            SMART_CACHE_TOKEN_SAVED_TOTAL.inc(token_saved)
            return FaqMatchResult(
                entry=entry,
                match_reason=f"faq_bm25_match(score={score:.2f})",
                token_saved_estimate=token_saved,
            )

        # Layer 3: TF-IDF cosine similarity match
        entry, sim = self._match_tfidf(query)
        if entry is not None:
            SMART_CACHE_REQUESTS_TOTAL.labels(layer="L1_FAQ", result="hit").inc()
            FAQ_TFIDF_HITS_TOTAL.inc()
            token_saved = entry.token_estimate or max(len(entry.answer) // 2, 50)
            SMART_CACHE_TOKEN_SAVED_TOTAL.inc(token_saved)
            return FaqMatchResult(
                entry=entry,
                match_reason=f"faq_tfidf_match(sim={sim:.3f})",
                token_saved_estimate=token_saved,
            )

        SMART_CACHE_REQUESTS_TOTAL.labels(layer="L1_FAQ", result="miss").inc()
        return None

    def add_entry(self, entry: FaqEntry) -> None:
        with self._lock:
            key = _normalize(entry.question)
            self._entries[key] = entry
            self._sync_to_redis(key, entry)
            FAQ_CACHE_ENTRIES.set(len(self._entries))
            self._rebuild_indices()

    def upsert_entry(self, entry: FaqEntry) -> None:
        """Add an entry and let it replace older aliases that point at the same topic."""
        with self._lock:
            keys = {_normalize(entry.question)}
            keys.update(_normalize(alias) for alias in entry.aliases)
            for key in keys:
                self._entries[key] = entry
                self._sync_to_redis(key, entry)
            FAQ_CACHE_ENTRIES.set(len(self._entries))
            self._rebuild_indices()

    def remove_entry(self, question: str) -> bool:
        key = _normalize(question)
        with self._lock:
            removed = self._entries.pop(key, None)
            if removed:
                self._delete_from_redis(key)
                FAQ_CACHE_ENTRIES.set(len(self._entries))
                self._rebuild_indices()
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
                    "category": entry.category,
                    "document_refs": [r.to_dict() for r in (entry.document_refs or [])],
                    "prerequisites": entry.prerequisites or [],
                    "related_topics": entry.related_topics or [],
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
            "bm25_enabled": self.settings.faq_bm25_enabled,
            "bm25_threshold": self.settings.faq_bm25_threshold,
            "tfidf_enabled": self.settings.faq_tfidf_enabled,
            "tfidf_threshold": self.settings.faq_tfidf_threshold,
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
                return self._parse_faq_entry(data)
            for key in self._redis_client.scan_iter(match=f"{self.settings.faq_cache_namespace}:q:*"):
                raw = self._redis_client.get(key)
                if raw:
                    data = json.loads(raw)
                    entry = self._parse_faq_entry(data)
                    if any(_normalize(alias) == normalized_query for alias in entry.aliases):
                        return entry
        except Exception:
            pass
        return None

    def _match_bm25(self, query: str) -> tuple[FaqEntry | None, float]:
        """Layer 2: BM25 keyword match using jieba tokenization."""
        if not self.settings.faq_bm25_enabled or self._bm25_scorer is None:
            return None, 0.0
        query_terms = _jieba_tokenize(query)
        if not query_terms:
            return None, 0.0
        best_score = 0.0
        best_entry = None
        for i, doc_terms in enumerate(self._bm25_corpus):
            s = self._bm25_scorer.score(doc_terms, query_terms)
            if s > best_score:
                best_score = s
                best_entry = self._bm25_entries[i]
        if best_score >= self.settings.faq_bm25_threshold and best_entry is not None:
            return best_entry, best_score
        return None, best_score

    def _match_tfidf(self, query: str) -> tuple[FaqEntry | None, float]:
        """Layer 3: TF-IDF cosine similarity match."""
        if not self.settings.faq_tfidf_enabled or self._tfidf_vectorizer is None:
            return None, 0.0
        import numpy as np

        query_vec = self._tfidf_vectorizer.transform([query])
        sims = (self._tfidf_matrix @ query_vec.T).toarray().ravel()
        best_idx = int(np.argmax(sims))
        best_sim = float(sims[best_idx])
        if best_sim >= self.settings.faq_tfidf_threshold:
            return self._tfidf_entries[best_idx], best_sim
        return None, best_sim

    def _rebuild_indices(self) -> None:
        """Rebuild BM25 corpus and TF-IDF matrix from current entries."""
        # Deduplicate entries (multiple keys can point to same FaqEntry)
        seen_ids: set[int] = set()
        unique_entries: list[FaqEntry] = []
        for entry in self._entries.values():
            eid = id(entry)
            if eid not in seen_ids:
                seen_ids.add(eid)
                unique_entries.append(entry)

        if not unique_entries:
            self._bm25_scorer = None
            self._bm25_corpus = []
            self._bm25_entries = []
            self._tfidf_vectorizer = None
            self._tfidf_matrix = None
            self._tfidf_entries = []
            return

        # Build texts for indexing
        texts = [_build_entry_text(e) for e in unique_entries]

        # BM25: tokenize and fit
        from app.services.hybrid_retrieval import BM25Scorer

        corpus = [_jieba_tokenize(t) for t in texts]
        scorer = BM25Scorer()
        scorer.fit(corpus)
        self._bm25_scorer = scorer
        self._bm25_corpus = corpus
        self._bm25_entries = list(unique_entries)

        # TF-IDF: vectorize and fit
        from sklearn.feature_extraction.text import TfidfVectorizer

        vectorizer = TfidfVectorizer(tokenizer=_jieba_tokenize, token_pattern=None)
        matrix = vectorizer.fit_transform(texts)
        self._tfidf_vectorizer = vectorizer
        self._tfidf_matrix = matrix
        self._tfidf_entries = list(unique_entries)

    @staticmethod
    def _parse_faq_entry(data: dict) -> FaqEntry:
        doc_refs = None
        raw_refs = data.get("document_refs")
        if raw_refs:
            doc_refs = [FaqDocumentRef(doc_id=r["docId"], title=r["title"], url=r.get("url")) for r in raw_refs if "docId" in r and "title" in r]
        return FaqEntry(
            question=data.get("question", ""),
            aliases=data.get("aliases", []),
            answer=data.get("answer", ""),
            token_estimate=data.get("token_estimate", 0),
            confidence=data.get("confidence", 1.0),
            category=data.get("category", "general"),
            document_refs=doc_refs,
            prerequisites=data.get("prerequisites"),
            related_topics=data.get("related_topics"),
        )

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
                    "category": entry.category,
                    "document_refs": [r.to_dict() for r in (entry.document_refs or [])],
                    "prerequisites": entry.prerequisites or [],
                    "related_topics": entry.related_topics or [],
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
