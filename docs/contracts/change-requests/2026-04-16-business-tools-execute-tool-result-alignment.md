# Change Request

## Summary
- requester: supervisor-orchestrator
- date: 2026-04-16
- affected frozen path: `docs/contracts/shared/schema-catalog.md`, `openapi/business-tools-service.openapi.yaml`, `openapi/components.openapi.yaml`, and the shared internal `BusinessToolExecuteResponse` schema/type
- blocking: no

## Background
Owned `business-tools-service` and `tool-hub-service` now support provider-backed direct invoke in HTTP deployments. That path needs the business-tools execute route to carry the same practical execution metadata that the shared `ToolExecutionResult` already defines, so tool-hub can preserve direct invoke semantics without falling back to a local-only starter implementation.

## Current Gap
The current frozen `BusinessToolExecuteResponse` contract still only documents:
- `success`
- `code`
- `message`
- `data`
- `audit_tags`
- `retryable`
- `cache_ttl_seconds`
- `provider`
- `error_detail`
- `compensation`
- `idempotency_key`
- `session_context_patch`

That omits the richer execution fields already frozen on `ToolExecutionResult`:
- `tool_name`
- `operation`
- `status`
- `summary`
- `result`
- `citations`

Without those additive fields, tool-hub direct invoke cannot treat the business-tools HTTP provider as the full source of truth for `ToolInvokeResponse`.

## Proposed Change
Promote additive execute-response alignment for `POST /internal/v1/execute/{tool_name}`:
1. extend `BusinessToolExecuteResponse` with `tool_name`, `operation`, `status`, `summary`, `result`, and `citations`
2. explicitly keep existing `message` and `data` fields as compatibility aliases during migration
3. document that `result` and `data` should carry the same payload in the current additive phase
4. clarify that downstream consumers may prefer `result/status/summary` when they need `ToolExecutionResult` fidelity, while older callers may continue using `message/data`

## Impacted Consumers
- supervisor(s): supervisor-orchestrator, supervisor-foundation
- service(s) or surface(s): business-tools-service, tool-hub-service, orchestrator debug/admin consumers, future gateway integrations that call direct tool invoke surfaces
- required follow-up work: foundation promotion into frozen schema/OpenAPI docs

## Compatibility
- breaking or non-breaking: non-breaking additive
- fallback or migration plan: owned tool-hub/business-tools code continues to emit and accept the legacy `message` + `data` fields alongside the richer execution fields
- temporary workaround already in use: tool-hub currently parses both shapes so older frozen payloads still work while the additive contract waits for promotion

## Evidence
- code reference(s):
  - `apps/business-tools/src/business_tools_service/api/routes/tools.py`
  - `apps/business-tools/src/business_tools_service/models/tools.py`
  - `apps/tool-hub-service/app/services/business_tools_client.py`
  - `apps/tool-hub-service/app/services/dispatcher.py`
  - `apps/tool-hub-service/app/api/routes/tools.py`
- mock/example/stub reference(s):
  - `apps/business-tools/tests/test_service_app.py`
  - `apps/tool-hub-service/tests/test_api.py`
  - `apps/tool-hub-service/tests/test_business_tools_client.py`
- log or validation reference(s):
  - owned pytest suites now cover the richer execute payload plus provider-backed direct invoke in HTTP mode

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - aligned the shared `BusinessToolExecuteResponse` schema/type with the live richer execute payload by adding `tool_name`, `operation`, `status`, `summary`, `result`, and `citations`
  - kept `message` and `data` as additive compatibility aliases and documented that `result` and `data` carry the same payload in the current baseline phase
  - refreshed `openapi/business-tools-service.openapi.yaml`, shared contract summaries, and the foundation validator so the execute-response alignment cannot silently regress
