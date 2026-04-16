# Change Request

## Summary
- requester: supervisor-orchestrator
- date: 2026-04-16
- affected frozen path: `docs/contracts/shared/schema-catalog.md` and related frozen internal tool-hub / business-tools schemas or OpenAPI placeholders
- blocking: no

## Background
Owned orchestrator, tool-hub, and business-tools code now includes a lightweight tool preflight / clarification baseline so the system can stop before execution when a tool is missing required business fields. This avoids placeholder payloads and lets the orchestrator ask for missing invoice, refund, ICP, or billing-range inputs before calling downstream tools.

## Current Gap
Frozen shared contracts do not yet describe:
- internal tool-hub `POST /internal/v1/tools/preflight`
- the additive tool preflight result fields such as `ready`, `available`, `missing_payload_fields`, `missing_payload_hints`, `missing_auth_context`, and `confirmation_required`
- additive tool-definition metadata `input_field_hints` used by tool-hub registry consumers and orchestrator clarification prompts

Without promotion, the owned services can use the new baseline immediately, but shared schema/OpenAPI validation cannot rely on it yet.

## Proposed Change
Promote additive internal contract coverage for tool readiness validation:
1. add an internal tool-hub preflight route alongside the existing tool-call route
2. define a shared preflight/readiness response schema with missing-payload, auth-required, confirmation-required, missing-tool, invalid-operation, and ready outcomes
3. allow additive `input_field_hints` metadata on internal tool definitions so orchestrator and admin/debug consumers can surface meaningful clarification prompts
4. document that preflight does not execute the tool call or create a tool-call audit record

## Impacted Consumers
- supervisor(s): supervisor-orchestrator, supervisor-foundation
- service(s) or surface(s): orchestrator-service, tool-hub-service, business-tools-service, future admin/debug consumers of tool definitions and tool readiness checks
- required follow-up work: foundation promotion into frozen internal schemas/OpenAPI descriptions

## Compatibility
- breaking or non-breaking: non-breaking additive
- fallback or migration plan: consumers may continue calling `/internal/v1/tools/call` directly and handle malformed payloads as runtime failures until they adopt preflight
- temporary workaround already in use: owned services already share the new preflight behavior locally without editing frozen contracts

## Evidence
- code reference(s):
  - `apps/business-tools/src/business_tools/interfaces.py`
  - `apps/tool-hub-service/app/api/routes/tools.py`
  - `apps/orchestrator-service/app/services/agent_runtime.py`
- mock/example/stub reference(s):
  - `apps/tool-hub-service/tests/test_api.py`
  - `apps/business-tools/tests/test_catalog.py`
  - `apps/orchestrator-service/tests/test_api.py`
- log or failing validation reference(s):
  - owned tests now verify clarification-first behavior for missing billing range, invoice fields, and refund fields before execution

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - promoted additive `input_field_hints` metadata and shared `ToolPreflightResult` / `ToolPreflightResponse` schemas into `packages/common-schemas`
  - aligned `openapi/tool-hub-service.openapi.yaml` and `openapi/components.openapi.yaml` with the canonical `POST /api/v1/tools/preflight` baseline plus `/internal/v1/tools/preflight` compatibility alias documentation
  - documented that preflight is a readiness-only contract and must not execute the tool or create a tool-call audit record in the shared contract docs
  - hardened the foundation validator to require the new preflight schema roots, `input_field_hints`, and tool-hub preflight OpenAPI coverage
