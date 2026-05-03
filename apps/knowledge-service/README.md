# Knowledge Service Baseline

FastAPI-based knowledge ingestion service for SmartCloud-X.

## Scope
- source registration and local catalog persistence
- text document ingestion with chunking, duplicate protection, and upgraded text processing
- starter catalog bootstrap for immediate admin and RAG validation
- filesystem batch-import preview and ingestion for mounted markdown/text starter corpora
- catalog overview API for operator inventory, top-tag tracking, recent-ingestion review, document-language coverage, and largest-source snapshots
- search API for RAG consumers and admin preview flows, including query-token, source-breakdown, tag-breakdown, and backend-used metadata
- admin `/api/v1/admin/**` baseline for knowledge-base listing/create/update, document creation, chunk preview, search preview, and confirm-token-gated reindex operations
- owner-local object-storage upload lifecycle for admin knowledge documents (`upload init -> upload content -> upload complete`)
- admin document detail and async-job lookup routes so operators can inspect token/chunk stats plus latest create/reindex job state without opening runtime files
- service-local admin audit log persisted beside the runtime JSON store
- owner-local audit inspection route for recent admin write events
- async indexing outbox lifecycle scaffolding with queued/processing/failed/completed state persisted beside the runtime store; this is service-local failure recovery for knowledge indexing, not a cross-service Saga coordinator
- MySQL-backed runtime metadata mirror for knowledge-base profiles, document profiles, and admin async jobs, with local JSON retained as a migration-safety fallback
- a practical `app.worker` indexing worker that drains the outbox into MinIO, MySQL, Qdrant, OpenSearch, and Redis when those connectors are configured
- live-search preference for OpenSearch BM25 and Qdrant vector hits when those backends are configured, with deterministic local keyword fallback for cold or degraded environments
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
- `GET /api/knowledge/v1/embedding:test`
- `GET /api/v1/admin/knowledge-bases`
- `POST /api/v1/admin/knowledge-bases`
- `PATCH /api/v1/admin/knowledge-bases/{kb_id}`
- `GET /api/v1/admin/knowledge-bases/{kb_id}/documents`
- `POST /api/v1/admin/knowledge-bases/{kb_id}/documents`
- `POST /api/v1/admin/files/uploads`
- `PUT /api/v1/admin/files/uploads/{upload_id}/content`
- `POST /api/v1/admin/files/uploads/{upload_id}:complete`
- `GET /api/v1/admin/knowledge-documents/{doc_id}`
- `GET /api/v1/admin/knowledge-documents/{doc_id}/chunks`
- `POST /api/v1/admin/knowledge-documents/{doc_id}/reindex`
- `GET /api/v1/admin/jobs/{job_id}`
- `POST /api/v1/admin/retrieval/search-preview`
- `POST /api/v1/admin/dify/datasets/sync/{kb_id}`
- `POST /retrieval` (Dify external knowledge adapter)

## Run
```bash
cd apps/knowledge-service
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8030
```

## Notes
- Embedding strategy:
  - default is `hash-baseline`, still fully offline and deterministic
  - optional `openai-compatible` mode is enabled by `SMARTCLOUD_EMBEDDING_PROVIDER=openai-compatible` together with `SMARTCLOUD_EMBEDDING_API_URL`, `SMARTCLOUD_EMBEDDING_API_KEY`, and `SMARTCLOUD_EMBEDDING_MODEL`
  - `GET /api/knowledge/v1/embedding:test?text=...` returns the active provider plus a sample vector preview
- Text processing pipeline is now `clean -> metadata extract -> chunk -> keyword extract -> embed -> persist/index`.
- Cleaning normalizes whitespace, strips markdown headers/links while preserving content, removes zero-width characters, and normalizes common CJK punctuation.
- Metadata extraction adds `language`, `domainHints`, `entityMentions`, and `estimatedReadingMinutes` onto chunk metadata.
- Chunking strategy is configurable with `SMARTCLOUD_CHUNK_STRATEGY=fixed|paragraph`; paragraph mode first splits on blank lines / markdown headers / horizontal rules, then falls back to bounded character windows.
- Ingestion responses now expose `avgChunkTokens`, `maxChunkTokens`, and `minChunkTokens` for chunk quality inspection.
- Token estimation now uses a mixed heuristic: about `1.5` tokens per CJK char and `1` token per English word, instead of raw `len(content)//4`.
- Search backend priority and score merge:
  - local fallback stays enabled
  - remote BM25/vector merge uses configurable weights `SMARTCLOUD_SEARCH_REMOTE_WEIGHT` and `SMARTCLOUD_SEARCH_LEXICAL_WEIGHT`
  - score floor is controlled by `SMARTCLOUD_SEARCH_MIN_SCORE`
  - response now includes `backendUsed` (`local-keyword`, `opensearch-only`, `qdrant-only`, `hybrid-live-backends`)
- `SMARTCLOUD_MINIO_ACCESS_KEY` and `SMARTCLOUD_MINIO_SECRET_KEY` let the worker upload raw mirrors into MinIO; snapshot/export payloads now treat the MinIO bucket/object key as the formal raw-object target while retaining a local mirror for migration safety.
- `SMARTCLOUD_CONNECTOR_TIMEOUT_MS`, `SMARTCLOUD_QDRANT_VECTOR_SIZE`, `SMARTCLOUD_INDEX_WORKER_POLL_SECONDS`, and `SMARTCLOUD_INDEX_WORKER_BATCH_SIZE` tune the connector-processing worker without code changes.
- `SMARTCLOUD_KNOWLEDGE_STARTER_CATALOG_PATH` lets operators swap in a different seed file when they need a service-local starter corpus.
- `SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT` lets operators point filesystem imports at a different mounted directory.
- `SMARTCLOUD_OPERATOR_REASON_HEADER` lets operators rename the required admin write audit header without editing service code; admin routes default to `X-Operator-Reason`.
- `SMARTCLOUD_TRACE_ENABLED=true` plus `OTEL_EXPORTER_OTLP_ENDPOINT` enables Phoenix-compatible OTLP tracing for request spans and ingestion/search child spans; `/healthz` and `/metrics` are intentionally excluded to keep collector noise low.
- `SMARTCLOUD_DIFY_EXTERNAL_KNOWLEDGE_API_KEY` enables the owner-local Dify External Knowledge adapter on `POST /retrieval`. When absent, the adapter is disabled instead of pretending to succeed.
- `SMARTCLOUD_DIFY_DATASET_API_BASE_URL` + `SMARTCLOUD_DIFY_DATASET_API_KEY` + `SMARTCLOUD_DIFY_DATASET_ID` enable the dataset push/sync path on `POST /api/v1/admin/dify/datasets/sync/{kb_id}`.
- Filesystem import requests must keep both `directory` and `glob` inside `SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT`; parent-traversal, absolute, drive-prefixed, and out-of-root resolved matches are rejected.
- Known limitations:
  - default embedding remains hash-based unless an external embedding API is configured
  - Qdrant still uses a single configured collection and OpenSearch still uses a single configured index, not the per-domain collections/indices from the design doc yet
  - Redis namespace/key layout still follows service-local conventions rather than the exact doc 10.3 prefixes
  - indexing outbox / retry path covers service-local ingestion recovery only; cross-service Saga compensation still requires orchestrator-side coordination and is not implemented inside knowledge-service
- Validation commands:
  - `PYTHONPATH="/home/ljr/SmartCloud-X/apps/knowledge-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" /home/ljr/SmartCloud-X/.venv/bin/pytest /home/ljr/SmartCloud-X/apps/knowledge-service/tests/test_ingestion.py -q`
  - `cd /home/ljr/SmartCloud-X && /home/ljr/SmartCloud-X/.venv/bin/python -m compileall apps/knowledge-service/app`
  - `cd /home/ljr/SmartCloud-X && uv run --with-requirements apps/knowledge-service/requirements.txt --with httpx --with pytest python -m pytest apps/knowledge-service/tests apps/rag-service/tests -q`
