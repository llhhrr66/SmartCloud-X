# Shared Persistence Backend Baseline

This document freezes the current repo-wide persistence matrix used for infra migration, release decisions, and downstream QA reporting. It records repository reality first, including temporary local fallbacks.

## Shared connector-key status
- frozen root connector keys:
  - `SMARTCLOUD_MYSQL_DSN`
  - `SMARTCLOUD_REDIS_URL`
  - `SMARTCLOUD_MINIO_ENDPOINT`
  - `SMARTCLOUD_MINIO_BUCKET`
  - `SMARTCLOUD_MINIO_ACCESS_KEY`
  - `SMARTCLOUD_MINIO_SECRET_KEY`
- documented owner-local multi-service knob:
  - `BUSINESS_TOOLS_REDIS_NAMESPACE`
- documented owner-local retrieval/index connector keys:
  - `SMARTCLOUD_QDRANT_URL`
  - `SMARTCLOUD_OPENSEARCH_URL`
- not yet a frozen release dependency in repo reality:
  - MongoDB remains part of the primary target architecture, but no current repo-owned runtime path depends on it today

## Service matrix
| Service | Authoritative mainline backend(s) | Allowed local/degraded fallback | Restart durability expectation | Canonical evidence today | Release guidance |
| --- | --- | --- | --- | --- | --- |
| `auth-user-service` | MySQL-backed account and refresh-session runtime via `SMARTCLOUD_MYSQL_DSN` | SQLite/local file only for local smoke and tests | auth/session state must survive restart outside local smoke | owner-local restart smoke in `tests/integration/test_service_smoke.py`; response-level backend proof still pending | release promotion should require DB-backed runtime, not bootstrap-only assumptions |
| `orchestrator-service` | MySQL for conversation/session/config state; Redis for SSE replay, idempotency, and shared business-tools fallback cache alignment | JSON/file spools only for local smoke and degraded recovery | conversation state, continuation state, admin agent overrides, and replayable stream events should survive restart | current evidence is owner-local config/runtime tests plus frozen chat/session/event replay routes | release promotion should require both MySQL and Redis on the main path |
| `tool-hub-service` | MySQL-backed tool-call audit persistence; Redis-backed shared business-tools cache alignment | local JSON/in-memory fallback only for local smoke and degraded recovery | audit records and idempotent local fallback behavior should survive restart | current evidence is owner-local config/runtime tests plus frozen tool-call audit read contracts | release promotion should require MySQL-backed audit persistence; Redis remains required when shared local business-tools fallback is enabled |
| `business-tools-service` | Redis-backed idempotency and query-cache persistence via `SMARTCLOUD_REDIS_URL` | file-backed spools only for local smoke and degraded recovery | idempotency and cache namespaces should survive restart outside local smoke | current evidence is owner-local runtime tests and the published internal execute/preflight contracts | release promotion should require Redis-backed runtime state instead of file-only fallback |
| `knowledge-service` | MySQL metadata, MinIO raw-object mirrors, Qdrant vector index, OpenSearch keyword index, Redis coordination/cache | local JSON mirror remains a migration-safety fallback | KB/document metadata, raw objects, and index handoff state should survive restart | `GET /api/knowledge/v1/snapshot`, bootstrap/ingestion routes, and compose smoke provide response-level/runtime evidence today | release promotion should require the real connector set, not JSON-only mirrors |
| `rag-service` | Redis-backed retrieval cache; retrieval/index evidence comes from the knowledge/index stack it depends on | in-process cache only for local smoke or transient Redis failure | cache loss is tolerable, but retrieval dependency wiring must stay explicit | `POST /api/rag/v1/diagnose` plus owner-local retrieval smoke | release promotion should require the intended Redis/cache and retrieval dependency wiring for the target environment |
| `marketing-service` | MySQL-backed campaign/artifact/task metadata; optional MinIO raw-object storage for poster artifacts | SQLite/public-URL fallback only for local smoke or no-object-storage mode | generated artifact metadata should survive restart; poster binary durability depends on whether object storage is enabled for the environment | owner-local restart smoke proves DB-backed persistence today; response-level backend proof is still pending | release promotion should require MySQL on the mainline path; MinIO should be required whenever poster/raw-object retention is part of the environment contract |
| `research-service` | MySQL-backed task/result persistence | SQLite/local fallback only for local smoke and tests | task/result history should survive restart outside local smoke | owner-local restart smoke proves DB-backed persistence today; response-level backend proof is still pending | release promotion should require DB-backed runtime instead of local fallback |

## Local fallback rules
- JSON/file/memory fallbacks are acceptable for local bootstrap, isolated smoke, and degraded development recovery only
- once a service is marked release-promotable for an environment, its authoritative runtime path must use the mainline middleware/database backend listed above
- degraded fallbacks must not silently become the only production durability path

## Canonical evidence rules
- minimal `/healthz` routes are liveness checks, not proof of backend selection
- when a service exposes backend-selection evidence in HTTP responses, it should follow `docs/contracts/shared/runtime-health.md`
- until a service exposes response-level backend evidence, QA should use the owner-published restart or compose smoke named in the matrix above

## Current migration notes
- `orchestrator-service`, `tool-hub-service`, and `business-tools-service` are the highest-priority migration surfaces for replacing JSON/file-backed state with MySQL/Redis mainline persistence
- `knowledge-service` already establishes the strongest real-backend baseline in-repo and remains the reference for MinIO/raw-object plus retrieval/index contract expectations
- `BUSINESS_TOOLS_REDIS_NAMESPACE` must stay aligned across business-tools, tool-hub, and orchestrator whenever local or degraded business-tools execution touches shared Redis keyspace
