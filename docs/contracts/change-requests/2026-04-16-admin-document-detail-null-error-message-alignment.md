# Change Request

## Summary
- requester: supervisor-integration-qa
- date: 2026-04-16
- affected frozen path: admin knowledge document detail schemas and `openapi/admin-api.openapi.yaml`
- blocking: no

## Background
The project-level QA smoke validates the admin document detail response against the frozen admin API contract. The live knowledge-service admin detail payload currently returns `document.error_message: null` when no document-level error exists.

## Current Gap
The frozen admin knowledge document detail contract still requires `document.error_message` to be a string when present. That does not match the live no-error read model.

## Proposed Change
Promote additive nullability alignment for admin knowledge document detail:
1. allow `document.error_message` to be omitted or null when no error exists
2. keep string values for actual document-level error states
3. align shared OpenAPI examples and DTO/type exports accordingly

## Impacted Consumers
- supervisor(s): supervisor-knowledge-rag, supervisor-foundation, supervisor-integration-qa
- service(s) or surface(s): knowledge-service admin detail route, web-admin consumers, QA contract validation
- required follow-up work: foundation promotion into frozen schema/OpenAPI/types

## Compatibility
- breaking or non-breaking: non-breaking additive
- fallback or migration plan: consumers may treat missing and null `document.error_message` as equivalent no-error states until frozen contracts are updated
- temporary workaround already in use: QA baseline records this as a documented contract drift and only suppresses hard-failure on the affected admin detail success response

## Evidence
- code reference(s):
  - `apps/knowledge-service/app/api/routes/admin.py`
  - `apps/knowledge-service/app/models/admin.py`
- mock/example/stub reference(s):
  - `scripts/qa/project_smoke.py`
- log or failing validation reference(s):
  - live contract validation failed with `data.document.error_message: None is not of type 'string'`

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - updated the shared admin knowledge-document schema/type so `document.error_message` may be omitted or explicitly `null` when no document-level error exists
  - aligned admin OpenAPI examples and shared admin baseline docs with the nullable document-detail behavior while preserving string values for real failure states
  - added validator coverage for the processed change request and the promoted nullable admin document field
