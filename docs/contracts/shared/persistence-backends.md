# Shared Persistence Backend Baseline

This document freezes the current repo-wide persistence matrix used for infra migration, release decisions, and downstream QA reporting. It records repository reality first, including temporary local fallbacks and migration-stage mixed modes.

## Shared connector-key status
- frozen root connector keys:
  - `SMARTCLOUD_MYSQL_DSN`
  - `SMARTCLOUD_MONGODB_URI`
  - `SMARTCLOUD_MONGODB_DATABASE`
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
- current repo-owned document-store and queue additions:
  - `orchestrator-service` exposes MongoDB-backed document runtimes
  - `knowledge-service` exposes Qdrant/OpenSearch-backed retrieval indexing with fallback-compatible target resolution
  - `rag-service` exposes Redis-backed retrieval cache plus explicit knowledge-service dependency readiness

## Service matrix
| Service | Authoritative mainline backend(s) | Allowed local/degraded fallback | Restart durability expectation | Canonical evidence today | Release guidance |
| --- | --- | --- | --- | --- | --- |
| `auth-user-service` | MySQL-backed account and refresh-session runtime via `SMARTCLOUD_MYSQL_DSN` | SQLite/local file only for local smoke and tests | auth/session state must survive restart outside local smoke | `/healthz` and `/readyz` now expose backend evidence and runtime mode; owner-local smoke still remains useful for restart validation | release promotion should require DB-backed runtime, not bootstrap-only assumptions |
| `orchestrator-service` | MySQL for conversation/session/config state; MongoDB for `conversation_messages`, `agent_reasoning_logs`, `raw_tool_payloads`, and `session_snapshots`; Redis for SSE replay, idempotency, and shared business-tools fallback cache alignment | JSON/file spools only for local smoke and degraded recovery | conversation state, message history, retry snapshots, agent reasoning logs, raw tool payloads, admin agent overrides, and replayable stream events should survive restart | owner-local `tests/test_persistence.py` proves Mongo-backed message/snapshot preference and hard failure when the configured Mongo document store is unavailable; runtime health exposes document-store evidence | release promotion should require MySQL + MongoDB + Redis on the intended main path |
| `knowledge-service` | MySQL metadata, MinIO raw-object mirrors, Qdrant vector index, OpenSearch keyword index, Redis coordination/cache | local JSON mirror and single-target baseline remain migration-safety fallbacks | KB/document metadata, raw objects, index handoff state, and search target configuration should survive restart | `/healthz`, `/readyz`, snapshot/admin diagnostics, and runtime payloads provide connector and readiness evidence; index-target runtime may expose `single-baseline`, `mixed`, or `per-domain` mode | release promotion should require the intended connector set; `single-baseline` may be reviewable baseline, while `mixed`/`per-domain` should be interpreted from runtime evidence rather than assumed from design goals |
| `rag-service` | Redis-backed retrieval cache; retrieval/index evidence comes from knowledge-service and the retrieval stack it depends on | in-process cache only for local smoke or transient Redis failure | cache loss is tolerable, but retrieval dependency wiring must stay explicit | `/healthz`, `/readyz`, and `/api/rag/v1/diagnose` expose cache/backend evidence plus nested `knowledgeService.dependencyReadiness` | release promotion should require intended Redis/cache posture and explicit knowledge dependency wiring for the target environment |

## Local fallback and release semantics
- JSON/file/memory/SQLite fallbacks are acceptable for local bootstrap, isolated smoke, and degraded development recovery only unless a service owner explicitly documents a stronger supported mode
- once a service is marked release-promotable for an environment, its authoritative runtime path must use the mainline middleware/database backend listed above
- degraded fallbacks must not silently become the only production durability path
- `required_for_release=true` in runtime health is the field-level signal that a backend participates in that service's release gate
- `runtime_mode=local-fallback` means the service can still be useful for local validation but should not be reported as shared-backend release proof
- `runtime_mode=mixed` means part of the runtime uses aligned shared backends while another part remains fallback, compatibility, or migration-stage

## Knowledge retrieval/index target modes
The current knowledge indexing/search baseline recognizes these target modes:
- `single-baseline`
  - single collection/index baseline, typically equivalent to the repo-wide default target such as `knowledge_chunks`
  - useful as a reviewable baseline or migration-safe fallback
  - must not be misreported as completed per-domain isolation
- `per-domain`
  - domain-specific collection/index routing is active for the addressed documents/queries
  - runtime evidence should identify the effective per-domain targets, not just the intended design
- `mixed`
  - both baseline and per-domain targets may be active during migration or partial rollout
  - search/query diagnostics should make clear when fallback reads or writes still occur against baseline targets

### Domain index backend evidence
When knowledge-service exposes domain index evidence, QA and reviewers should look for:
- active target mode: `single-baseline`, `mixed`, or `per-domain`
- effective Qdrant collection names
- effective OpenSearch index names
- fallback target names, where applicable
- connector evidence for vector and BM25 backends, such as `connector-ping`, health payload backend records, snapshot output, or diagnose/admin runtime output

Important review rule:
- the presence of domain-index code paths or design docs is not sufficient proof that `per-domain` is active in the running environment
- runtime payloads, diagnose output, or verified tests must show the effective target mode before release reports claim domain isolation is live

## Canonical evidence rules
- minimal `/healthz` routes are liveness checks, not proof of backend selection
- when a service exposes backend-selection evidence in HTTP responses, it should follow `docs/contracts/shared/runtime-health.md`
- `/readyz` is the stricter traffic gate and should be preferred over `/healthz` for release/readiness decisions
- until a service exposes response-level backend evidence, QA should use the owner-published restart or compose smoke named in the matrix above
- nested downstream readiness should use `dependencyReadiness` rather than ad-hoc booleans when effective readiness depends on another service
- domain-index rollout claims should be backed by runtime target evidence, not only by static config or target-state prompts
