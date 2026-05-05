from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from app.core.config import get_settings
from app.core.metrics import (
    DEGRADED_RETRIEVALS_TOTAL,
    EMPTY_RETRIEVALS_TOTAL,
    RETRIEVAL_DURATION_SECONDS,
    RETRIEVAL_REQUESTS_TOTAL,
)
from app.core.tracing import start_span
from app.models.rag import (
    ContextBuildResult,
    CountBucket,
    KnowledgeSearchCandidate,
    QueryRewriteResult,
    RetrievalDiagnosticResponse,
    RetrieveRequest,
    RetrieveResponse,
    RetrievalCitation,
    RetrievalSource,
    SourceBreakdown,
)
from app.services.hybrid_retrieval import (
    BM25Scorer,
    HybridRetrievalConfig,
    tokenize_for_bm25,
    weighted_score_fusion,
)
from app.services.query_rewriter import QueryRewriter, tokenize

DOMAIN_KEYWORDS = {
    "billing": ["账单", "发票", "billing"],
    "icp": ["备案", "icp", "实名"],
    "product": ["gpu", "云服务器", "轻量服务器", "实例", "cdn", "域名", "ssl", "安全组"],
    "marketing": ["营销", "活动", "优惠"],
    "research": ["调研", "报告", "research"],
}


def _build_citation_id(chunk_id: str, backend_used: str) -> str:
    return f"{backend_used}:{chunk_id}"


class ContextBuilder:
    def __init__(self, max_context_tokens: int) -> None:
        self.max_context_tokens = max_context_tokens

    def build(self, citations: list[RetrievalCitation]) -> ContextBuildResult:
        ordered = sorted(citations, key=lambda item: item.score, reverse=True)
        seen_chunks: set[tuple[str, str]] = set()
        blocks: list[str] = []
        token_total = 0
        included_count = 0
        truncated_count = 0

        for citation in ordered:
            normalized = " ".join(citation.snippet.split())
            dedup_key = (citation.document_id, normalized[:120])
            if dedup_key in seen_chunks:
                continue
            block = f"[来源: {citation.document_title}] {normalized}"
            block_tokens = self._estimate_tokens(block)
            if token_total + block_tokens > self.max_context_tokens:
                truncated_count += 1
                continue
            seen_chunks.add(dedup_key)
            blocks.append(block)
            token_total += block_tokens
            included_count += 1

        return ContextBuildResult(
            contextText="\n\n".join(blocks),
            tokenEstimate=token_total,
            includedCount=included_count,
            truncatedCount=truncated_count,
        )

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, len(tokenize(text)))


class RetrievalService:
    def __init__(self, query_rewriter: QueryRewriter) -> None:
        self.query_rewriter = query_rewriter
        self.settings = get_settings()
        self.context_builder = ContextBuilder(self.settings.max_context_tokens)
        self._bm25_scorer: BM25Scorer | None = None
        self._bm25_corpus_ids: list[str] = []

    def _build_bm25_index(self, candidates: list[KnowledgeSearchCandidate]) -> None:
        corpus: list[list[str]] = []
        ids: list[str] = []
        for c in candidates:
            corpus.append(tokenize_for_bm25(c.chunk.content))
            ids.append(c.chunk.id)
        self._bm25_scorer = BM25Scorer()
        self._bm25_scorer.fit(corpus)
        self._bm25_corpus_ids = ids

    def _bm25_score_candidates(
        self, candidates: list[KnowledgeSearchCandidate], query_terms: list[str]
    ) -> list[tuple[str, float]]:
        if self._bm25_scorer is None:
            return [(c.chunk.id, 0.0) for c in candidates]
        scored: list[tuple[str, float]] = []
        for c in candidates:
            doc_tokens = tokenize_for_bm25(c.chunk.content)
            s = self._bm25_scorer.score(doc_tokens, query_terms)
            scored.append((c.chunk.id, s))
        return scored

    def rewrite_query(self, request_or_query: RetrieveRequest | str) -> QueryRewriteResult:
        if isinstance(request_or_query, RetrieveRequest):
            return self.query_rewriter.rewrite(
                request_or_query.query,
                request_or_query.conversation_context,
            )
        return self.query_rewriter.rewrite(request_or_query)

    async def search_candidates(self, request: RetrieveRequest, search_client, trace_headers: dict[str, str] | None = None, cache_service=None) -> tuple[QueryRewriteResult, list[KnowledgeSearchCandidate]]:
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
                rewrite = self.rewrite_query(request)
                RETRIEVAL_REQUESTS_TOTAL.inc()
                candidates = await search_client.search(request, rewrite.rewritten_query, headers=trace_headers)
                if cache_service is not None:
                    cache_service.set(request, rewrite, candidates)
            if span is not None:
                span.set_attribute("smartcloud.retrieval.cache_hit", False)
                span.set_attribute("smartcloud.retrieval.expanded_term_count", len(rewrite.expanded_terms))
                span.set_attribute("smartcloud.retrieval.candidate_count", len(candidates))
            return rewrite, candidates

    async def retrieve(self, request: RetrieveRequest, search_client, trace_headers: dict[str, str] | None = None, cache_service=None) -> RetrieveResponse:
        rewrite, candidates = await self.search_candidates(request, search_client, trace_headers, cache_service=cache_service)
        return self.build_response(request, candidates, rewrite.rewritten_query)

    async def hybrid_retrieve(
        self,
        request: RetrieveRequest,
        search_client,
        trace_headers: dict[str, str] | None = None,
        cache_service=None,
        semantic_weight: float = 0.6,
    ) -> RetrieveResponse:
        """Hybrid retrieval: semantic search + BM25 keyword scoring fused via weighted sum."""
        rewrite, candidates = await self.search_candidates(
            request, search_client, trace_headers, cache_service=cache_service
        )
        if len(candidates) <= 1:
            return self.build_response(
                request, candidates, rewrite.rewritten_query, backend_used="hybrid"
            )

        # Build BM25 index and score
        self._build_bm25_index(candidates)
        query_terms = tokenize_for_bm25(rewrite.rewritten_query)
        bm25_scored = self._bm25_score_candidates(candidates, query_terms)

        # Semantic scores from the vector search
        semantic_scored = [(c.chunk.id, c.score) for c in candidates]

        # Weighted fusion
        fused = weighted_score_fusion(
            semantic_scored, bm25_scored, semantic_weight=semantic_weight
        )

        # Build score lookup
        fused_map = dict(fused)

        # Rerank candidates by fused score
        query_terms = tokenize(rewrite.rewritten_query)
        ranked = sorted(
            candidates,
            key=lambda item: fused_map.get(item.chunk.id, 0.0),
            reverse=True,
        )

        citations = []
        for item in ranked:
            score = round(fused_map.get(item.chunk.id, 0.0), 4)
            if score < self.settings.min_rerank_score:
                continue
            citations.append(
                RetrievalCitation(
                    citationId=_build_citation_id(item.chunk.id, "hybrid"),
                    chunkId=item.chunk.id,
                    sourceId=item.chunk.source_id,
                    sourceName=item.source_name,
                    documentId=item.chunk.document_id,
                    documentTitle=item.chunk.document_title,
                    snippet=self._snippet(item.chunk.content),
                    score=score,
                    backendUsed="hybrid",
                    reasoning=item.match_reason,
                )
            )
            if len(citations) >= request.top_k:
                break

        notes: list[str] = []
        if not citations:
            notes.append("未找到匹配知识，建议补充知识库文档或放宽筛选条件")
            EMPTY_RETRIEVALS_TOTAL.inc()
        elif citations[0].score < 0.45:
            notes.append("当前检索结果置信度较低，建议在后台校准知识库标签")

        context = self.context_builder.build(citations)
        sources = [self._build_retrieval_source(c) for c in citations]

        return RetrieveResponse(
            query=request.query,
            rewrittenQuery=rewrite.rewritten_query,
            citations=citations,
            coverageNotes=notes,
            degraded=False,
            degradationNote=None,
            backendUsed="hybrid",
            sources=sources,
            context=context,
        )

    def build_response(self, request: RetrieveRequest, candidates: list[KnowledgeSearchCandidate], rewritten_query: str, degraded: bool = False, degradation_note: str | None = None, include_context: bool = False, backend_used: str = "local-keyword") -> RetrieveResponse:
        query_terms = tokenize(rewritten_query)
        ranked = sorted(candidates, key=lambda item: self._rerank_score(item, query_terms), reverse=True)
        citations = []
        for item in ranked:
            score = round(self._rerank_score(item, query_terms), 4)
            if score < self.settings.min_rerank_score:
                continue
            citations.append(
                RetrievalCitation(
                    citationId=_build_citation_id(item.chunk.id, backend_used),
                    chunkId=item.chunk.id,
                    sourceId=item.chunk.source_id,
                    sourceName=item.source_name,
                    documentId=item.chunk.document_id,
                    documentTitle=item.chunk.document_title,
                    snippet=self._snippet(item.chunk.content),
                    score=score,
                    backendUsed=backend_used,
                    reasoning=item.match_reason,
                )
            )
            if len(citations) >= request.top_k:
                break
        notes = []
        if degradation_note:
            notes.append(degradation_note)
        if not citations:
            notes.append("未找到匹配知识，建议补充知识库文档或放宽筛选条件")
            EMPTY_RETRIEVALS_TOTAL.inc()
        elif citations[0].score < 0.45:
            notes.append("当前检索结果置信度较低，建议在后台校准知识库标签")
        if degraded:
            DEGRADED_RETRIEVALS_TOTAL.inc()
        context = self.context_builder.build(citations) if include_context else None
        sources = [self._build_retrieval_source(citation) for citation in citations]
        return RetrieveResponse(
            query=request.query,
            rewrittenQuery=rewritten_query,
            citations=citations,
            coverageNotes=notes,
            degraded=degraded,
            degradationNote=degradation_note,
            backendUsed=backend_used,
            sources=sources,
            context=context,
        )

    def build_context(self, request: RetrieveRequest, candidates: list[KnowledgeSearchCandidate], rewritten_query: str, backend_used: str = "local-keyword") -> ContextBuildResult:
        response = self.build_response(request, candidates, rewritten_query, include_context=True, backend_used=backend_used)
        return response.context or ContextBuildResult(contextText="", tokenEstimate=0, includedCount=0, truncatedCount=0)

    def build_diagnostic(self, request: RetrieveRequest, candidates: list[KnowledgeSearchCandidate], rewrite: QueryRewriteResult, degraded: bool = False, degradation_note: str | None = None, backend_used: str = "local-keyword") -> RetrievalDiagnosticResponse:
        query_terms = tokenize(rewrite.rewritten_query)
        response = self.build_response(request, candidates, rewrite.rewritten_query, degraded=degraded, degradation_note=degradation_note, backend_used=backend_used)
        source_breakdown = self._build_source_breakdown(candidates)
        tag_breakdown = self._build_tag_breakdown(candidates)
        unmatched_terms = self._build_unmatched_terms(candidates, rewrite.expanded_terms or query_terms)
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
            backendUsed=response.backend_used,
            sourceBreakdown=source_breakdown,
            tagBreakdown=tag_breakdown,
            citations=response.citations,
            coverageNotes=response.coverage_notes,
            degraded=response.degraded,
        )

    def _rerank_score(self, candidate: KnowledgeSearchCandidate, query_terms: list[str]) -> float:
        title = candidate.chunk.document_title.lower()
        content = candidate.chunk.content.lower()
        source_name = candidate.source_name.lower()
        chunk_keywords = {keyword.lower() for keyword in candidate.chunk.keywords}
        unique_terms = set(query_terms)
        term_hits = sum(1 for term in unique_terms if term in title or term in content)
        keyword_hits = sum(1 for term in unique_terms if term in chunk_keywords)
        title_boost = self.settings.rerank_title_boost if any(term in title for term in query_terms) else 0.0
        density = term_hits / max(len(unique_terms), 1)
        keyword_score = keyword_hits / max(len(unique_terms), 1)
        source_boost = self._source_type_boost(unique_terms, title, source_name, chunk_keywords)
        recency_boost = self._recency_boost(candidate.chunk.created_at)
        return (
            (candidate.score * self.settings.rerank_score_weight)
            + (density * self.settings.rerank_density_weight)
            + (keyword_score * self.settings.rerank_keyword_weight)
            + title_boost
            + source_boost
            + recency_boost
        )

    def _source_type_boost(self, query_terms: set[str], title: str, source_name: str, chunk_keywords: set[str]) -> float:
        haystack = " ".join([title, source_name, " ".join(chunk_keywords)])
        for _, keywords in DOMAIN_KEYWORDS.items():
            if not any(keyword in query_terms for keyword in keywords):
                continue
            if any(keyword in haystack for keyword in keywords):
                return self.settings.rerank_source_type_boost
        return 0.0

    def _recency_boost(self, created_at: str) -> float:
        try:
            normalized = created_at.replace("Z", "+00:00")
            created = datetime.fromisoformat(normalized)
        except ValueError:
            return 0.0
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        if created >= datetime.now(UTC) - timedelta(days=30):
            return self.settings.rerank_recency_boost
        return 0.0

    @staticmethod
    def _snippet(content: str) -> str:
        return content.strip()[:220]

    @staticmethod
    def _build_retrieval_source(citation: RetrievalCitation) -> RetrievalSource:
        return RetrievalSource(
            sourceId=citation.source_id,
            sourceType="knowledge_base",
            title=citation.document_title,
            docId=citation.document_id,
            chunkId=citation.chunk_id,
            score=citation.score,
            uri=f"kb://{citation.source_id}/{citation.document_id}#{citation.chunk_id}",
            snippet=citation.snippet,
            backendUsed=citation.backend_used,
            domain=None,
        )

    @staticmethod
    def _build_source_breakdown(candidates: list[KnowledgeSearchCandidate], limit: int = 6) -> list[SourceBreakdown]:
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
                key=lambda item: (-int(item[1]["hitCount"]), -float(item[1]["bestScore"]), str(item[1]["sourceName"])),
            )[:limit]
        ]

    @staticmethod
    def _build_tag_breakdown(candidates: list[KnowledgeSearchCandidate], limit: int = 8) -> list[CountBucket]:
        tag_counts = Counter()
        for candidate in candidates:
            tag_counts.update(tag.lower() for tag in candidate.chunk.tags)
        return [CountBucket(label=label, count=count) for label, count in sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]

    @staticmethod
    def _build_unmatched_terms(candidates: list[KnowledgeSearchCandidate], query_terms: list[str]) -> list[str]:
        unmatched: list[str] = []
        for term in query_terms:
            found = False
            for candidate in candidates:
                if term in candidate.chunk.document_title.lower() or term in candidate.chunk.content.lower() or term in {keyword.lower() for keyword in candidate.chunk.keywords}:
                    found = True
                    break
            if not found and term not in unmatched:
                unmatched.append(term)
        return unmatched[:8]


@lru_cache(maxsize=1)
def get_retrieval_service() -> RetrievalService:
    return RetrievalService(QueryRewriter())