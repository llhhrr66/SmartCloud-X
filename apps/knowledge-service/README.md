# Knowledge Service Baseline

FastAPI-based knowledge ingestion service for SmartCloud-X.

## Scope
- source registration and local catalog persistence
- text document ingestion with chunking, duplicate protection, and lightweight keyword extraction
- starter catalog bootstrap for immediate admin and RAG validation
- filesystem batch-import preview and ingestion for mounted markdown/text starter corpora
- catalog overview API for operator inventory, top-tag tracking, recent-ingestion review, document-language coverage, and largest-source snapshots
- search API for RAG consumers and admin preview flows, including query-token, source-breakdown, and tag-breakdown metadata
- admin `/api/v1/admin/**` baseline for knowledge-base listing/create/update, document creation, chunk preview, search preview, and confirm-token-gated reindex operations
- admin document detail and async-job lookup routes so operators can inspect token/chunk stats plus latest create/reindex job state without opening runtime files
- service-local admin audit log persisted beside the runtime JSON store
- owner-local audit inspection route for recent admin write events
- async indexing outbox lifecycle scaffolding with queued/processing/failed/completed state persisted beside the runtime store
- a practical `app.worker` indexing worker that drains the outbox into MinIO, MySQL, Qdrant, OpenSearch, and Redis when those connectors are configured
- Prometheus metrics and health endpoint
- readiness-aware health diagnostics for runtime store, audit path, starter catalog, and import-root availability
- readiness and inventory gauges on `/metrics` so Prometheus/Grafana can observe degraded local baselines without parsing `/healthz` JSON
- standard `X-Request-Id`, `X-Trace-Id`, `X-App-Name`, `X-App-Version`, and `X-Response-Time` headers on HTTP responses
- OpenTelemetry spans for ingestion, search, bootstrap, and filesystem-import flows with OTLP export to Phoenix-compatible collectors when tracing is enabled
- browser-safe CORS defaults for `web-admin`

## Endpoints
- `GET /healthz`
- `GET /metrics`
- `GET /api/knowledge/v1/sources`
- `POST /api/knowledge/v1/sources`
- `GET /api/knowledge/v1/documents`
- `GET /api/knowledge/v1/chunks`
- `GET /api/knowledge/v1/ingestions`
- `GET /api/knowledge/v1/overview`
- `GET /api/knowledge/v1/snapshot`
- `GET /api/knowledge/v1/admin/audit-records`
- `GET /api/knowledge/v1/imports:preview`
- `POST /api/knowledge/v1/documents:ingest`
- `POST /api/knowledge/v1/files:ingest`
- `POST /api/knowledge/v1/catalog:bootstrap`
- `POST /api/knowledge/v1/search`
- `GET /api/v1/admin/knowledge-bases`
- `POST /api/v1/admin/knowledge-bases`
- `PATCH /api/v1/admin/knowledge-bases/{kb_id}`
- `GET /api/v1/admin/knowledge-bases/{kb_id}/documents`
- `POST /api/v1/admin/knowledge-bases/{kb_id}/documents`
- `GET /api/v1/admin/knowledge-documents/{doc_id}`
- `GET /api/v1/admin/knowledge-documents/{doc_id}/chunks`
- `POST /api/v1/admin/knowledge-documents/{doc_id}/reindex`
- `GET /api/v1/admin/jobs/{job_id}`
- `POST /api/v1/admin/retrieval/search-preview`

## Run
```bash
cd apps/knowledge-service
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8030
```

## Notes
- `GET /healthz` now returns additive readiness diagnostics (`ready`, `readinessChecks`, `warnings`) so deploy probes and `web-admin` can tell the difference between a running process and a usable local ingestion environment.
- `/metrics` now refreshes and exports `knowledge_readiness_state`, `knowledge_readiness_check_state{check_name=...}`, `knowledge_health_warning_count`, and `knowledge_catalog_entity_count{entity=...}` for observability-friendly readiness and inventory tracking.
- The baseline uses a local JSON store at `data/knowledge-store.json`.
- A starter catalog lives at `data/starter-catalog.json` and can be loaded through `POST /api/knowledge/v1/catalog:bootstrap`.
- Filesystem starter docs live under `data/imports/`; the compose baseline mounts that directory into the running container and exposes it through `GET /api/knowledge/v1/imports:preview` and `POST /api/knowledge/v1/files:ingest`.
- `SMARTCLOUD_KNOWLEDGE_DATA_PATH` lets deploy/runtime environments persist the writable store outside the image without hiding the starter catalog asset.
- `SMARTCLOUD_KNOWLEDGE_AUDIT_PATH` lets operators persist the admin audit trail outside the image alongside the runtime store.
- `GET /api/knowledge/v1/admin/audit-records` exposes the recent admin audit trail with optional resource/action filters so `web-admin` can verify KB/document write activity without reading files directly.
- `PATCH /api/v1/admin/knowledge-bases/{kb_id}` lets operators rename a KB, tune `retrieval_mode`, and toggle `status` between `ready` and `disabled` while preserving an auditable before/after record in the runtime audit log.
- `GET /api/v1/admin/knowledge-documents/{doc_id}` returns the selected document read model together with chunk/token statistics and the latest async job id for operator drill-down.
- `GET /api/v1/admin/jobs/{job_id}` lets the admin console resolve the latest create/reindex job record returned by the document detail payload.
- `SMARTCLOUD_MINIO_ACCESS_KEY` and `SMARTCLOUD_MINIO_SECRET_KEY` let the worker upload raw mirrors into MinIO instead of only keeping the local mirror path.
- `SMARTCLOUD_CONNECTOR_TIMEOUT_MS`, `SMARTCLOUD_QDRANT_VECTOR_SIZE`, `SMARTCLOUD_INDEX_WORKER_POLL_SECONDS`, and `SMARTCLOUD_INDEX_WORKER_BATCH_SIZE` tune the connector-processing worker without code changes.
- `SMARTCLOUD_KNOWLEDGE_STARTER_CATALOG_PATH` lets operators swap in a different seed file when they need a service-local starter corpus.
- `SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT` lets operators point filesystem imports at a different mounted directory.
- `SMARTCLOUD_OPERATOR_REASON_HEADER` lets operators rename the required admin write audit header without editing service code; admin routes default to `X-Operator-Reason`.
- `SMARTCLOUD_TRACE_ENABLED=true` plus `OTEL_EXPORTER_OTLP_ENDPOINT` enables Phoenix-compatible OTLP tracing for request spans and ingestion/search child spans; `/healthz` and `/metrics` are intentionally excluded to keep collector noise low.
- Filesystem import requests must keep both `directory` and `glob` inside `SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT`; parent-traversal, absolute, drive-prefixed, and out-of-root resolved matches are rejected.
- `GET /api/knowledge/v1/overview` gives operators a quick inventory summary without requiring direct store access.
- `GET /api/knowledge/v1/snapshot` returns a portable JSON export of the current runtime state, including overview data, raw sources/documents/chunks, KB profiles, admin jobs, and recent audit records for debugging or handoff.
- snapshot export now reconciles missing KB/document profiles against the runtime store before building the payload, merges legacy duplicate profiles without dropping more informative file/source fields, and keeps exported outbox connector results aligned with the live runtime state.
- `GET /api/knowledge/v1/chunks?documentId=...` powers the admin chunk inspector so operators can validate chunk boundaries and extracted keywords after ingestion.
- `GET /api/knowledge/v1/imports:preview?directory=starter` lists candidate markdown/text files before an import run.
- Admin document create currently treats `file_id` as a relative path inside the configured import root, which keeps the baseline practical before object storage and async parsing jobs are introduced.
- Admin reindex returns an async-job-shaped record but performs the chunk rebuild immediately in the baseline so operators can validate chunk/output changes without a worker queue.
- Async indexing events are persisted in JSONL form with retry-friendly lifecycle fields (`queued`, `processing`, `failed`, `completed`) plus per-connector result records so operators can see which MinIO/MySQL/Qdrant/OpenSearch/Redis steps succeeded before reprocessing an event.
- `python -m app.worker --once` drains one batch of queued indexing work, while `python -m app.worker` runs the worker loop used by the compose baseline.
- Repeated ingestion of the same document under the same source reuses the existing record instead of inflating source counts.
- Search responses include query tokens plus source/tag breakdowns so operators can compare direct knowledge hits with `rag-service` diagnostics.
- The search implementation is intentionally simple and stable so `rag-service` can integrate before a vector database is introduced.
- When the request arrives from `rag-service` with W3C `traceparent`, the emitted knowledge-service spans join the same distributed trace while keeping the SmartCloud `X-Trace-Id` headers unchanged for local debugging.
