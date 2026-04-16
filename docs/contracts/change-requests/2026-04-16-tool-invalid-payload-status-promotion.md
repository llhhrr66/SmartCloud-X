# Change Request

## Summary
- requester: supervisor-orchestrator
- date: 2026-04-16
- affected frozen path: `docs/contracts/shared/schema-catalog.md` and related frozen internal tool-hub/business-tools schemas / OpenAPI placeholders
- blocking: no

## Background
The owned orchestrator, tool-hub, and business-tools baselines now enforce required tool payload fields consistently across:
- local business-tools execution
- tool-hub internal `/internal/v1/tools/call`
- business-tools internal `/internal/v1/execute/{tool_name}`
- orchestrator HTTP tool-hub adapter

This closes a practical contract gap where malformed tool payloads could previously continue with placeholder values instead of failing fast.

## Current Gap
Frozen shared tool-call/business-tool baselines do not yet document the normalized malformed-payload behavior:
- response/code semantics for required-field failures (`4001001`, `message="invalid tool payload"`)
- stable tool result / audit status value `invalid-payload`
- minimum error detail shape containing `missing_fields`

Without frozen promotion, downstream consumers can use the new behavior today, but shared schema/OpenAPI validation cannot rely on it yet.

## Proposed Change
Promote additive internal contract coverage for required-field validation failures:
1. tool-call / business-tool response schemas should allow `status="invalid-payload"`
2. tool-call / business-tool error code documentation should include `4001001` for missing required payload fields
3. error detail examples should include `missing_fields: string[]`
4. tool-call audit schema examples should show `invalid-payload` alongside existing auth/confirmation/idempotency statuses

## Impacted Consumers
- supervisor(s): supervisor-orchestrator, supervisor-foundation
- service(s) or surface(s): orchestrator-service, tool-hub-service, business-tools-service, future admin/debug consumers of tool-call audit data
- required follow-up work: foundation promotion into frozen internal schemas/OpenAPI descriptions

## Compatibility
- breaking or non-breaking: non-breaking additive
- fallback or migration plan: downstream services may continue treating these cases as generic failures until they adopt the new explicit status/code
- temporary workaround already in use: owned services already emit the new status/code locally without editing frozen contracts

## Evidence
- code reference(s):
  - `apps/business-tools/src/business_tools/catalog.py`
  - `apps/tool-hub-service/app/services/audit_store.py`
  - `apps/orchestrator-service/app/services/tool_hub_client.py`
- mock/example/stub reference(s):
  - `apps/tool-hub-service/tests/test_api.py`
  - `apps/business-tools/tests/test_catalog.py`
- log or failing validation reference(s):
  - malformed refund payloads now fail fast with `missing_fields=["order_no","amount"]` in owned test coverage

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - promoted the malformed-payload baseline into shared schemas by documenting `missing_fields` error-detail support and adding `invalid-payload` to the shared tool-call audit status enum
  - aligned `openapi/tool-hub-service.openapi.yaml` and `openapi/business-tools-service.openapi.yaml` with the live in-band failure semantics, including `code=4001001`, `message=invalid tool payload`, `missing_fields` examples, and the audit status/query enum updates
  - updated foundation/shared schema docs and the validator so future readiness checks fail if the malformed-payload status/example baseline regresses
