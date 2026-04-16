# Change Request

## Summary
- requester: supervisor-orchestrator
- date: 2026-04-16
- affected frozen path: `docs/contracts/shared/runtime-config.md`, `docs/contracts/shared/schema-catalog.md`, and related frozen internal tool-provider / tool-hub OpenAPI placeholders
- blocking: no

## Background
Owned orchestrator, tool-hub, and business-tools services now support a provider-backed tool-contract discovery baseline so downstream callers can read actual tool descriptors and preflight readiness metadata from the deployed provider chain instead of relying only on local starter metadata.

## Current Gap
Frozen shared contracts do not yet describe:
- business-tools internal descriptor route `GET /internal/v1/tools/{tool_name}`
- business-tools internal readiness route `POST /internal/v1/preflight/{tool_name}`
- runtime config keys `BUSINESS_TOOLS_INTERNAL_API_PREFIX` and `TOOL_HUB_INTERNAL_API_PREFIX`
- the expectation that tool-hub and orchestrator may resolve tool metadata from downstream/internal providers when configured for HTTP transport

## Proposed Change
Promote additive provider-backed discovery coverage:
1. document business-tools internal detail and preflight routes as additive provider-facing contracts
2. allow additive runtime-config keys for downstream internal prefix overrides (`BUSINESS_TOOLS_INTERNAL_API_PREFIX`, `TOOL_HUB_INTERNAL_API_PREFIX`)
3. clarify that tool-hub registry/preflight and orchestrator planning may source tool metadata from downstream HTTP providers when transport is configured accordingly
4. keep the change non-breaking by preserving existing local/default `/internal/v1` behavior

## Impacted Consumers
- supervisor(s): supervisor-orchestrator, supervisor-foundation
- service(s) or surface(s): business-tools-service, tool-hub-service, orchestrator-service, future admin/debug or gateway integrations that inspect internal tool contracts
- required follow-up work: foundation promotion into frozen shared runtime-config/schema/OpenAPI descriptions

## Compatibility
- breaking or non-breaking: non-breaking additive
- fallback or migration plan: all owned services still fall back to local metadata and the default `/internal/v1` prefix when the new routes/config are not used
- temporary workaround already in use: owned services already implement the new routes and config locally without editing frozen contracts

## Evidence
- code reference(s):
  - `apps/business-tools/src/business_tools_service/api/routes/tools.py`
  - `apps/tool-hub-service/app/services/business_tools_client.py`
  - `apps/tool-hub-service/app/services/registry.py`
  - `apps/orchestrator-service/app/services/router.py`
  - `apps/orchestrator-service/app/services/tool_hub_client.py`
- mock/example/stub reference(s):
  - `apps/business-tools/tests/test_service_app.py`
  - `apps/tool-hub-service/tests/test_api.py`
  - `apps/tool-hub-service/tests/test_registry.py`
  - `apps/orchestrator-service/tests/test_router.py`
  - `apps/orchestrator-service/tests/test_tool_hub_client.py`
- log or validation reference(s):
  - owned pytest suites and compile checks now cover remote descriptor/preflight discovery plus configurable downstream internal prefixes

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - promoted the live provider-facing business-tools discovery routes `GET /internal/v1/tools/{tool_name}` and `POST /internal/v1/preflight/{tool_name}` into `openapi/business-tools-service.openapi.yaml`
  - reserved `BUSINESS_TOOLS_INTERNAL_API_PREFIX` and `TOOL_HUB_INTERNAL_API_PREFIX` in the shared runtime baseline and `@smartcloud-x/common` env-key registry
  - documented provider-backed descriptor/preflight discovery expectations in shared runtime-config and API-convention docs
  - hardened foundation validation to require the promoted provider-discovery routes and non-pending change-request results
