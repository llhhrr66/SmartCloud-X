# Change Request

## Summary
- requester: supervisor-integration-qa
- date: 2026-04-16
- affected frozen path: `openapi/tool-hub-service.openapi.yaml` and related tool-hub direct invoke response schemas
- blocking: no

## Background
The project-level QA smoke validates the live `POST /api/v1/tools/{tool_name}/invoke` response against the frozen tool-hub OpenAPI contract. The live response currently includes additive metadata fields that are useful for direct invoke consumers.

## Current Gap
The frozen direct invoke response schema currently rejects:
- `downstream_target`
- `auth_requirements`

The live service includes both fields in the `data` payload for direct invoke responses.

## Proposed Change
Promote additive response metadata alignment for tool-hub direct invoke:
1. allow `downstream_target` on the direct invoke success payload
2. allow `auth_requirements` on the direct invoke success payload
3. document that these fields are additive metadata and do not replace the existing execution-result fields

## Impacted Consumers
- supervisor(s): supervisor-orchestrator, supervisor-foundation, supervisor-integration-qa
- service(s) or surface(s): tool-hub-service direct invoke consumers, QA contract validation
- required follow-up work: foundation promotion into frozen OpenAPI/schema docs

## Compatibility
- breaking or non-breaking: non-breaking additive
- fallback or migration plan: consumers may ignore the additive metadata until the frozen contract is updated
- temporary workaround already in use: QA baseline records this as a documented contract drift and only suppresses hard-failure on the affected direct invoke success response

## Evidence
- code reference(s):
  - `apps/tool-hub-service/app/api/routes/tools.py`
  - `apps/tool-hub-service/app/models/tools.py`
- mock/example/stub reference(s):
  - `scripts/qa/project_smoke.py`
  - `apps/tool-hub-service/tests/test_api.py`
- log or failing validation reference(s):
  - live contract validation failed because `auth_requirements` and `downstream_target` were present in `data` but rejected by the frozen schema

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - updated the shared direct invoke response schema/type so `downstream_target` and `auth_requirements` are accepted additive metadata on successful tool-hub invoke responses
  - aligned tool-hub OpenAPI descriptions/examples and shared schema-catalog/API-convention docs with the richer direct invoke metadata
  - added validator coverage for the processed change request and the promoted direct invoke response fields
