import hashlib
import math
import re
from collections import Counter
from functools import lru_cache
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings
from app.core.metrics import SEARCH_REQUESTS_TOTAL
from app.core.tracing import start_span
from app.models.knowledge import (
    CountBucket,
    KnowledgeChunk,
    SearchAppliedFilters,
    SearchRequest,
    SearchResponse,
    SearchResult,
    SearchSourceBreakdown,
)
from app.services.store import KnowledgeStoreRepository
from app.services.store_provider import get_repository

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_+-]+|[\u4e00-\u9fff]{2,}")


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def _tokenize(value: str) -> list[str]:
    tokens: list[str] = []
    for item in re.findall(r"[A-Za-z0-9_+-]+|[\u4e00-\u9fff]+", _normalize_text(value)):
        if re.fullmatch(r"[\u4e00-\u9fff]+", item):
            if len(item) <= 4:
                tokens.append(item)
            else:
                tokens.extend(item[index : index + 2] for index in range(len(item) - 1))
        else:
            tokens.append(item)
    return list(dict.fromkeys(tokens))


def _tokenize_embedding_text(value: str) -> list[str]:
    return TOKEN_PATTERN.findall(value.lower())


def _build_embedding(text: str, dimensions: int) -> list[float]:
    vector = [0.0] * max(dimensions, 4)
    tokens = _tokenize_embedding_text(text)
    if not tokens:
        return vector

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        for index in range(len(vector)):
            bucket = digest[index % len(digest)]
            vector[index] += (bucket / 255.0) - 0.5

    magnitude = math.sqrt(sum(component * component for component in vector))
    if magnitude <= 0:
        return vector
    return [round(component / magnitude, 6) for component in vector]


class SearchService:
    def __init__(self, repository: KnowledgeStoreRepository) -> None:
        self.repository = repository
        self.settings = get_settings()

    def search(self, request: SearchRequest) -> SearchResponse:
        with start_span(
            "knowledge.search",
            smartcloud_search_query=request.query,
            smartcloud_search_top_k=request.top_k,
            smartcloud_search_source_filter_count=len(request.source_ids),
            smartcloud_search_tag_filter_count=len(request.tags),
        ) as span:
            SEARCH_REQUESTS_TOTAL.inc()
            query_tokens = _tokenize(request.query)
            query_text = _normalize_text(request.query)
            scored, backend_used, remote_error_count = self._search_candidates(
                request,
                query_tokens,
                query_text,
            )
            results = scored[: request.top_k]

            source_summary: dict[str, dict[str, str | int | float]] = {}
            tag_counts = Counter()
            for item in scored:
                summary = source_summary.setdefault(
                    item.chunk.source_id,
                    {
                        "sourceName": item.source_name,
                        "resultCount": 0,
                        "bestScore": 0.0,
                    },
                )
                summary["resultCount"] = int(summary["resultCount"]) + 1
                summary["bestScore"] = max(float(summary["bestScore"]), item.score)
                tag_counts.update(tag.lower() for tag in item.chunk.tags)

            source_breakdown = [
                SearchSourceBreakdown(
                    sourceId=source_id,
                    sourceName=str(summary["sourceName"]),
                    resultCount=int(summary["resultCount"]),
                    bestScore=round(float(summary["bestScore"]), 4),
                )
                for source_id, summary in sorted(
                    source_summary.items(),
                    key=lambda item: (
                        -int(item[1]["resultCount"]),
                        -float(item[1]["bestScore"]),
                        str(item[1]["sourceName"]),
                    ),
                )[:6]
            ]
            tag_breakdown = [
                CountBucket(label=label, count=count)
                for label, count in sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))[:8]
            ]

            if span is not None:
                span.set_attribute("smartcloud.search.total_hits", len(scored))
                span.set_attribute("smartcloud.search.result_count", len(results))
                span.set_attribute("smartcloud.search.query_token_count", len(query_tokens))
                span.set_attribute("smartcloud.search.backend", backend_used)
                span.set_attribute("smartcloud.search.remote_error_count", remote_error_count)

            return SearchResponse(
                query=request.query,
                total=len(scored),
                queryTokens=query_tokens,
                appliedFilters=SearchAppliedFilters(sourceIds=request.source_ids, tags=request.tags),
                sourceBreakdown=source_breakdown,
                tagBreakdown=tag_breakdown,
                results=results,
            )

    def _search_candidates(
        self,
        request: SearchRequest,
        query_tokens: list[str],
        query_text: str,
    ) -> tuple[list[SearchResult], str, int]:
        local_candidates = self.repository.list_chunks(source_ids=request.source_ids, tags=request.tags)
        local_scored = self._score_local_candidates(local_candidates, query_tokens, query_text)
        remote_scored, remote_error_count = self._search_remote_candidates(request, query_tokens, query_text)

        if not remote_scored:
            return local_scored, "local-keyword", remote_error_count

        merged: dict[str, SearchResult] = {item.chunk.id: item for item in remote_scored}
        for item in local_scored:
            existing = merged.get(item.chunk.id)
            if existing is None or item.score > existing.score:
                merged[item.chunk.id] = item
        return (
            sorted(merged.values(), key=lambda item: item.score, reverse=True),
            "hybrid-live-backends",
            remote_error_count,
        )

    def _score_local_candidates(
        self,
        candidates: list[KnowledgeChunk],
        query_tokens: list[str],
        query_text: str,
    ) -> list[SearchResult]:
        scored: list[SearchResult] = []
        for chunk in candidates:
            score, reason = self._score_chunk(chunk, query_tokens, query_text)
            if score <= 0:
                continue
            source = self.repository.get_source(chunk.source_id)
            if source is None:
                continue
            scored.append(
                SearchResult(
                    chunk=chunk,
                    sourceName=source.name,
                    score=round(score, 4),
                    matchReason=reason,
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored

    def _search_remote_candidates(
        self,
        request: SearchRequest,
        query_tokens: list[str],
        query_text: str,
    ) -> tuple[list[SearchResult], int]:
        remote_error_count = 0
        merged: dict[str, SearchResult] = {}

        if self.settings.opensearch_url:
            try:
                for result in self._search_opensearch(request, query_tokens, query_text):
                    merged[result.chunk.id] = result
            except Exception:
                remote_error_count += 1

        if self.settings.qdrant_url:
            try:
                for result in self._search_qdrant(request, query_tokens, query_text):
                    existing = merged.get(result.chunk.id)
                    if existing is None or result.score > existing.score:
                        merged[result.chunk.id] = result
            except Exception:
                remote_error_count += 1

        return sorted(merged.values(), key=lambda item: item.score, reverse=True), remote_error_count

    def _search_opensearch(
        self,
        request: SearchRequest,
        query_tokens: list[str],
        query_text: str,
    ) -> list[SearchResult]:
        base_url = self._normalized_endpoint(self.settings.opensearch_url)
        filters: list[dict[str, object]] = []
        if request.source_ids:
            filters.append({"terms": {"source_id": request.source_ids}})
        if request.tags:
            filters.append({"terms": {"tags": [tag.lower() for tag in request.tags]}})
        payload = {
            "size": max(request.top_k * 4, request.top_k),
            "query": {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": request.query,
                                "fields": [
                                    "document_title^2",
                                    "content",
                                    "keywords^1.5",
                                ],
                            }
                        }
                    ],
                    "filter": filters,
                }
            },
            "_source": [
                "kb_id",
                "source_id",
                "source_name",
                "document_id",
                "document_title",
                "chunk_id",
                "content",
                "keywords",
                "tags",
                "ordinal",
                "created_at",
            ],
        }
        with httpx.Client(timeout=self.settings.connector_timeout_ms / 1000) as client:
            response = client.post(
                f"{base_url}/{self.settings.opensearch_index}/_search",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        results: list[SearchResult] = []
        for hit in data.get("hits", {}).get("hits", []) or []:
            source_payload = hit.get("_source") or {}
            raw_score = float(hit.get("_score") or 0.0)
            result = self._build_remote_result(
                source_payload,
                raw_score=raw_score,
                query_tokens=query_tokens,
                query_text=query_text,
                backend="opensearch",
            )
            if result is not None:
                results.append(result)
        return results

    def _search_qdrant(
        self,
        request: SearchRequest,
        query_tokens: list[str],
        query_text: str,
    ) -> list[SearchResult]:
        base_url = self._normalized_endpoint(self.settings.qdrant_url)
        must_filters: list[dict[str, object]] = []
        if request.source_ids:
            must_filters.append({"key": "source_id", "match": {"any": request.source_ids}})
        if request.tags:
            must_filters.append({"key": "tags", "match": {"any": [tag.lower() for tag in request.tags]}})
        payload: dict[str, object] = {
            "vector": _build_embedding(request.query, self.settings.qdrant_vector_size),
            "limit": max(request.top_k * 4, request.top_k),
            "with_payload": True,
        }
        if must_filters:
            payload["filter"] = {"must": must_filters}
        with httpx.Client(timeout=self.settings.connector_timeout_ms / 1000) as client:
            response = client.post(
                f"{base_url}/collections/{self.settings.qdrant_collection}/points/search",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        results: list[SearchResult] = []
        for hit in data.get("result") or []:
            source_payload = hit.get("payload") or {}
            raw_score = float(hit.get("score") or 0.0)
            result = self._build_remote_result(
                source_payload,
                raw_score=raw_score,
                query_tokens=query_tokens,
                query_text=query_text,
                backend="qdrant",
            )
            if result is not None:
                results.append(result)
        return results

    def _build_remote_result(
        self,
        payload: dict[str, object],
        *,
        raw_score: float,
        query_tokens: list[str],
        query_text: str,
        backend: str,
    ) -> SearchResult | None:
        chunk_id = str(payload.get("chunk_id") or payload.get("chunkId") or "").strip()
        if not chunk_id:
            return None
        fallback_chunk = next(
            (chunk for chunk in self.repository.list_chunks() if chunk.id == chunk_id),
            None,
        )
        chunk = self._coerce_chunk(payload, fallback_chunk)
        if chunk is None:
            return None
        lexical_score, lexical_reason = self._score_chunk(chunk, query_tokens, query_text)
        normalized_remote_score = self._normalize_remote_score(raw_score)
        score = max(lexical_score, (normalized_remote_score * 0.62) + (lexical_score * 0.38))
        if score <= 0:
            return None
        source = self.repository.get_source(chunk.source_id)
        source_name = str(
            payload.get("source_name")
            or payload.get("sourceName")
            or (source.name if source is not None else chunk.source_id)
        )
        return SearchResult(
            chunk=chunk,
            sourceName=source_name,
            score=round(score, 4),
            matchReason=f"{backend} hit + {lexical_reason}",
        )

    def _coerce_chunk(
        self,
        payload: dict[str, object],
        fallback_chunk: KnowledgeChunk | None,
    ) -> KnowledgeChunk | None:
        if fallback_chunk is not None:
            return fallback_chunk
        content = str(payload.get("content") or "").strip()
        source_id = str(payload.get("source_id") or payload.get("sourceId") or "").strip()
        document_id = str(payload.get("document_id") or payload.get("documentId") or "").strip()
        document_title = str(payload.get("document_title") or payload.get("documentTitle") or "").strip()
        chunk_id = str(payload.get("chunk_id") or payload.get("chunkId") or "").strip()
        if not (content and source_id and document_id and document_title and chunk_id):
            return None
        keywords = payload.get("keywords") if isinstance(payload.get("keywords"), list) else []
        tags = payload.get("tags") if isinstance(payload.get("tags"), list) else []
        return KnowledgeChunk(
            id=chunk_id,
            sourceId=source_id,
            documentId=document_id,
            documentTitle=document_title,
            ordinal=int(payload.get("ordinal") or 1),
            content=content,
            tokenEstimate=max(1, len(content) // 4),
            keywords=[str(item).lower() for item in keywords],
            tags=[str(item) for item in tags],
            createdAt=str(payload.get("created_at") or payload.get("createdAt") or "1970-01-01T00:00:00+00:00"),
        )

    @staticmethod
    def _normalize_remote_score(value: float) -> float:
        if value <= 0:
            return 0.0
        if value <= 1:
            return value
        return min(1.0, 0.35 + (math.log1p(value) / 5.0))

    @staticmethod
    def _normalized_endpoint(endpoint: str | None) -> str:
        if not endpoint:
            return ""
        parsed = urlparse(endpoint)
        if parsed.scheme and parsed.netloc:
            return endpoint.rstrip("/")
        return f"http://{endpoint.strip().rstrip('/')}"

    def _score_chunk(self, chunk: KnowledgeChunk, query_tokens: list[str], query_text: str) -> tuple[float, str]:
        if not query_tokens:
            return 0.0, "empty query"
        haystack = _normalize_text(f"{chunk.document_title} {chunk.content}")
        matched_tokens = [token for token in query_tokens if token in haystack]
        if not matched_tokens:
            return 0.0, "no overlap"

        lexical = len(set(matched_tokens)) / len(set(query_tokens))
        keyword_overlap = len(set(query_tokens).intersection(chunk.keywords)) / max(len(set(query_tokens)), 1)
        phrase_bonus = 0.35 if query_text and query_text in haystack else 0.0
        title_bonus = 0.12 if any(token in _normalize_text(chunk.document_title) for token in query_tokens) else 0.0
        score = (lexical * 0.55) + (keyword_overlap * 0.18) + phrase_bonus + title_bonus
        return score, f"matched tokens: {', '.join(sorted(set(matched_tokens))[:5])}"


@lru_cache(maxsize=1)
def get_search_service() -> SearchService:
    return SearchService(get_repository())
