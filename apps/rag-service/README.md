# RAG Service Baseline

FastAPI-based retrieval service for SmartCloud-X.

## Scope
- query rewrite and hybrid-style reranking over `knowledge-service` results
- retrieval endpoint with citations and coverage notes
- diagnostics endpoint for rewrite, filters, candidate counts, grounded citations, source/tag coverage, and unmatched-term inspection
- admin diagnostics endpoint under `/api/v1/admin/retrieval/diagnostics` with canonical external envelopes for the admin console and future gateway proxying
- answer composition endpoint without external LLM dependency
- Prometheus metrics, request-context forwarding, standard trace/response headers, upstream degradation handling, empty/degraded retrieval quality counters, and an optional Redis-backed retrieval cache with local fallback
- OpenTelemetry spans for retrieval orchestration, upstream knowledge-service calls, and answer composition with OTLP export to Phoenix-compatible collectors when tracing is enabled
- readiness-aware health diagnostics with an active probe against `knowledge-service`
- readiness and upstream probe gauges on `/metrics` so Prometheus/Grafana can alert on degraded dependencies without scraping `/healthz` JSON
- browser-safe CORS defaults for `web-admin`

## Endpoints
- `GET /healthz`
- `GET /metrics`
- `GET /api/rag/v1/capabilities`
- `POST /api/rag/v1/retrieve`
- `POST /api/rag/v1/diagnose`
- `POST /api/rag/v1/answer`
- `POST /api/v1/admin/retrieval/diagnostics`

## Run
```bash
cd apps/rag-service
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8040
```

## Notes
- This baseline depends on `knowledge-service` search APIs rather than a vector database, which keeps local integration simple while preserving a future swappable retrieval layer.
- When `SMARTCLOUD_REDIS_URL` is configured, the retrieval cache now stores serialized results in Redis with TTL semantics and keeps an in-process fallback copy so cache reads remain available during Redis hiccups.
- `GET /healthz` now reports `ready=false` plus upstream probe details when `knowledge-service` is unreachable or not ready, which makes compose/runtime debugging faster than relying on process liveness alone.
- `/metrics` now refreshes and exports `rag_readiness_state`, `rag_upstream_reachable_state`, `rag_upstream_ready_state`, `rag_upstream_probe_latency_ms`, and `rag_health_warning_count` on every scrape.
- Incoming request, trace, tenant, and conversation headers are forwarded to `knowledge-service` to preserve shared contract context.
- `SMARTCLOUD_TRACE_ENABLED=true` plus `OTEL_EXPORTER_OTLP_ENDPOINT` enables Phoenix-compatible OTLP tracing for request spans, retrieval child spans, and outbound knowledge-service search spans; `/healthz` and `/metrics` are excluded to avoid collector noise.
- `POST /api/rag/v1/diagnose` is intended for operators and the admin console so retrieval quality can be inspected before a live orchestrator handoff is wired.
- `POST /api/v1/admin/retrieval/diagnostics` wraps the same diagnostic engine in the canonical admin envelope required by the frozen admin placeholder contract.
- Diagnostic responses include `queryTerms`, `unmatchedTerms`, `sourceBreakdown`, and `tagBreakdown` so operators can see why a query underperformed without reading raw service logs.
- Retrieval latency is recorded from the shared candidate-search path, so the Prometheus histogram covers `/retrieve`, `/diagnose`, and `/answer` traffic instead of only the thin retrieve wrapper.
- Outbound knowledge-service calls now inject W3C trace context in addition to the existing SmartCloud headers, so Phoenix can render the cross-service retrieval path without changing the shared header contract.
