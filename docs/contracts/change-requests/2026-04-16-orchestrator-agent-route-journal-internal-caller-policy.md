# Change Request

## Summary
- requester: supervisor-orchestrator
- date: 2026-04-16
- affected frozen path: `docs/contracts/shared/api-conventions.md`, `docs/contracts/shared/schema-catalog.md`, and related orchestrator/tool-hub/business-tools OpenAPI snapshots
- blocking: no

## Background
Owned orchestrator, tool-hub, and business-tools services now expose two additive integration baselines:
1. a structured orchestrator agent-route journal so downstream callers can inspect per-step handoff execution without reverse-engineering raw events
2. explicit allowed-caller enforcement on internal tool-hub and business-tools routes so internal execution contracts are not treated as public unauthenticated APIs

## Current Gap
Frozen shared contracts/OpenAPI do not yet describe:
- `GET /api/v1/chat/sessions/{conversation_id}/agent-routes`
- additive `agent_routes[]` on owned orchestrator session-state snapshots
- the requirement that internal tool-hub routes (`/internal/v1/tools*`, `/internal/v1/tool-compensations/call`) reject callers outside `ALLOWED_INTERNAL_CALLERS`
- the requirement that business-tools internal routes reject callers outside `ALLOWED_INTERNAL_CALLERS`
- runtime-config promotion for `ALLOWED_INTERNAL_CALLERS` on tool-hub-service and business-tools-service

## Proposed Change
Promote the following additive baseline into frozen shared space:
1. document `GET /api/v1/chat/sessions/{conversation_id}/agent-routes` as an additive orchestrator debug/inspection route that returns ordered agent handoff records
2. extend the orchestrator session-state schema with additive `agent_routes[]` items containing step/order/agent/status/handoff/action/tool/context-highlight metadata
3. document `ALLOWED_INTERNAL_CALLERS` as an allowed service-local runtime key for tool-hub-service and business-tools-service
4. document that tool-hub and business-tools internal routes must return a structured `403` error when the configured caller header is missing or not allowlisted

## Impacted Consumers
- supervisor(s): supervisor-orchestrator, supervisor-foundation, supervisor-integration-qa
- service(s) or surface(s): orchestrator-service, tool-hub-service, business-tools-service, future gateway/admin/debug consumers, contract/OpenAPI validation
- required follow-up work: foundation promotion into frozen schema/OpenAPI/runtime-config baselines

## Compatibility
- breaking or non-breaking: non-breaking additive for shared contracts; runtime behavior hardens internal routes but does not change public `/api/v1/tools/{tool_name}/invoke` or MCP surfaces
- fallback or migration plan: current owned services already send the caller-service header on orchestrator -> tool-hub -> business-tools internal hops; older consumers can keep using the documented public routes instead of internal ones
- temporary workaround already in use: owned services implement the route and allowlist policy locally without editing frozen contracts directly

## Evidence
- code reference(s):
  - `apps/orchestrator-service/app/api/routes/orchestration.py`
  - `apps/orchestrator-service/app/models/orchestration.py`
  - `apps/tool-hub-service/app/api/routes/tools.py`
  - `apps/tool-hub-service/app/core/config.py`
  - `apps/business-tools/src/business_tools_service/api/routes/tools.py`
  - `apps/business-tools/src/business_tools_service/core/config.py`
- mock/example/stub reference(s):
  - `apps/orchestrator-service/tests/test_api.py`
  - `apps/orchestrator-service/tests/test_persistence.py`
  - `apps/tool-hub-service/tests/test_api.py`
  - `apps/tool-hub-service/tests/test_config.py`
  - `apps/business-tools/tests/test_service_app.py`
  - `apps/business-tools/tests/test_service_config.py`
- log or validation reference(s):
  - owned pytest suites (`34/34`, `34/34`, `59/59`) and compile/import checks now cover the route journal and internal caller allowlist baselines

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - published `GET /api/v1/chat/sessions/{conversation_id}/agent-routes` in the frozen orchestrator OpenAPI baseline and kept `agent_routes[]` on the shared session-state snapshot contract
  - promoted the shared `AgentRouteRecord` and related session snapshot journal metadata needed for ordered handoff inspection, dependencies, tool activity, and context highlights
  - documented the `ALLOWED_INTERNAL_CALLERS` policy for tool-hub and business-tools internal routes in shared runtime/API conventions and added validator coverage for the processed baseline
