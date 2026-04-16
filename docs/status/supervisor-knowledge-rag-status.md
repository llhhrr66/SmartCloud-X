# Supervisor Knowledge RAG Status

## Status
- phase: done
- updated at: 2026-04-16T14:28:01+08:00
- owned scope: `apps/knowledge-service/`, `apps/rag-service/`, `apps/web-admin/`, `deploy/`, `observability/`

## Completed
- hardened `knowledge-service` snapshot/export consistency again by merging duplicate legacy KB/document profiles without losing informative `file_id`, `source_type`, or `source_uri` fields, while still pruning orphaned runtime state and keeping exported counts aligned.
- added a practical `knowledge-indexer` worker in owned scope. It now drains queued outbox events into MinIO raw-object upload, MySQL metadata upsert, Qdrant vector upsert, OpenSearch BM25 upsert, and Redis completion notification flows, then persists per-connector results back onto the event.
- upgraded `rag-service` retrieval caching to use Redis TTL storage when configured, with in-process fallback so degraded Redis does not break retrieval.
- updated compose, smoke, and observability artifacts so the owned baseline actually runs the worker, waits for completed connector steps in smoke validation, and alerts on worker or connector failures.
- strengthened `deploy/docker-compose/trace-smoke.py` so OTLP QA now covers the worker span as well as both backend services and the shared rag-to-knowledge trace id.

## Self-review
- reviewed the new reconciliation, worker, Redis-cache, and QA wiring end to end after implementation.
- found and fixed one issue in this pass:
- the first worker implementation read `source_type/source_uri` only from the document-profile row, but admin/file-backed ingests enqueue before that profile is persisted.
- fixed it by preferring the outbox event’s raw-object metadata during connector writes, which preserves the real filesystem source fields even under async timing.

## Current verification
- passed: `/home/ljr/SmartCloud-X/.venv/bin/pip install -r /home/ljr/SmartCloud-X/apps/knowledge-service/requirements.txt -r /home/ljr/SmartCloud-X/apps/rag-service/requirements.txt`
- passed: `python3 -m py_compile /home/ljr/SmartCloud-X/apps/knowledge-service/app/services/store.py /home/ljr/SmartCloud-X/apps/knowledge-service/app/services/indexing_worker.py /home/ljr/SmartCloud-X/apps/knowledge-service/app/worker.py /home/ljr/SmartCloud-X/apps/rag-service/app/services/cache.py /home/ljr/SmartCloud-X/deploy/docker-compose/smoke-test.py /home/ljr/SmartCloud-X/deploy/docker-compose/trace-smoke.py`
- passed: `/home/ljr/SmartCloud-X/.venv/bin/pytest -q /home/ljr/SmartCloud-X/apps/knowledge-service/tests /home/ljr/SmartCloud-X/apps/rag-service/tests`
- passed: `SMARTCLOUD_TRACE_SMOKE_PYTHON=/home/ljr/SmartCloud-X/.venv/bin/python /home/ljr/SmartCloud-X/.venv/bin/python /home/ljr/SmartCloud-X/deploy/docker-compose/trace-smoke.py`
- passed: `docker compose -f /home/ljr/SmartCloud-X/deploy/docker-compose/docker-compose.yml config`
- passed: `npm run build` in `/home/ljr/SmartCloud-X/apps/web-admin`
- passed: `python3` YAML parse for `/home/ljr/SmartCloud-X/observability/prometheus/alerts.yml` and `/home/ljr/SmartCloud-X/observability/prometheus/prometheus.yml`

## Blockers
- none active inside owned directories.
- non-blocking follow-up: frozen promotion for `PATCH /api/v1/admin/knowledge-bases/{kb_id}` is still pending in `docs/contracts/change-requests/2026-04-16-admin-kb-update-promotion.md`.

## Integration points
- `knowledge-service` snapshot exports now expose connector step results on `integrations.recentEvents[*].connectorResults`, so `web-admin` and compose smoke can distinguish queued, failed, and fully-synchronized indexing events.
- the new `knowledge-indexer` worker consumes the same runtime outbox already written by ingestion/reindex flows and fans it out to MinIO, MySQL, Qdrant, OpenSearch, and Redis without changing the public/admin API surface.
- `rag-service` now uses Redis as the primary retrieval cache backend when configured in compose, while preserving local fallback behavior during Redis failures.
- `deploy/docker-compose/trace-smoke.py` now exercises ingestion, worker processing, and rag answer flows together and proves that Phoenix-compatible collectors receive spans from both services plus the worker span under the propagated trace.

## Residual risks
- knowledge persistence and admin job state still use local JSON as the source of truth; MySQL/Qdrant/OpenSearch are now downstream synchronization targets rather than authoritative storage.
- the indexing queue itself is still JSONL-backed with retry markers; Redis is used for completion notification and cache wiring, not yet as the sole durable work queue.
- admin document creation remains file-backed through the configured import root rather than shared upload-policy/object-storage flows.
- admin write flows remain local-operator friendly but are not yet wired to shared auth/RBAC enforcement beyond operator-reason and confirm-token checks.
- the KB PATCH route is implemented in owned code today, but the frozen admin contract/OpenAPI still need the follow-up promotion request listed above.
