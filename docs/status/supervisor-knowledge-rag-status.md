# Supervisor Knowledge RAG Status

## Status
- phase: done
- updated at: 2026-04-16T22:45:41+08:00
- owned scope: `apps/knowledge-service/`, `apps/rag-service/`, `apps/web-admin/`, `deploy/`, `observability/`
- run focus completed: snapshot/export authority hardening, export/degraded-path QA coverage, and trace verification refresh

## Completed in this run
- made `knowledge-service` snapshot export refresh MySQL-backed KB/document/admin metadata before repository reconciliation, so stale local JSON profile blobs no longer overwrite the exported admin/runtime view.
- fixed repository reconciliation so `documentProfiles[].latest_job_id` preserves the newer authoritative job reference instead of blindly falling back to an older local ingestion job.
- added knowledge-service regressions for conflicting local JSON drift, snapshot refresh from authoritative metadata, and snapshot OTLP span export.
- added a rag-service route-level empty-result answer regression and extended `deploy/docker-compose/smoke-test.py` to assert snapshot KB/document-profile consistency plus the live empty-result answer path.
- refreshed owned README guidance to describe the stronger MySQL-authority and QA behavior.

## Self-review
- reviewed the new metadata-refresh path, document-profile reconciliation, and QA assertions end to end.
- found and fixed two issues during review:
  - repository reconciliation was overwriting fresher authoritative `latest_job_id` values with older local ingestion ids; fixed by comparing candidate/admin-job timestamps before choosing the job id.
  - the first version of the new metadata-authority regressions depended on module reloads and collided with the global Prometheus registry during combined pytest; replaced that with instance-injected fake metadata backends.

## Current verification
- passed: `python3 -m py_compile apps/knowledge-service/app/services/metadata_backend.py apps/knowledge-service/app/services/store.py apps/knowledge-service/app/services/snapshot.py deploy/docker-compose/smoke-test.py`
- passed: `/home/ljr/SmartCloud-X/.venv/bin/pytest -q apps/knowledge-service/tests apps/rag-service/tests`
- passed: `SMARTCLOUD_TRACE_SMOKE_PYTHON=/home/ljr/SmartCloud-X/.venv/bin/python /home/ljr/SmartCloud-X/.venv/bin/python deploy/docker-compose/trace-smoke.py`
- passed: `docker compose -f deploy/docker-compose/docker-compose.yml config`
- not run in this pass: `deploy/docker-compose/smoke-test.py` against a live compose stack; the script itself was updated, but the stack was not started during this pass.

## Blockers
- none active inside owned directories.
- non-blocking follow-up remains the frozen promotion request for `PATCH /api/v1/admin/knowledge-bases/{kb_id}` in `docs/contracts/change-requests/2026-04-16-admin-kb-update-promotion.md`.

## Integration points
- `apps/knowledge-service/app/services/snapshot.py` now refreshes metadata from the MySQL-backed authority before export reconciliation.
- `apps/knowledge-service/app/services/store.py` now keeps authoritative document-profile job references when admin/profile metadata is newer than the local ingestion row.
- `deploy/docker-compose/smoke-test.py` now checks that snapshot-exported KB/document-profile state matches the just-written admin/runtime state and that the live empty-result answer path returns operator guidance without a degraded flag.
- `apps/rag-service/tests/test_retrieval.py` now locks in the empty-result answer behavior that the compose smoke path expects.

## Residual risks
- documents and chunks still persist primarily in the local runtime JSON store; this pass strengthened metadata authority but did not fully migrate the corpus store.
- the Redis queue path still uses simple list semantics with the JSONL outbox retained as the audit/recovery log, not a full broker/worker framework.
- admin document creation is still file-backed through the configured import root rather than shared upload-policy/object-storage contracts.
- admin/auth enforcement is still local-baseline only; shared auth/RBAC integration remains outside this run.
