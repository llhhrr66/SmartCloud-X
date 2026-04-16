# Change Request

## Summary
- requester: supervisor-integration-qa
- date: 2026-04-16
- affected frozen path: tool-hub audit record schemas and `openapi/tool-hub-service.openapi.yaml`
- blocking: no

## Background
The project-level QA smoke validates `GET /api/v1/tool-calls` against the frozen tool-hub audit contract. Live audit records for successful tool executions currently persist `status: completed`.

## Current Gap
The frozen audit status enum currently excludes `completed`, so otherwise valid successful audit rows fail contract validation.

## Proposed Change
Promote additive audit-status alignment:
1. allow `completed` on tool-hub audit record status
2. document how `completed` relates to the older success-oriented status vocabulary already present in the frozen contract
3. align examples for successful query and write tool executions

## Impacted Consumers
- supervisor(s): supervisor-orchestrator, supervisor-foundation, supervisor-integration-qa
- service(s) or surface(s): tool-hub audit readers, admin/debug consumers, QA contract validation
- required follow-up work: foundation promotion into frozen schema/OpenAPI docs

## Compatibility
- breaking or non-breaking: non-breaking additive
- fallback or migration plan: consumers may continue treating `completed` as the success-path status while frozen contracts are updated
- temporary workaround already in use: QA baseline records this as a documented contract drift and only suppresses hard-failure on the affected audit list response

## Evidence
- code reference(s):
  - `apps/tool-hub-service/app/services/audit_store.py`
  - `apps/tool-hub-service/app/models/tools.py`
- mock/example/stub reference(s):
  - `scripts/qa/project_smoke.py`
- log or failing validation reference(s):
  - live contract validation failed because `data[].status` contained `completed`, which is not present in the frozen enum

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - updated the shared tool-call audit schema/OpenAPI enum so `completed` is part of the frozen success-path status vocabulary
  - documented `completed` as the current stored success status while keeping `success` as an additive compatibility alias for older readers and filters
  - added validator coverage for the processed change request and the promoted audit-status enum value
