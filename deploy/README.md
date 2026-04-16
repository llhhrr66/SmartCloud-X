# Deploy Baseline

This directory contains the first runnable deployment baseline for the owned SmartCloud-X knowledge and RAG surfaces.

## Included
- `docker-compose/docker-compose.yml`: local stack for knowledge-service, a dedicated knowledge-indexer worker, rag-service, web-admin, Redis, MySQL, Qdrant, OpenSearch, MinIO, Phoenix, Prometheus, Grafana, and cAdvisor
- `docker-compose/.env.example`: local stack variables, including active connector wiring for MinIO/MySQL/Qdrant/OpenSearch/Redis plus Phoenix and LangSmith placeholders
- `docker-compose/smoke-test.py`: reusable smoke validation for readiness-aware health checks, web-admin SPA serving, RAG capabilities, starter seeding, filesystem import preview/import, knowledge runtime snapshot export, connector configuration visibility, snapshot/profile consistency, MySQL/Qdrant/OpenSearch/Redis backend intent, completed indexing-worker connector steps, admin knowledge-base create/update/document/reindex flows, admin document detail + job lookup, admin audit inspection, overview, direct knowledge search, diagnose, answer plus empty-result answer flows, readiness/inventory gauge exposure on `/metrics`, and standard trace/response headers
- `docker-compose/trace-smoke.py`: QA-style OTLP smoke script that runs local knowledge-service, the knowledge indexing worker, and rag-service against a temporary collector and asserts spans are actually exported, tagged with both service names, and share propagated trace IDs after ingestion, snapshot export, worker processing, and answer flows
- `k8s/README.md`: next-step notes for a Kubernetes migration
- Prometheus alert placeholders plus configurable browser and frontend build endpoints

## Start
```bash
cp deploy/docker-compose/.env.example deploy/docker-compose/.env
docker compose -f deploy/docker-compose/docker-compose.yml up --build
python3 deploy/docker-compose/smoke-test.py
python3 deploy/docker-compose/trace-smoke.py
```

## Key variables
- `SMARTCLOUD_CORS_ALLOWED_ORIGINS`: browser origins allowed to call `knowledge-service` and `rag-service`
- `SMARTCLOUD_TRACE_ENABLED`: explicit switch for OTLP tracing inside `knowledge-service` and `rag-service`; compose defaults it to `true`
- `SMARTCLOUD_OPERATOR_REASON_HEADER`: shared admin-write audit header name consumed by `knowledge-service` and the compose smoke test
- `SMARTCLOUD_KNOWLEDGE_DATA_PATH`: compose-only runtime path for the persisted knowledge JSON store so the baked starter catalog is not hidden by the mounted volume
- `SMARTCLOUD_KNOWLEDGE_AUDIT_PATH`: compose-only runtime path for the knowledge-service admin audit log
- `SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH` / `SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT`: compose-visible runtime paths for persisted async indexing events and raw mirror files
- `SMARTCLOUD_MINIO_ACCESS_KEY` / `SMARTCLOUD_MINIO_SECRET_KEY`: credentials passed to the knowledge-indexer worker so raw mirrors are uploaded into MinIO instead of staying local-only
- `SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT`: compose-visible import directory consumed by `GET /api/knowledge/v1/imports:preview` and `POST /api/knowledge/v1/files:ingest`
- `SMARTCLOUD_MINIO_ENDPOINT` / `SMARTCLOUD_MINIO_BUCKET`: raw object mirror target advertised by `knowledge-service` integration snapshots
- `SMARTCLOUD_MYSQL_DSN`: metadata-store target used for knowledge runtime metadata and advertised by `knowledge-service` integration snapshots
- `SMARTCLOUD_QDRANT_URL` / `SMARTCLOUD_QDRANT_VECTOR_SIZE` / `SMARTCLOUD_OPENSEARCH_URL`: vector and BM25 targets advertised by `knowledge-service` integration snapshots and consumed by the knowledge-indexer worker
- `SMARTCLOUD_REDIS_URL` / `SMARTCLOUD_RAG_REDIS_URL`: Redis wiring used for the knowledge active queue path, worker completion fan-out, and the RAG retrieval cache in the local stack
- `SMARTCLOUD_CONNECTOR_TIMEOUT_MS` / `SMARTCLOUD_INDEX_WORKER_POLL_SECONDS` / `SMARTCLOUD_INDEX_WORKER_BATCH_SIZE`: worker tuning knobs for connector request deadlines, idle polling, and per-batch drain size
- `SMARTCLOUD_PHOENIX_COLLECTOR_ENDPOINT`: Phoenix OTLP collector endpoint passed through to both backend services
- `OTEL_EXPORTER_OTLP_ENDPOINT` / `OTEL_EXPORTER_OTLP_PROTOCOL`: standard OpenTelemetry export settings passed through to `knowledge-service` and `rag-service`
- `LANGSMITH_TRACING` / `LANGSMITH_ENDPOINT` / `LANGSMITH_PROJECT` / `LANGSMITH_API_KEY`: reserved LangSmith tracing placeholders passed through to the backend services
- `VITE_KNOWLEDGE_SERVICE_BASE_URL`: build-time API base URL baked into `web-admin`
- `VITE_RAG_SERVICE_BASE_URL`: build-time API base URL baked into `web-admin`
- `VITE_OPERATOR_REASON_HEADER`: build-time admin write header name baked into `web-admin`; keep it aligned with `SMARTCLOUD_OPERATOR_REASON_HEADER`
- `SMARTCLOUD_SMOKE_TIMEOUT_SECONDS`: optional timeout override for `smoke-test.py`
- `SMARTCLOUD_SMOKE_WAIT_ATTEMPTS` / `SMARTCLOUD_SMOKE_WAIT_SECONDS`: optional health retry tuning for `smoke-test.py`

## Persistence notes
- `knowledge_runtime` persists the writable knowledge JSON store at the compose runtime path.
- `knowledge_runtime` also persists the admin audit log so KB creation and reindex events survive local restarts.
- `knowledge_runtime` also persists the async indexing outbox and raw mirrored source files used by the connector staging baseline.
- the `knowledge-indexer` service drains that persisted outbox and writes connector results back into the same event records, so snapshot exports and `web-admin` can show completed versus failed connector steps.
- when Redis is configured, the JSONL outbox acts as an auditable event log while Redis pending/processing lists carry the active queue lifecycle.
- `../../apps/knowledge-service/data/imports` is mounted read-only into the compose knowledge-service container at `/app/imports` for starter batch-import scenarios.
- `prometheus_data` persists scraped time-series data across local restarts.
- `grafana_data` persists local admin credentials and dashboard state across local restarts.
- `mysql_data`, `qdrant_data`, `opensearch_data`, and `minio_data` persist connector-local state for the owned retrieval/indexing baseline.

## Readiness behavior
- Compose healthchecks now require `GET /healthz` to report `data.ready=true`, not just return HTTP 200.
- `knowledge-service` readiness covers repository access, audit-log parent writability, starter catalog presence, and import-root readability.
- `rag-service` readiness covers a live upstream probe to `knowledge-service`, so a running container is still marked unhealthy until retrieval dependencies are actually usable.
- Prometheus scrapes now also refresh readiness gauges on `/metrics`, so Grafana and alert rules can detect “running but not usable” states without a separate JSON health poller.
- Phoenix now receives OTLP spans for request, ingestion, indexing-worker connector processing, retrieval, and answer flows when `SMARTCLOUD_TRACE_ENABLED=true`; `healthz` and `metrics` traffic stay excluded so the UI focuses on operator and retrieval behavior instead of probes.
- `trace-smoke.py` gives operators a fast QA loop for OTLP export itself when they want stronger tracing validation than config inspection or the standard compose smoke run; it now checks the snapshot-export span and worker span as well as both service identities and cross-service trace propagation, not just batch counts.
- `smoke-test.py` now also fails if snapshot-exported KB/document profile rows drift from the admin/runtime state it just wrote, which keeps the migration path honest when MySQL metadata becomes authoritative.

## Default endpoints
- Web admin: `http://localhost:8050`
- Knowledge service: `http://localhost:8030`
- RAG service: `http://localhost:8040`
- Phoenix: `http://localhost:6006`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`
- MinIO console: `http://localhost:9001`
