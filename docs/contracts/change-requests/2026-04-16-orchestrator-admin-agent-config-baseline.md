# Change Request

## Summary
- requester: supervisor-orchestrator
- date: 2026-04-16
- affected frozen path: `openapi/orchestrator-service.openapi.yaml`, related shared schema catalog entries, and any frozen admin API baseline docs that enumerate orchestrator owner routes
- blocking: no

## Background
The owned orchestrator baseline now includes a lightweight admin-facing agent configuration surface so local operators can inspect and tune the practical FastAPI supervisor without editing code. The service exposes:
- `GET /api/v1/admin/agents` with additive `scene` / `status` filtering
- `PATCH /api/v1/admin/agents/{agent_code}` for process-local `enabled`, `max_tool_calls`, `fallback_agent`, and `timeout_seconds` overrides

The router already honors those overrides for routable/supporting-agent selection and per-agent tool-plan limits.

## Current Gap
Frozen OpenAPI/shared contract coverage does not yet describe:
- the admin orchestrator agent-config routes above
- the additive admin response fields `tool_whitelist`, `enabled`, and `timeout_seconds`
- the owner-local runtime config keys `DEFAULT_AGENT_TIMEOUT_SECONDS` and `AGENT_CONFIG_STORE_PATH`

Without a promotion request, the owned implementation works locally, but frozen contract validation cannot treat the new admin agent-config baseline as documented cross-service behavior.

## Proposed Change
Promote an additive orchestrator admin agent-config baseline into frozen docs/OpenAPI:
1. add `GET /api/v1/admin/agents` and `PATCH /api/v1/admin/agents/{agent_code}` to the orchestrator OpenAPI baseline
2. add reusable admin agent DTO coverage for list/update responses, including `tool_whitelist`, `enabled`, and `timeout_seconds`
3. document the owner-local runtime knobs `DEFAULT_AGENT_TIMEOUT_SECONDS` and `AGENT_CONFIG_STORE_PATH`
4. clarify that the current implementation is a process-local practical baseline, not yet a distributed control plane

## Impacted Consumers
- supervisor(s): supervisor-orchestrator, supervisor-foundation
- service(s) or surface(s): orchestrator-service, admin/debug tooling, future web-admin agent-config views
- required follow-up work: foundation promotion into frozen schemas/OpenAPI/runtime docs once the additive admin-agent baseline is accepted

## Compatibility
- breaking or non-breaking: non-breaking additive
- fallback or migration plan: callers may ignore the new admin route/fields until they are ready to use them
- temporary workaround already in use: owned orchestrator code and tests use the app-local admin models/routes without editing frozen files directly

## Evidence
- code reference(s):
  - `apps/orchestrator-service/app/api/routes/orchestration.py`
  - `apps/orchestrator-service/app/services/router.py`
  - `apps/orchestrator-service/app/services/agent_config_store.py`
  - `apps/orchestrator-service/app/models/orchestration.py`
  - `apps/orchestrator-service/app/core/config.py`
- mock/example/stub reference(s):
  - `apps/orchestrator-service/tests/test_api.py`
  - `apps/orchestrator-service/tests/test_router.py`
  - `apps/orchestrator-service/tests/test_config.py`
- log or failing validation reference(s):
  - current frozen docs/contracts/OpenAPI coverage does not enumerate orchestrator admin agent-config routes or the new runtime keys even though the owned service now ships them
