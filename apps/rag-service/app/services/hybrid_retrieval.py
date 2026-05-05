from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


class BM25Scorer:
    """BM25 scorer for keyword-based candidate ranking.

    Uses the Okapi BM25 formula to score document chunks against query terms,
    providing a complementary signal to semantic/vector similarity scores.
    """

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        epsilon: float = 0.25,
    ) -> None:
        self.k1 = k1
        self.b = b
        self.epsilon = epsilon

    def fit(self, corpus: list[list[str]]) -> None:
        self._corpus_size = len(corpus)
        self._avg_doc_len = sum(len(doc) for doc in corpus) / max(self._corpus_size, 1)

        df: dict[str, int] = defaultdict(int)
        for doc in corpus:
            seen = set(doc)
            for term in seen:
                df[term] += 1

        self._idf: dict[str, float] = {}
        for term, freq in df.items():
            self._idf[term] = math.log(
                1 + (self._corpus_size - freq + 0.5) / (freq + 0.5)
            )

    def score(self, doc: list[str], query_terms: list[str]) -> float:
        doc_len = len(doc)
        total = 0.0
        tf: dict[str, int] = defaultdict(int)
        for t in doc:
            tf[t] += 1

        for term in query_terms:
            idf = self._idf.get(term, self.epsilon)
            term_freq = tf.get(term, 0)
            numerator = term_freq * (self.k1 + 1)
            denominator = term_freq + self.k1 * (
                1 - self.b + self.b * doc_len / max(self._avg_doc_len, 1)
            )
            total += idf * numerator / max(denominator, self.epsilon)
        return total


def reciprocal_rank_fusion(
    ranked_lists: list[list[tuple[str, float]]],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Combine multiple ranked lists using Reciprocal Rank Fusion (RRF).

    Each candidate's score = sum over lists of 1/(k + rank_in_list).
    """
    scores: dict[str, float] = defaultdict(float)
    for ranked in ranked_lists:
        for rank_idx, (candidate_id, _) in enumerate(ranked):
            scores[candidate_id] += 1.0 / (k + rank_idx + 1)

    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def weighted_score_fusion(
    semantic_scored: list[tuple[str, float]],
    bm25_scored: list[tuple[str, float]],
    semantic_weight: float = 0.6,
) -> list[tuple[str, float]]:
    """Combine semantic and BM25 scores using weighted sum.

    Requires min-max normalization of each list first, then:
    combined = w * norm_semantic + (1-w) * norm_bm25
    """
    def _min_max_normalize(
        scored: list[tuple[str, float]],
    ) -> dict[str, float]:
        if not scored:
            return {}
        values = [s for _, s in scored]
        v_min, v_max = min(values), max(values)
        if v_max == v_min:
            return {cid: 0.5 for cid, _ in scored}
        return {
            cid: (score - v_min) / (v_max - v_min)
            for cid, score in scored
        }

    norm_sem = _min_max_normalize(semantic_scored)
    norm_bm = _min_max_normalize(bm25_scored)

    all_ids = set(norm_sem.keys()) | set(norm_bm.keys())
    combined: dict[str, float] = {}
    for cid in all_ids:
        combined[cid] = (
            semantic_weight * norm_sem.get(cid, 0.0)
            + (1 - semantic_weight) * norm_bm.get(cid, 0.0)
        )

    return sorted(combined.items(), key=lambda x: x[1], reverse=True)


def tokenize_for_bm25(text: str) -> list[str]:
    """Tokenize text for BM25 indexing: lowercase, split on non-alphanumeric."""
    import re

    return [t.lower() for t in re.findall(r"[\w一-鿿]+", text)]


class HybridRetrievalConfig:
    """Configuration for hybrid retrieval strategy."""

    SEMANTIC_ONLY = "semantic_only"
    KEYWORD_ONLY = "keyword_only"
    RRF_FUSION = "rrf_fusion"
    WEIGHTED_FUSION = "weighted_fusion"


DEFAULT_HYBRID_CONFIG: dict[str, Any] = {
    "strategy": HybridRetrievalConfig.WEIGHTED_FUSION,
    "semantic_weight": 0.6,
    "bm25_k1": 1.5,
    "bm25_b": 0.75,
    "rrf_k": 60,
    "min_hybrid_score": 0.15,
}