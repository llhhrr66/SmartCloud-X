# Persistence Backend Contract Baseline

## Summary
- requester: supervisor-integration-qa
- date: 2026-04-16
- affected frozen path: `docs/contracts/shared/runtime-config.md`, `docs/contracts/foundation-baseline.md`, and any shared OpenAPI/runtime-config references that describe service infrastructure expectations
- blocking: no

## Background
The QA-owned baseline now distinguishes three different persistence realities across SmartCloud-X:

1. auth-user-service already exposes a real database-backed runtime surface
2. knowledge-service/rag-service expose real connector/runtime surfaces for MySQL, Redis, MinIO, Qdrant, and OpenSearch, with compose smoke proving those paths
3. orchestrator/tool-hub/business-tools plus marketing/research still rely on file or JSON-backed persistence

The shared frozen contracts currently define common headers, API envelopes, and generic runtime keys, but they do not freeze one cross-service persistence/backend matrix. That leaves QA and downstream teams inferring intended infra from service-local code and compose files instead of one shared contract.

## Current Gap
There is no frozen/shared contract that answers these release-critical questions in one place:

- which services are expected to use MySQL, Redis, MinIO, Qdrant, OpenSearch, MongoDB, or local files
- which backends are required in production versus allowed as local fallback
- which persistence surfaces must survive process restart
- which health/snapshot/metrics fields are the canonical evidence that a service is wired to the intended backend

Without that matrix, QA can report current repo reality, but cannot cleanly distinguish "intended temporary fallback" from "missing shared backend promotion".

## Proposed Change
Promote one shared persistence/backend contract baseline that covers at least:

1. per-service primary persistence backends and allowed local fallbacks
2. required shared env keys for those backends where the names should be frozen
3. restart durability expectations for session/task/audit/cache data
4. canonical health/snapshot/metrics evidence that QA should validate for each service
5. explicit guidance on when local JSON/file stores are acceptable only for local smoke versus not acceptable for release promotion

## Impacted Consumers
- supervisor(s): `supervisor-foundation`, `supervisor-integration-qa`, `supervisor-orchestrator`, `supervisor-knowledge-rag`, `supervisor-auth-marketing-research`
- service(s) or surface(s): auth-user-service, orchestrator-service, tool-hub-service, business-tools-service, knowledge-service, rag-service, marketing-service, research-service
- required follow-up work:
  - foundation to decide where the frozen matrix lives and which runtime-config keys become shared
  - QA to align the owned persistence matrix/reporting with the frozen baseline once it exists

## Compatibility
- breaking or non-breaking: non-breaking additive documentation/config-contract promotion
- fallback or migration plan: QA continues using owner-local code/compose inspection until the frozen matrix exists
- temporary workaround already in use: `scripts/qa/infra_persistence_matrix.py` reports current backend reality directly from the repo

## Evidence
- code reference(s):
  - `scripts/qa/infra_persistence_matrix.py`
  - `deploy/docker-compose/docker-compose.yml`
  - `deploy/docker-compose/smoke-test.py`
  - `apps/auth-user-service/app/core/config.py`
  - `apps/knowledge-service/app/core/config.py`
  - `apps/orchestrator-service/app/core/config.py`
  - `apps/marketing-service/app/core/config.py`
  - `apps/research-service/app/core/config.py`
- log or validation reference(s):
  - the owned readiness report now includes a non-blocking `focusAreas.infraPersistence` section so the current backend split is visible in every QA pass

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - added `docs/contracts/shared/persistence-backends.md` as the frozen repo-wide backend matrix covering authoritative backends, allowed local fallbacks, restart-durability expectations, evidence sources, and release guidance per service
  - updated shared runtime-config and foundation-baseline docs so the persistence matrix is part of the published frozen contract instead of only QA/source inspection knowledge
  - aligned shared root runtime config promotion with the current real-infra migration path by reserving the shared MySQL/Redis connector names and documenting shared MinIO raw-object connector names
- deferred:
  - no new per-service backend snapshot route was forced into owner OpenAPI placeholders when the backing service does not yet publish response-level backend evidence
- rationale:
  - QA needed one frozen source of truth that distinguishes intended temporary fallback from release-ready authoritative persistence, but foundation should still track current repo reality instead of inventing owner routes that do not exist yet
