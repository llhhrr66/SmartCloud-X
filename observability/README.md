# Observability Baseline

This directory holds the first monitoring and tracing placeholders for the knowledge and RAG surfaces.

## Included
- Prometheus scrape config for the owned FastAPI services and cAdvisor
- Prometheus alert placeholders for service-down, upstream-error, elevated upstream-error-rate, filesystem-import-failure detection, and rejected admin reindex attempts
- Grafana provisioning plus a starter dashboard with activity, availability, latency, degradation, retrieval-quality, filesystem-import, and admin-operations panels
- Phoenix notes for the active OTLP tracing baseline emitted by `knowledge-service` and `rag-service`
- deployable QA trace smoke notes for asserting OTLP export itself, not just env/config presence
- LangSmith placeholder notes for future evaluation and trace export wiring
- readiness-aware deploy notes so operators can pair `/healthz` diagnostics with Prometheus/Grafana metrics during local bring-up

## Service metrics
- `knowledge_ingestions_total`
- `knowledge_chunks_created_total`
- `knowledge_search_requests_total`
- `knowledge_bootstrap_runs_total`
- `knowledge_duplicate_documents_total`
- `knowledge_file_import_runs_total`
- `knowledge_file_import_files_total`
- `knowledge_file_import_failures_total`
- `knowledge_admin_write_requests_total{action,outcome}`
- `knowledge_admin_audit_records_total`
- `knowledge_document_reindexes_total{outcome}`
- `knowledge_index_worker_runs_total{outcome}`
- `knowledge_index_connector_writes_total{connector,outcome}`
- `knowledge_readiness_state`
- `knowledge_readiness_check_state{check_name}`
- `knowledge_health_warning_count`
- `knowledge_catalog_entity_count{entity}`
- `rag_retrieval_requests_total`
- `rag_retrieval_duration_seconds`
- `rag_answer_requests_total`
- `rag_empty_retrievals_total`
- `rag_degraded_retrievals_total`
- `rag_upstream_errors_total`
- `rag_readiness_state`
- `rag_upstream_reachable_state`
- `rag_upstream_ready_state`
- `rag_upstream_probe_latency_ms`
- `rag_health_warning_count`
- `rag_cache_backend_errors_total{operation}`

## Practical operator path
1. start the local stack with `docker compose -f deploy/docker-compose/docker-compose.yml up --build`
2. run `python3 deploy/docker-compose/smoke-test.py`
3. inspect Prometheus at `http://localhost:9090` and Grafana at `http://localhost:3000`
4. use the admin knowledge-base create/reindex controls, preview-file admin document creation, audit-trail panel, filesystem preview/import, direct knowledge search, canonical admin retrieval preview/diagnostics, and `POST /api/rag/v1/diagnose` flows in `web-admin` to compare UI behavior against the metrics panels

When services stay unhealthy in Compose, check the enriched `/healthz` payloads first: `knowledge-service` now reports which local runtime asset is missing, and `rag-service` reports whether its upstream `knowledge-service` probe is reachable and ready. That shortens the path from “container is restarting” to the actual config or mount issue before you move on to Prometheus or Grafana.

Prometheus can now observe those same readiness states directly through gauges exported on `/metrics`, which keeps the placeholder baseline useful even when operators only have Grafana/alerts in front of them. `knowledge_readiness_state` and `rag_readiness_state` distinguish “process is up” from “baseline is usable,” while `knowledge_catalog_entity_count{entity=...}` and `rag_upstream_probe_latency_ms` make starter-catalog seeding and upstream health drift visible without opening a service shell.

The retrieval latency metric is recorded by the shared RAG candidate-search path, so `/api/rag/v1/retrieve`, `/api/rag/v1/diagnose`, and `/api/rag/v1/answer` all contribute to the dashboard timing panels. Empty-result and degraded-result counters remain exposed so operators can distinguish knowledge gaps from simple transport errors. The new filesystem-import metrics make it easy to tell whether a batch seed run failed before retrieval quality regressed.

The admin-write metrics let operators distinguish intentional KB/document maintenance activity from background seed runs. Audit-record counts should move in lockstep with successful admin writes, including the new knowledge-base update path used by `web-admin` for status / retrieval-mode tuning, while `knowledge_document_reindexes_total{outcome="rejected"}` highlights confirm-token mistakes or unsafe manual reindex attempts. The new admin document detail + job lookup flow complements those counters by letting operators confirm which create/reindex job most recently touched a document before opening Prometheus or Grafana.

The compose smoke test now asserts that key knowledge and RAG metrics are actually exposed on `/metrics`, which keeps the observability placeholder baseline honest even before Alertmanager, OTLP spans, or LangSmith-backed evaluations are fully wired.

The backend services now also emit OTLP spans to Phoenix-compatible collectors for request handling plus key child operations such as ingestion, filesystem import, indexing-worker connector processing, retrieval candidate search, upstream knowledge-service fetches, and answer composition. Health and metrics routes are excluded from tracing on purpose so the Phoenix view stays focused on operator and retrieval flows instead of scrape noise.

When operators need a stronger tracing check than “the env vars are present,” run `python3 deploy/docker-compose/trace-smoke.py`. It launches temporary local knowledge-service, knowledge-indexer, and rag-service processes against a throwaway OTLP collector, exercises ingestion plus worker processing plus answer traffic, and fails fast if OTLP batches are missing, either backend service is absent from the exported spans, the worker span is missing, or the rag-to-knowledge handoff does not preserve a shared trace ID.
