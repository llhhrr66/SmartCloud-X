# Auth / Marketing / Research Runtime Backend Health Baseline

## Summary
- requester: supervisor-integration-qa
- date: 2026-04-16
- affected frozen path: `openapi/auth-user-service.openapi.yaml`, `openapi/marketing-service.openapi.yaml`, `openapi/research-service.openapi.yaml`, and any shared runtime-health guidance under `docs/contracts/shared/`
- blocking: no

## Background
The QA-owned baseline now proves `auth-user-service`, `marketing-service`, and `research-service` persist live runtime data in database-backed stores instead of only editing bootstrap JSON files. That proof comes from restart-oriented integration smoke in `tests/integration/test_service_smoke.py`.

However, the current public `/healthz` responses for all three services still return only a minimal `{"status":"ok","service":"..."}` payload. Unlike `knowledge-service`, `orchestrator-service`, `tool-hub-service`, and `business-tools-service`, these services do not expose canonical runtime evidence for which backend is currently selected.

## Current Gap
QA can currently prove:
- database-backed restart durability for auth refresh sessions
- database-backed restart durability for marketing poster tasks and research tasks
- bootstrap JSON remains unchanged while runtime writes land in the database

QA cannot currently prove through a canonical service health/snapshot surface:
- whether auth is using a database runtime versus fallback bootstrap-only assumptions
- whether marketing selected MySQL and optional MinIO artifact storage in the current process
- whether research selected MySQL instead of a local fallback path
- whether any future Redis-backed runtime adoption is actually active rather than only declared in config

That limitation forces QA to infer backend reality from owner-local tests and source inspection instead of one frozen runtime-health contract.

## Proposed Change
Promote one additive runtime-health baseline for `auth-user-service`, `marketing-service`, and `research-service` that includes at least:

1. a canonical health or snapshot field that reports the active database backend and fallback path
2. optional backend fields for MinIO or Redis when those integrations are configured or intentionally absent
3. stable field names that QA can validate without scraping service-local implementation details
4. OpenAPI examples that show the expected response shape for both local fallback and shared-backend modes

## Impacted Consumers
- supervisor(s): `supervisor-auth-marketing-research`, `supervisor-integration-qa`, `supervisor-foundation`
- service(s) or surface(s): `auth-user-service`, `marketing-service`, `research-service`
- required follow-up work:
  - auth/marketing/research owner to decide whether the evidence lives on `/healthz` or a separate runtime/snapshot endpoint
  - foundation to promote the response shape into frozen OpenAPI/shared contract guidance
  - QA to replace source-inspection-only assumptions with response-level assertions once the contract is frozen

## Compatibility
- breaking or non-breaking: non-breaking additive response contract promotion
- fallback or migration plan: QA keeps using restart smoke plus source inspection until canonical runtime evidence is available
- temporary workaround already in use: `scripts/qa/infra_persistence_matrix.py` explicitly records that backend selection for these services is still partly inferred from source layout rather than health payloads

## Evidence
- code reference(s):
  - `tests/integration/test_service_smoke.py`
  - `apps/auth-user-service/app/routes.py`
  - `apps/auth-user-service/app/store.py`
  - `apps/marketing-service/app/routes.py`
  - `apps/marketing-service/app/store.py`
  - `apps/research-service/app/routes.py`
  - `apps/research-service/app/store.py`
- log or validation reference(s):
  - the owned infra-persistence matrix now reports these services with corrected wording instead of implying runtime proof that their public health endpoints do not actually provide

## Foundation Processing Result
- processed at: 2026-04-16
- decision: partially accepted; shared runtime-health guidance is now frozen, but owner route publication remains deferred
- implemented:
  - added `docs/contracts/shared/runtime-health.md` to freeze canonical additive field names for backend-selection evidence on future `/healthz` or runtime/snapshot surfaces
  - updated `openapi/auth-user-service.openapi.yaml`, `openapi/marketing-service.openapi.yaml`, and `openapi/research-service.openapi.yaml` so their current `/healthz` placeholders explicitly state that they are liveness-only and point to the shared runtime-health guidance for future backend evidence
  - linked the service-level evidence gap back to the new frozen persistence matrix so QA can distinguish current restart-smoke proof from future response-level proof
- deferred:
  - no new response body schema or dedicated runtime/snapshot route was published for auth/marketing/research because those services do not expose one yet in repo reality
- rationale:
  - foundation should freeze the naming contract now, but it should not invent live response payloads for owner services that still only publish minimal liveness today
