# Change Request

## Summary
- requester: supervisor-integration-qa
- date: 2026-04-16
- affected frozen path: `packages/common-schemas` research-task schemas and `openapi/research-service.openapi.yaml`
- blocking: no

## Background
The project-level QA baseline validates live research-service responses against the frozen research task contract. Completed task detail responses currently return `error_message: null` when no error occurred.

## Current Gap
The frozen research task detail contract still requires `error_message` to be a string when the field is present. That does not match the live completed-task payload shape.

## Proposed Change
Promote additive nullability alignment for research task detail:
1. allow `error_message` to be omitted or null on successful task details
2. keep string values for real task failure states
3. align OpenAPI examples and shared DTO/type exports accordingly

## Impacted Consumers
- supervisor(s): supervisor-auth-marketing-research, supervisor-foundation, supervisor-integration-qa
- service(s) or surface(s): research-service, frontend consumers polling research tasks, QA contract validation
- required follow-up work: foundation promotion into frozen schema/OpenAPI/types

## Compatibility
- breaking or non-breaking: non-breaking additive
- fallback or migration plan: consumers may treat missing and null `error_message` as equivalent no-error states until frozen contracts are updated
- temporary workaround already in use: QA baseline records this as a documented contract drift and only suppresses hard-failure on the affected success detail response

## Evidence
- code reference(s):
  - `apps/research-service/app/models.py`
  - `apps/research-service/app/routes.py`
- mock/example/stub reference(s):
  - `tests/integration/test_auth_marketing_research_flow.py`
  - `scripts/qa/project_smoke.py`
- log or failing validation reference(s):
  - live contract validation failed with `data.error_message: None is not of type 'string'`

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - updated the shared research-task schema/type so `error_message` may be omitted or explicitly `null` on successful task detail payloads
  - aligned research OpenAPI examples and shared foundation docs with the nullable research-task error field while preserving string values for real failure states
  - added validator coverage for the processed change request and the promoted nullable research-task field
