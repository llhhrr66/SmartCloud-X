# RAG Service Baseline

FastAPI-based retrieval service for SmartCloud-X.

## Scope
- query rewrite with keyword, synonym, and lightweight multi-turn conversation-context expansion
- retrieval endpoint with citations, stable citation IDs, backend-used source marker, and coverage notes
- diagnostics endpoint for rewrite, filters, candidate counts, grounded citations, source/tag coverage, and unmatched-term inspection
- standalone rewrite endpoint for debugging and standalone context endpoint for orchestrator consumption
- admin diagnostics endpoint under `/api/v1/admin/retrieval/diagnostics` with canonical external envelopes for the admin console and future gateway proxying
- answer composition endpoint without external LLM dependency, now fed by bounded context-builder output
- Prometheus metrics, request-context forwarding, standard trace/response headers, upstream degradation handling, empty/degraded retrieval quality counters, and an optional Redis-backed retrieval cache with local fallback
- OpenTelemetry spans for retrieval orchestration, upstream knowledge-service calls, and answer composition with OTLP export to Phoenix-compatible collectors when tracing is enabled
- readiness-aware health diagnostics with an active probe against `knowledge-service`
- readiness and upstream probe gauges on `/metrics` so Prometheus/Grafana can alert on degraded dependencies without scraping `/healthz` JSON
- browser-safe CORS defaults for `web-admin`

## Endpoints
- `GET /healthz`
- `GET /metrics`
- `GET /api/rag/v1/capabilities`
- `POST /api/rag/v1/rewrite`
- `POST /api/rag/v1/retrieve`
- `POST /api/rag/v1/diagnose`
- `POST /api/rag/v1/context`
- `POST /api/rag/v1/answer`
- `DELETE /api/rag/v1/cache`
- `POST /api/v1/admin/retrieval/diagnostics`
- `POST /api/v1/admin/cache/clear`

## Retrieval chain status
- Query Rewrite: tokenization + configurable synonym expansion; accepts `conversationContext` and merges recent message entities into rewritten terms.
- Hybrid Search: still proxies `knowledge-service` search APIs; no direct Qdrant/OpenSearch access was introduced.
- Rerank: deterministic, but now configurable through environment weights, source-type/domain boosts, recency boost, and minimum-score filtering.
- Context Build: bounded `ContextBuilder` enforces `SMARTCLOUD_RAG_MAX_CONTEXT_TOKENS` (default 3000), orders by relevance score, deduplicates overlapping chunks from the same document, and emits `[来源: 文档标题]` markers plus structured stats.
- Citation Pack: still returns structured citations with source, score, reasoning, stable `citationId`, and `backendUsed`; `/answer` now also returns the context build result used to compose the answer.

## Configuration
- `SMARTCLOUD_RAG_SYNONYM_FILE`: optional JSON file path for synonym overrides/extensions. Falls back to the built-in synonym map if missing or invalid.
- `SMARTCLOUD_RAG_MAX_CONTEXT_TOKENS`: maximum token budget for the context builder. Default `3000`.
- `SMARTCLOUD_RAG_RERANK_SCORE_WEIGHT`: base candidate score weight. Default `0.68`.
- `SMARTCLOUD_RAG_RERANK_DENSITY_WEIGHT`: token-density weight. Default `0.22`.
- `SMARTCLOUD_RAG_RERANK_KEYWORD_WEIGHT`: keyword-hit weight. Default `0.1`.
- `SMARTCLOUD_RAG_RERANK_TITLE_BOOST`: title-match boost. Default `0.1`.
- `SMARTCLOUD_RAG_RERANK_SOURCE_TYPE_BOOST`: knowledge-domain/source-type boost when query terms match billing/product/icp/marketing/research domains. Default `0.08`.
- `SMARTCLOUD_RAG_RERANK_RECENCY_BOOST`: recency boost for chunks created within the last 30 days. Default `0.05`.
- `SMARTCLOUD_RAG_MIN_RERANK_SCORE`: minimum rerank score required before a citation enters the response. Default `0.2`.
- `SMARTCLOUD_RAG_CACHE_NAMESPACE`: defaults to `smartcloud:rag:l1`, aligning the generated cache keys to `smartcloud:rag:l1:{query_hash}`.

## Cache behavior
- Retrieval cache keys now use the documented hash pattern: `smartcloud:rag:l1:{query_hash}`.
- Cache key inputs cover query, topK, filters, and conversation context; raw query text is not exposed in the key.
- `GET /healthz` now reports `cacheHitRate`, `cacheSize`, and `lastPruneTime` in addition to the detailed cache object.
- `DELETE /api/rag/v1/cache` clears the internal retrieval cache for knowledge-change invalidation.
- `POST /api/v1/admin/cache/clear` provides manual operator invalidation.
- `/metrics` exports `rag_cache_hit_ratio`.

## Run
```bash
cd apps/rag-service
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8040
```

## Notes
- This service still depends on `knowledge-service` search APIs rather than a direct vector database, which preserves the frozen cross-service contract.
- When `SMARTCLOUD_REDIS_URL` is configured, the retrieval cache stores serialized results in Redis with TTL semantics and keeps an in-process fallback copy so cache reads remain available during Redis hiccups.
- `GET /healthz` reports `ready=false` plus upstream probe details when `knowledge-service` is unreachable or not ready, and now surfaces cache invalidation/usage stats for operators.
- Incoming request, trace, tenant, and conversation headers are forwarded to `knowledge-service` to preserve shared contract context.
- `SMARTCLOUD_TRACE_ENABLED=true` plus `OTEL_EXPORTER_OTLP_ENDPOINT` enables Phoenix-compatible OTLP tracing for request spans, retrieval child spans, and outbound knowledge-service search spans; `/healthz` and `/metrics` are excluded to avoid collector noise.
- `POST /api/rag/v1/diagnose` is intended for operators and the admin console so retrieval quality can be inspected before a live orchestrator handoff is wired.
- `POST /api/v1/admin/retrieval/diagnostics` wraps the same diagnostic engine in the canonical admin envelope required by the frozen admin placeholder contract.
- Diagnostic responses include `queryTerms`, `unmatchedTerms`, `sourceBreakdown`, `tagBreakdown`, and `backendUsed` so operators can see why a query underperformed without reading raw service logs.
- Retrieval latency is recorded from the shared candidate-search path, so the Prometheus histogram covers `/retrieve`, `/diagnose`, `/context`, and `/answer` traffic instead of only the thin retrieve wrapper.

## Known limitations
- no ML rerank; scoring remains deterministic rule-based logic
- no direct Qdrant/OpenSearch access from rag-service
- no streaming retrieval pipeline
- agent-specific knowledge-base routing is still keyword/domain inferred in rerank only, not a hard router to distinct knowledge-service indices
