# Change Request

## Summary
- requester: supervisor-orchestrator
- date: 2026-04-16
- affected frozen path: `openapi/orchestrator-service.openapi.yaml`, `openapi/tool-hub-service.openapi.yaml`, any frozen business-tools service contract docs/OpenAPI coverage for health endpoints, and shared runtime/ops contract docs that describe service readiness evidence
- blocking: no

## Background
The owned orchestrator, tool-hub, and business-tools services now expose additive `GET /readyz` routes alongside the existing `GET /healthz` surfaces.

This increment makes the migrated middleware and HTTP boundaries operationally visible:
- `business-tools-service /readyz` returns non-ready when Redis-backed idempotency/query-cache runtime has degraded
- `tool-hub-service /readyz` returns non-ready when MySQL-backed audit storage is degraded or downstream `business-tools-service` is not ready over HTTP
- `orchestrator-service /readyz` returns non-ready when MySQL/Redis-backed orchestrator runtime is degraded or downstream `tool-hub-service` is not ready over HTTP

The existing `/healthz` routes were also extended with additive nested `dependencyReadiness` metadata on the upstream HTTP transport sections so operators can distinguish config from live downstream readiness.

## Current Gap
The frozen contract/OpenAPI/runtime docs do not yet describe:
- additive `GET /readyz` endpoints for orchestrator, tool-hub, and business-tools
- the `ready` / `not_ready` response status vocabulary plus `not_ready_components[]`
- additive nested `dependencyReadiness` metadata under orchestrator `toolHubTransport` and tool-hub `businessToolsTransport` health payloads

Without promotion, the owned runtime behavior is available and tested locally, but downstream operators, QA, and future gateway/admin consumers cannot rely on one documented readiness baseline.

## Proposed Change
Promote an additive runtime readiness baseline that covers:
1. `GET /readyz` for orchestrator, tool-hub, and business-tools with `status`, `service`, `not_ready_components`, and `runtime`
2. the operational distinction that `/healthz` may report degraded-but-live state while `/readyz` is the stricter load-balancer/readiness signal
3. additive nested `dependencyReadiness` metadata for owned upstream HTTP transport sections
4. the expectation that HTTP-mainline upstream services should surface downstream readiness failures instead of silently appearing healthy when their required dependency is absent

## Impacted Consumers
- supervisor(s): supervisor-orchestrator, supervisor-foundation, supervisor-integration-qa
- service(s) or surface(s): orchestrator-service, tool-hub-service, business-tools-service, deploy/readiness probes, future admin/debug tooling
- required follow-up work:
  - foundation to promote the readiness route and payload coverage into frozen docs/OpenAPI
  - QA to include `readyz` expectations in owned infra/runtime verification once promoted

## Compatibility
- breaking or non-breaking: non-breaking additive
- fallback or migration plan: existing consumers may continue to use `/healthz`; operators can adopt `/readyz` incrementally for stricter readiness gating
- temporary workaround already in use: owned service code and tests rely on the additive owner-local readiness routes and metadata without editing frozen files directly

## Evidence
- code reference(s):
  - `apps/orchestrator-service/app/api/routes/health.py`
  - `apps/orchestrator-service/app/services/tool_hub_client.py`
  - `apps/tool-hub-service/app/api/routes/health.py`
  - `apps/tool-hub-service/app/services/business_tools_client.py`
  - `apps/business-tools/src/business_tools_service/api/routes/health.py`
- mock/example/stub reference(s):
  - `apps/orchestrator-service/tests/test_api.py`
  - `apps/orchestrator-service/tests/test_tool_hub_client.py`
  - `apps/tool-hub-service/tests/test_api.py`
  - `apps/tool-hub-service/tests/test_business_tools_client.py`
  - `apps/business-tools/tests/test_service_app.py`
- log or failing validation reference(s):
  - owned validation passes with additive readiness coverage: targeted `60/57/29` tests, full `153/82/83` tests, plus compileall across all three owned services

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - added shared `RuntimeHealthStatus`, `RuntimeReadinessStatus`, and `RuntimeDependencyReadiness` schemas in `@smartcloud-x/common-schemas`
  - updated `openapi/orchestrator-service.openapi.yaml`, `openapi/tool-hub-service.openapi.yaml`, and `openapi/business-tools-service.openapi.yaml` to publish `/readyz`, richer `/healthz` payloads, and nested downstream `dependencyReadiness` examples
  - expanded `docs/contracts/shared/runtime-health.md` so `/healthz` vs `/readyz` semantics and the shared readiness field names are frozen in docs as well as OpenAPI
- deferred:
  - no owner-specific runtime component sub-schemas were frozen beyond the shared top-level readiness/health envelopes; per-service `runtime.*` component details remain additive examples for now
- rationale:
  - the routes and readiness vocabulary already exist in live owner code, so frozen space needed a shared baseline for operators and QA without overfitting every service-local runtime snapshot detail into brittle shared DTOs
