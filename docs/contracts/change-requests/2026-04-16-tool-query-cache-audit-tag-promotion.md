# Change Request: tool query-cache replay semantics + audit tag propagation

## Summary
- requester: supervisor-orchestrator
- date: 2026-04-16
- affected frozen path: shared tool invocation schemas/OpenAPI for business-tools execute + tool-hub direct tool-call responses/audit read models
- blocking: no

## Background
This round extends the owned orchestrator/tool-hub/business-tools baseline with a practical in-memory cache for successful query tools. The cache is intentionally process-local for now, but the replay signal now crosses three owned services:

- `apps/business-tools` marks replayed query results with `audit_tags += ["cache-hit"]`
- `apps/tool-hub-service` forwards those tags on direct tool-call responses and persists them in audit records
- `apps/orchestrator-service` forwards the same tags into tool traces so chat/integration callers can see whether a result came from cache

## Current Gap
Frozen shared contracts currently describe `session_context_patch`, compensation, idempotency, and audit read models, but they do not yet freeze:

1. `audit_tags` on business-tools execute responses
2. `audit_tags` on tool-hub direct `ToolCallResponse`
3. `audit_tags` on tool-call audit read models
4. explicit shared wording that successful read/query tool responses may be replayed from a local cache and surfaced with a stable `cache-hit` annotation

## Proposed Change
Please promote additive shared/OpenAPI support for:

- `audit_tags: string[]` on:
  - business-tools execute response
  - tool-hub internal/direct tool-call response
  - tool-call audit detail/list read models
- shared guidance that read/query tools may replay prior successful results from a cache and should surface that via `audit_tags` (current baseline tag: `cache-hit`)

## Impacted Consumers
- supervisor(s): supervisor-orchestrator, future gateway/admin consumers
- service(s) or surface(s): `apps/business-tools`, `apps/tool-hub-service`, `apps/orchestrator-service`, future `/api/v1/admin/tool-calls`
- required follow-up work: foundation promotion of the additive response/audit fields

## Compatibility
- breaking or non-breaking: non-breaking additive
- fallback or migration plan: downstream consumers can ignore `audit_tags` until they adopt the richer trace surface
- temporary workaround already in use: owned services already exchange these fields locally without touching frozen files

## Evidence
- code reference(s):
  - `apps/business-tools/src/business_tools/query_cache.py`
  - `apps/business-tools/src/business_tools_service/models/tools.py`
  - `apps/tool-hub-service/app/models/tools.py`
  - `apps/orchestrator-service/app/services/tool_hub_client.py`
- mock/example/stub reference(s):
  - `apps/business-tools/tests/test_service_app.py::test_business_tools_service_surfaces_query_cache_hits`
  - `apps/tool-hub-service/tests/test_api.py::test_tool_call_audit_surfaces_query_cache_hits_and_filtering`
  - `apps/orchestrator-service/tests/test_api.py::test_orchestrator_propagates_query_cache_audit_tags`
- log or failing validation reference(s): owned services now rely on additive local models because frozen shared contracts do not yet publish the new `audit_tags` path

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - promoted additive `audit_tags` support into the shared business-tools execute response, tool-hub direct tool-call response, and tool-call audit record schemas in `packages/common-schemas`
  - aligned `openapi/tool-hub-service.openapi.yaml` and `openapi/business-tools-service.openapi.yaml` with the live replay annotation baseline, including `audit_tag` filtering on audit reads and the stable `cache-hit` description
  - documented shared query-cache replay guidance in `docs/contracts/shared/api-conventions.md`, `docs/contracts/shared/schema-catalog.md`, and the foundation baseline/openapi package README files
  - hardened `scripts/validate_foundation.py` so future foundation readiness checks fail if the promoted `audit_tags` fields regress or if change requests remain unresolved
