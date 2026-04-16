import re
from collections import Counter
from functools import lru_cache

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

    def search(self, request: SearchRequest) -> SearchResponse:
        with start_span(
            "knowledge.search",
            smartcloud_search_query=request.query,
            smartcloud_search_top_k=request.top_k,
            smartcloud_search_source_filter_count=len(request.source_ids),
            smartcloud_search_tag_filter_count=len(request.tags),
        ) as span:
            SEARCH_REQUESTS_TOTAL.inc()
            candidates = self.repository.list_chunks(source_ids=request.source_ids, tags=request.tags)
            query_tokens = _tokenize(request.query)
            query_text = _normalize_text(request.query)
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
                span.set_attribute("smartcloud.search.candidate_count", len(candidates))
                span.set_attribute("smartcloud.search.total_hits", len(scored))
                span.set_attribute("smartcloud.search.result_count", len(results))
                span.set_attribute("smartcloud.search.query_token_count", len(query_tokens))

            return SearchResponse(
                query=request.query,
                total=len(scored),
                queryTokens=query_tokens,
                appliedFilters=SearchAppliedFilters(sourceIds=request.source_ids, tags=request.tags),
                sourceBreakdown=source_breakdown,
                tagBreakdown=tag_breakdown,
                results=results,
            )

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
