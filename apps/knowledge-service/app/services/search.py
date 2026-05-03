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
from app.services.embeddings import build_embedding_provider
from app.services.index_targets import KnowledgeIndexTargetResolver
from app.services.store import KnowledgeStoreRepository
from app.services.store_provider import get_repository
from app.services.text_processing import estimate_tokens

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_+-]+|[\u4e00-\u9fff]+")


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


class SearchService:
    def __init__(self, repository: KnowledgeStoreRepository) -> None:
        self.repository = repository
        self.settings = get_settings()
        self.embedding_provider = build_embedding_provider(self.settings)
        self.target_resolver = KnowledgeIndexTargetResolver(self.settings)

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
                backendUsed=backend_used,
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
        domain = self._resolve_request_domain(request, local_candidates)
        remote_scored, remote_backend_label, remote_error_count = self._search_remote_candidates(
            request,
            query_tokens,
            query_text,
            domain=domain,
        )

        if not remote_scored:
            return local_scored, "local-keyword", remote_error_count
        if not local_scored:
            return self._normalize_scores(remote_scored), remote_backend_label, remote_error_count

        merged: dict[str, SearchResult] = {item.chunk.id: item for item in remote_scored}
        for item in local_scored:
            existing = merged.get(item.chunk.id)
            if existing is None or item.score > existing.score:
                merged[item.chunk.id] = item
        filtered = [item for item in merged.values() if item.score >= self.settings.search_min_score]
        backend_used = remote_backend_label if remote_backend_label != "local-keyword" else "hybrid-live-backends"
        return (
            self._normalize_scores(sorted(filtered, key=lambda item: item.score, reverse=True)),
            backend_used,
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
            if score < self.settings.search_min_score:
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
        *,
        domain: str | None,
    ) -> tuple[list[SearchResult], str, int]:
        remote_error_count = 0
        merged: dict[str, SearchResult] = {}
        used_backends: list[str] = []
        target_resolutions = self.target_resolver.search_targets(domain=domain)

        if self.settings.opensearch_url:
            for targets in target_resolutions:
                try:
                    results = self._search_opensearch(
                        request,
                        query_tokens,
                        query_text,
                        target_index=targets.opensearch_index,
                    )
                    if results:
                        label = "opensearch" if not targets.used_fallback else "opensearch-fallback"
                        if label not in used_backends:
                            used_backends.append(label)
                    for result in results:
                        existing = merged.get(result.chunk.id)
                        if existing is None or result.score > existing.score:
                            merged[result.chunk.id] = result
                except Exception:
                    remote_error_count += 1

        if self.settings.qdrant_url:
            for targets in target_resolutions:
                try:
                    results = self._search_qdrant(
                        request,
                        query_tokens,
                        query_text,
                        target_collection=targets.qdrant_collection,
                    )
                    if results:
                        label = "qdrant" if not targets.used_fallback else "qdrant-fallback"
                        if label not in used_backends:
                            used_backends.append(label)
                    for result in results:
                        existing = merged.get(result.chunk.id)
                        if existing is None or result.score > existing.score:
                            merged[result.chunk.id] = result
                except Exception:
                    remote_error_count += 1

        backend_label = "hybrid-live-backends"
        if used_backends == ["opensearch"]:
            backend_label = "opensearch-only"
        elif used_backends == ["qdrant"]:
            backend_label = "qdrant-only"
        elif used_backends:
            backend_label = "hybrid-live-backends"
        return (
            self._normalize_scores(
                sorted(
                    [item for item in merged.values() if item.score >= self.settings.search_min_score],
                    key=lambda item: item.score,
                    reverse=True,
                )
            ),
            backend_label,
            remote_error_count,
        )

    def _search_opensearch(
        self,
        request: SearchRequest,
        query_tokens: list[str],
        query_text: str,
        *,
        target_index: str,
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
                                "fields": ["document_title^2", "content", "keywords^1.5"],
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
                "metadata",
            ],
        }
        with httpx.Client(timeout=self.settings.connector_timeout_ms / 1000, trust_env=False) as client:
            response = client.post(f"{base_url}/{target_index}/_search", json=payload)
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
        *,
        target_collection: str,
    ) -> list[SearchResult]:
        base_url = self._normalized_endpoint(self.settings.qdrant_url)
        must_filters: list[dict[str, object]] = []
        if request.source_ids:
            must_filters.append({"key": "source_id", "match": {"any": request.source_ids}})
        if request.tags:
            must_filters.append({"key": "tags", "match": {"any": [tag.lower() for tag in request.tags]}})
        vector = self.embedding_provider.embed([request.query])[0]
        payload: dict[str, object] = {
            "vector": vector,
            "limit": max(request.top_k * 4, request.top_k),
            "with_payload": True,
        }
        if must_filters:
            payload["filter"] = {"must": must_filters}
        with httpx.Client(timeout=self.settings.connector_timeout_ms / 1000, trust_env=False) as client:
            response = client.post(
                f"{base_url}/collections/{target_collection}/points/search",
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

    def _resolve_request_domain(
        self,
        request: SearchRequest,
        local_candidates: list[KnowledgeChunk],
    ) -> str | None:
        for tag in request.tags:
            normalized = tag.strip().lower()
            if normalized.startswith("domain:"):
                derived = normalized.split(":", 1)[1].strip().replace("-", "_")
                return derived or None
        for chunk in local_candidates:
            payload = chunk.metadata if isinstance(chunk.metadata, dict) else {}
            domain_hints = payload.get("domainHints")
            if isinstance(domain_hints, list):
                for item in domain_hints:
                    if isinstance(item, str) and item.strip():
                        return item.strip().lower().replace("-", "_")
            domain = payload.get("domain")
            if isinstance(domain, str) and domain.strip():
                return domain.strip().lower().replace("-", "_")
        return None

    @staticmethod
    def _normalize_scores(results: list[SearchResult]) -> list[SearchResult]:
        normalized: list[SearchResult] = []
        for item in results:
            normalized.append(item.model_copy(update={"score": round(max(0.0, min(item.score, 1.0)), 4)}))
        return normalized

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
        fallback_chunk = next((chunk for chunk in self.repository.list_chunks() if chunk.id == chunk_id), None)
        chunk = self._coerce_chunk(payload, fallback_chunk)
        if chunk is None:
            return None
        lexical_score, lexical_reason = self._score_chunk(chunk, query_tokens, query_text)
        normalized_remote_score = self._normalize_remote_score(raw_score)
        score = max(
            lexical_score,
            (normalized_remote_score * self.settings.search_remote_weight)
            + (lexical_score * self.settings.search_lexical_weight),
        )
        score = min(1.0, score)
        if score < self.settings.search_min_score:
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
        content = str(payload.get("content") or payload.get("text") or "").strip()
        source_id = str(payload.get("source_id") or payload.get("sourceId") or "").strip()
        document_id = str(payload.get("document_id") or payload.get("documentId") or "").strip()
        document_title = str(payload.get("document_title") or payload.get("documentTitle") or payload.get("title") or "").strip()
        chunk_id = str(payload.get("chunk_id") or payload.get("chunkId") or payload.get("id") or "").strip()
        if not (content and source_id and document_id and document_title and chunk_id):
            return None
        keywords = payload.get("keywords") if isinstance(payload.get("keywords"), list) else []
        tags = payload.get("tags") if isinstance(payload.get("tags"), list) else []
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        return KnowledgeChunk(
            id=chunk_id,
            sourceId=source_id,
            documentId=document_id,
            documentTitle=document_title,
            ordinal=int(payload.get("ordinal") or 1),
            content=content,
            tokenEstimate=int(payload.get("token_estimate") or payload.get("tokenEstimate") or estimate_tokens(content)),
            keywords=[str(item).lower() for item in keywords],
            tags=[str(item) for item in tags],
            metadata=metadata,
            createdAt=str(payload.get("created_at") or payload.get("createdAt") or "1970-01-01T00:00:00+00:00"),
        )

    @staticmethod
    def _normalize_remote_score(value: float) -> float:
        if value <= 0:
            return 0.0
        if value <= 1:
            return value
        return min(1.0, math.log1p(value) / math.log1p(100.0))

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
