from collections import Counter
from functools import lru_cache

from app.core.metrics import (
    DEGRADED_RETRIEVALS_TOTAL,
    EMPTY_RETRIEVALS_TOTAL,
    RETRIEVAL_DURATION_SECONDS,
    RETRIEVAL_REQUESTS_TOTAL,
)
from app.core.tracing import start_span
from app.models.rag import (
    CountBucket,
    KnowledgeSearchCandidate,
    QueryRewriteResult,
    RetrievalDiagnosticResponse,
    RetrieveRequest,
    RetrieveResponse,
    RetrievalCitation,
    SourceBreakdown,
)
from app.services.query_rewriter import QueryRewriter, tokenize


class RetrievalService:
    def __init__(self, query_rewriter: QueryRewriter) -> None:
        self.query_rewriter = query_rewriter

    def rewrite_query(self, query: str) -> QueryRewriteResult:
        return self.query_rewriter.rewrite(query)

    async def search_candidates(
        self,
        request: RetrieveRequest,
        search_client,
        trace_headers: dict[str, str] | None = None,
        cache_service=None,
    ) -> tuple[QueryRewriteResult, list[KnowledgeSearchCandidate]]:
        with start_span(
            "rag.retrieval.search_candidates",
            smartcloud_retrieval_query=request.query,
            smartcloud_retrieval_top_k=request.top_k,
            smartcloud_retrieval_source_filter_count=len(request.filters.source_ids),
            smartcloud_retrieval_tag_filter_count=len(request.filters.tags),
        ) as span:
            with RETRIEVAL_DURATION_SECONDS.time():
                if cache_service is not None:
                    cached = cache_service.get(request)
                    if cached is not None:
                        rewrite, candidates = cached
                        if span is not None:
                            span.set_attribute("smartcloud.retrieval.cache_hit", True)
                            span.set_attribute("smartcloud.retrieval.expanded_term_count", len(rewrite.expanded_terms))
                            span.set_attribute("smartcloud.retrieval.candidate_count", len(candidates))
                        return rewrite, candidates
                rewrite = self.rewrite_query(request.query)
                RETRIEVAL_REQUESTS_TOTAL.inc()
                candidates = await search_client.search(
                    request,
                    rewrite.rewritten_query,
                    headers=trace_headers,
                )
                if cache_service is not None:
                    cache_service.set(request, rewrite, candidates)
            if span is not None:
                span.set_attribute("smartcloud.retrieval.cache_hit", False)
                span.set_attribute("smartcloud.retrieval.expanded_term_count", len(rewrite.expanded_terms))
                span.set_attribute("smartcloud.retrieval.candidate_count", len(candidates))
            return rewrite, candidates

    async def retrieve(
        self,
        request: RetrieveRequest,
        search_client,
        trace_headers: dict[str, str] | None = None,
        cache_service=None,
    ) -> RetrieveResponse:
        rewrite, candidates = await self.search_candidates(
            request,
            search_client,
            trace_headers,
            cache_service=cache_service,
        )
        return self.build_response(request, candidates, rewrite.rewritten_query)

    def build_response(
        self,
        request: RetrieveRequest,
        candidates: list[KnowledgeSearchCandidate],
        rewritten_query: str,
        degraded: bool = False,
        degradation_note: str | None = None,
    ) -> RetrieveResponse:
        query_terms = tokenize(rewritten_query)
        ranked = sorted(
            candidates,
            key=lambda item: self._rerank_score(item, query_terms),
            reverse=True,
        )
        citations = [
            RetrievalCitation(
                chunkId=item.chunk.id,
                sourceId=item.chunk.source_id,
                sourceName=item.source_name,
                documentId=item.chunk.document_id,
                documentTitle=item.chunk.document_title,
                snippet=self._snippet(item.chunk.content),
                score=round(self._rerank_score(item, query_terms), 4),
                reasoning=item.match_reason,
            )
            for item in ranked[: request.top_k]
        ]
        notes = []
        if degradation_note:
            notes.append(degradation_note)
        if not citations:
            notes.append("未检索到匹配知识，请先补充知识库文档或放宽过滤条件。")
            EMPTY_RETRIEVALS_TOTAL.inc()
        elif citations[0].score < 0.45:
            notes.append("当前命中结果存在弱相关项，建议在后台补充更精准的知识标题与标签。")
        if degraded:
            DEGRADED_RETRIEVALS_TOTAL.inc()
        return RetrieveResponse(
            query=request.query,
            rewrittenQuery=rewritten_query,
            citations=citations,
            coverageNotes=notes,
            degraded=degraded,
        )

    def build_diagnostic(
        self,
        request: RetrieveRequest,
        candidates: list[KnowledgeSearchCandidate],
        rewrite: QueryRewriteResult,
        degraded: bool = False,
        degradation_note: str | None = None,
    ) -> RetrievalDiagnosticResponse:
        query_terms = tokenize(rewrite.rewritten_query)
        response = self.build_response(
            request,
            candidates,
            rewrite.rewritten_query,
            degraded=degraded,
            degradation_note=degradation_note,
        )
        source_breakdown = self._build_source_breakdown(candidates)
        tag_breakdown = self._build_tag_breakdown(candidates)
        unmatched_terms = self._build_unmatched_terms(
            candidates,
            rewrite.expanded_terms or query_terms,
        )
        return RetrievalDiagnosticResponse(
            query=request.query,
            rewrittenQuery=rewrite.rewritten_query,
            expandedTerms=rewrite.expanded_terms,
            queryTerms=query_terms,
            unmatchedTerms=unmatched_terms,
            requestedTopK=request.top_k,
            appliedFilters=request.filters,
            candidateCount=len(candidates),
            strategy=response.strategy,
            sourceBreakdown=source_breakdown,
            tagBreakdown=tag_breakdown,
            citations=response.citations,
            coverageNotes=response.coverage_notes,
            degraded=response.degraded,
        )

    def _rerank_score(self, candidate: KnowledgeSearchCandidate, query_terms: list[str]) -> float:
        title = candidate.chunk.document_title.lower()
        content = candidate.chunk.content.lower()
        chunk_keywords = set(candidate.chunk.keywords)
        term_hits = sum(1 for term in set(query_terms) if term in title or term in content)
        keyword_hits = sum(1 for term in set(query_terms) if term in chunk_keywords)
        title_boost = 0.1 if any(term in title for term in query_terms) else 0.0
        density = term_hits / max(len(set(query_terms)), 1)
        keyword_score = keyword_hits / max(len(set(query_terms)), 1)
        return (candidate.score * 0.68) + (density * 0.22) + (keyword_score * 0.1) + title_boost

    @staticmethod
    def _snippet(content: str) -> str:
        return content.strip()[:220]

    @staticmethod
    def _build_source_breakdown(
        candidates: list[KnowledgeSearchCandidate],
        limit: int = 6,
    ) -> list[SourceBreakdown]:
        source_summary: dict[str, dict[str, str | int | float]] = {}
        for candidate in candidates:
            summary = source_summary.setdefault(
                candidate.chunk.source_id,
                {
                    "sourceName": candidate.source_name,
                    "hitCount": 0,
                    "bestScore": 0.0,
                },
            )
            summary["hitCount"] = int(summary["hitCount"]) + 1
            summary["bestScore"] = max(float(summary["bestScore"]), candidate.score)
        return [
            SourceBreakdown(
                sourceId=source_id,
                sourceName=str(summary["sourceName"]),
                hitCount=int(summary["hitCount"]),
                bestScore=round(float(summary["bestScore"]), 4),
            )
            for source_id, summary in sorted(
                source_summary.items(),
                key=lambda item: (
                    -int(item[1]["hitCount"]),
                    -float(item[1]["bestScore"]),
                    str(item[1]["sourceName"]),
                ),
            )[:limit]
        ]

    @staticmethod
    def _build_tag_breakdown(
        candidates: list[KnowledgeSearchCandidate],
        limit: int = 8,
    ) -> list[CountBucket]:
        tag_counts = Counter()
        for candidate in candidates:
            tag_counts.update(tag.lower() for tag in candidate.chunk.tags)
        return [
            CountBucket(label=label, count=count)
            for label, count in sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
        ]

    @staticmethod
    def _build_unmatched_terms(
        candidates: list[KnowledgeSearchCandidate],
        query_terms: list[str],
    ) -> list[str]:
        unmatched: list[str] = []
        for term in query_terms:
            found = False
            for candidate in candidates:
                if (
                    term in candidate.chunk.document_title.lower()
                    or term in candidate.chunk.content.lower()
                    or term in set(candidate.chunk.keywords)
                ):
                    found = True
                    break
            if not found and term not in unmatched:
                unmatched.append(term)
        return unmatched[:8]


@lru_cache(maxsize=1)
def get_retrieval_service() -> RetrievalService:
    return RetrievalService(QueryRewriter())
