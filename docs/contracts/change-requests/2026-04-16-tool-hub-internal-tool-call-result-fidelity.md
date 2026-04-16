# Change Request

## Summary
- requester: supervisor-orchestrator
- date: 2026-04-16
- affected frozen path: shared internal `tool-call-response` / tool-call audit schemas and the corresponding `openapi/tool-hub-service.openapi.yaml` + orchestrator-facing contract docs
- blocking: no

## Background
Owned `business-tools` already returns richer execute metadata for direct providers:
- `status`
- `summary`
- `result`
- `citations`

This rollout now keeps that metadata intact through the owned `tool-hub-service` internal `/internal/v1/tools/call` response and into `orchestrator-service` HTTP-mode tool invocations, instead of collapsing everything to legacy `message` + `data` only.

## Current Gap
The frozen shared contract baseline still focuses on the older internal tool-call shape and may not yet describe the richer additive response/audit fields that owned services now emit:
- internal `ToolCallResponse.status`
- internal `ToolCallResponse.summary`
- internal `ToolCallResponse.result`
- internal `ToolCallResponse.citations`
- additive tool-call audit fields for `summary` and `citations`

Without promotion, the owned services can interoperate today, but shared schema/OpenAPI validation and downstream consumers cannot rely on those richer fields yet.

## Proposed Change
Promote additive internal tool-call fidelity fields into the frozen baseline:
1. extend the internal tool-hub tool-call response schema with `status`, `summary`, `result`, and `citations`
2. keep `message` and `data` as compatibility aliases during the additive phase
3. extend tool-call audit/read schemas with additive `summary` and `citations`
4. document that `result` and `data` carry the same payload in the current compatibility phase, while `summary` is the preferred human-readable execution text

## Impacted Consumers
- supervisor(s): supervisor-orchestrator, supervisor-foundation
- service(s) or surface(s): tool-hub-service, orchestrator-service, future gateway/admin/debug consumers of tool-call responses and audit records
- required follow-up work: foundation promotion into frozen schema/OpenAPI docs

## Compatibility
- breaking or non-breaking: non-breaking additive
- fallback or migration plan: downstream services may continue reading `message` + `data` while newer consumers adopt `status` + `summary` + `result` + `citations`
- temporary workaround already in use: owned tool-hub/orchestrator code now reads the richer fields when present and falls back to the legacy fields otherwise

## Evidence
- code reference(s):
  - `apps/tool-hub-service/app/models/tools.py`
  - `apps/tool-hub-service/app/services/business_tools_client.py`
  - `apps/tool-hub-service/app/services/audit_store.py`
  - `apps/orchestrator-service/app/services/tool_hub_client.py`
- mock/example/stub reference(s):
  - `apps/business-tools/tests/stubs/business-tools/execute-success.json`
  - `apps/tool-hub-service/tests/stubs/tool-hub/tools-call-success.json`
  - `apps/orchestrator-service/tests/contracts/tool_hub_service/orchestrator_service/test_tools_call_contract.py`
- log or validation reference(s):
  - owned pytest suites pass with richer status/summary/result/citation propagation across business-tools -> tool-hub -> orchestrator HTTP paths

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - extended the shared internal `ToolCallResponse` schema/type with additive `status`, `summary`, `result`, and `citations` while keeping `message` and `data` as compatibility aliases
  - extended the shared `ToolCallAuditRecord` schema with additive `summary` and `citations`, and aligned tool-hub OpenAPI descriptions/examples with the richer direct-response baseline
  - refreshed shared contract summaries and validator coverage so the promoted tool-call fidelity fields and processing record cannot silently regress
