# Supervisor Foundation Status

## Status
- phase: completed-solid-baseline
- updated at: 2026-04-16T22:47:14+08:00
- owned scope: `packages/common/`, `packages/common-schemas/`, `packages/common-auth/`, `docs/contracts/`, `openapi/`, `.env.example`, and root engineering scaffolding
- pending before final signoff: no active owned-scope blockers; continue monitoring for newly filed frozen-space change requests

## This pass completed
- reserved shared root connector keys for `SMARTCLOUD_MYSQL_DSN`, `SMARTCLOUD_REDIS_URL`, and shared `SMARTCLOUD_MINIO_*` raw-object storage settings in `.env.example`, `@smartcloud-x/common`, and shared runtime docs
- added `docs/contracts/shared/persistence-backends.md` as the frozen service-by-service backend matrix covering authoritative backends, local-only fallbacks, restart durability expectations, evidence sources, and release guidance
- added `docs/contracts/shared/runtime-health.md` and aligned auth/marketing/research OpenAPI health descriptions so current liveness-only routes are explicit while future backend-evidence field names are now frozen
- promoted shared `RuntimeHealthStatus`, `RuntimeReadinessStatus`, and `RuntimeDependencyReadiness` schemas plus `/readyz` OpenAPI coverage for orchestrator, tool-hub, and business-tools, including nested downstream `dependencyReadiness` examples
- promoted stored chat stream replay baselines: reusable stream replay record/page schemas, orchestrator message-event replay/list routes, and shared `CHAT_STREAM_EVENTS_NOT_FOUND` error code/export coverage
- documented the owner-local but cross-service `BUSINESS_TOOLS_REDIS_NAMESPACE` alignment rule for degraded/local business-tools Redis keyspace reuse
- recorded explicit partial defers for:
  - auth/marketing/research response-level backend-health payloads until owners publish them
  - frontend-sdk-owned `GET /api/v1/icp/applications` contract promotion until a backend-owned frozen service contract exists

## Shared baselines now available
- shared persistence/runtime config:
  - `SMARTCLOUD_MYSQL_DSN`
  - `SMARTCLOUD_REDIS_URL`
  - `SMARTCLOUD_MINIO_ENDPOINT`
  - `SMARTCLOUD_MINIO_BUCKET`
  - `SMARTCLOUD_MINIO_ACCESS_KEY`
  - `SMARTCLOUD_MINIO_SECRET_KEY`
- shared docs:
  - `docs/contracts/shared/persistence-backends.md`
  - `docs/contracts/shared/runtime-health.md`
- shared schemas/components:
  - `RuntimeDependencyReadiness`
  - `RuntimeHealthStatus`
  - `RuntimeReadinessStatus`
  - `StreamEventRecord`
  - `StreamEventPage`
- OpenAPI route coverage:
  - `GET /readyz` in orchestrator, tool-hub, and business-tools baselines
  - `GET /api/v1/chat/sessions/{conversation_id}/messages/{message_id}/events`
  - `GET /api/v1/chat/sessions/{conversation_id}/messages/{message_id}/events/stream`

## Validation
- `python3 scripts/validate_foundation.py`
- `bash scripts/check_foundation_done.sh`
- `python3 -m py_compile scripts/validate_foundation.py`
- direct YAML parse of `openapi/*.yaml`
- targeted persistence/readiness/replay drift check covering:
  - shared MySQL/Redis/MinIO connector key publication
  - `CHAT_STREAM_EVENTS_NOT_FOUND` catalog/export sync
  - orchestrator stream replay routes
  - orchestrator/tool-hub/business-tools `/readyz` coverage

## Self-review
- completed on 2026-04-16
- fixes made during review:
  - validator review caught a missing foundation-baseline marker string after the persistence-matrix promotion; corrected the doc wording and revalidated
  - validator review surfaced the newly filed runtime-readiness-health request during this pass, so the readiness baseline was promoted before final signoff instead of being left as a stale governance marker
