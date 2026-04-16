# Change Request

## Summary
- requester: supervisor-integration-qa
- date: 2026-04-16
- affected frozen path: `packages/common-schemas/src/schemas/api-envelope.schema.json`, related shared envelope references, and orchestrator OpenAPI responses that reuse `ApiEnvelope`
- blocking: no

## Background
The project-level QA baseline validates live service responses against the frozen shared `ApiEnvelope` contract. Current successful responses on multiple services include `error: null` rather than omitting the field entirely.

## Current Gap
The frozen shared `ApiEnvelope` schema currently defines:
- `error` as a direct `$ref` to `ErrorInfo`
- `meta` as `type: object`
- no nullable variant for either optional object field

That conflicts with the live success-envelope behavior observed on:
- `POST /api/knowledge/v1/catalog:bootstrap`
- `POST /api/knowledge/v1/search`
- `POST /api/v1/chat/sessions`
- `POST /api/v1/chat/completions`
- `GET /api/v1/sessions/{conversation_id}/state`

## Proposed Change
Promote additive success-envelope alignment for shared optional object fields:
1. allow `error` to be null when `success=true` and no error payload exists
2. allow `meta` to be null when no metadata payload exists
3. keep the existing structured `ErrorInfo` object for failure cases
4. document whether success responses should prefer omitting these fields or explicitly returning null, so downstream consumers and validators can normalize consistently

## Impacted Consumers
- supervisor(s): supervisor-knowledge-rag, supervisor-orchestrator, supervisor-foundation, supervisor-integration-qa
- service(s) or surface(s): orchestrator-service, knowledge-service, and any future service that reuses the shared success envelope
- required follow-up work: foundation promotion into frozen schema/OpenAPI/types

## Compatibility
- breaking or non-breaking: non-breaking additive
- fallback or migration plan: consumers may treat missing and null `error` as equivalent success-envelope states until the frozen schema is updated
- temporary workaround already in use: QA baseline records this as a documented contract drift and only suppresses hard-failure on the affected orchestrator success responses

## Evidence
- code reference(s):
  - `apps/orchestrator-service/app/main.py`
  - `apps/orchestrator-service/app/models/common.py`
  - `packages/common-schemas/src/schemas/api-envelope.schema.json`
- mock/example/stub reference(s):
  - `tests/integration/test_orchestrator_smoke.py`
  - `scripts/qa/project_smoke.py`
- log or failing validation reference(s):
  - live contract validation failed with `error: None is not of type 'object'`

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - updated the shared `ApiEnvelope` schema/type so `error` may be omitted or explicitly `null` on success responses while preserving the structured `ErrorInfo` object for failure cases
  - updated the shared `ApiEnvelope` schema/type so optional object metadata may also return `meta: null` when a service has no non-domain metadata to surface
  - refreshed shared API-convention/foundation docs to document that missing and `null` internal `error` and `meta` states are equivalent success-envelope forms
  - added validator coverage for the processed change request and the promoted nullable envelope behavior
