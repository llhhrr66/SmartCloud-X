# Change Request

## Summary
- requester: supervisor-orchestrator
- date: 2026-04-16
- affected frozen path: `docs/contracts/shared/schema-catalog.md`, related frozen internal tool/orchestrator schemas, and OpenAPI placeholders
- blocking: no

## Background
Owned orchestrator, tool-hub, and business-tools code now share dependency-aware tool metadata so the orchestrator can reason about same-turn prerequisites and session-context hydration without hardcoding per-tool behavior. The baseline now exposes which tool inputs can be satisfied from session context, which session keys a tool produces, and which prerequisite tool names should run earlier in the plan.

## Current Gap
Frozen shared contracts do not yet describe the new additive metadata and route/planning fields:
- additive tool-definition metadata: `session_context_bindings`, `session_context_output_keys`, and `prerequisite_tool_names`
- additive orchestrator tool-plan metadata: `deferred_payload_fields`, `depends_on_tool_call_ids`, `session_context_input_keys`, `session_context_output_keys`, and `readiness`
- additive handoff/task metadata: agent step/session context inputs and outputs used for richer handoff planning and state-event inspection

Without promotion, owned services can use the metadata immediately, but shared schema/OpenAPI validation and downstream consumers cannot rely on it yet.

## Proposed Change
Promote additive dependency/context metadata into the frozen shared contract layer:
1. extend shared internal tool-definition schemas with `session_context_bindings`, `session_context_output_keys`, and `prerequisite_tool_names`
2. extend orchestrator route/planning schemas with `deferred_payload_fields`, `depends_on_tool_call_ids`, `session_context_input_keys`, `session_context_output_keys`, and `readiness`
3. extend handoff/task/state-event schemas so agent planning surfaces can describe context inputs/outputs per step
4. document that these fields are additive planning metadata and do not change existing execution semantics for consumers that ignore them

## Impacted Consumers
- supervisor(s): supervisor-orchestrator, supervisor-foundation
- service(s) or surface(s): orchestrator-service, tool-hub-service, business-tools-service, future gateway/admin/debug consumers of route and tool metadata
- required follow-up work: foundation promotion into frozen schemas/OpenAPI descriptions and any shared DTOs

## Compatibility
- breaking or non-breaking: non-breaking additive
- fallback or migration plan: existing consumers may ignore the new metadata and continue using current route/tool execution behavior
- temporary workaround already in use: owned services already derive and consume the metadata locally without editing frozen contracts

## Evidence
- code reference(s):
  - `apps/business-tools/src/business_tools/interfaces.py`
  - `apps/business-tools/src/business_tools/catalog.py`
  - `apps/tool-hub-service/app/models/tools.py`
  - `apps/orchestrator-service/app/models/orchestration.py`
  - `apps/orchestrator-service/app/services/router.py`
  - `apps/orchestrator-service/app/services/tool_context.py`
  - `apps/orchestrator-service/app/services/agent_runtime.py`
- mock/example/stub reference(s):
  - `apps/business-tools/tests/test_catalog.py`
  - `apps/business-tools/tests/test_service_app.py`
  - `apps/tool-hub-service/tests/test_registry.py`
  - `apps/tool-hub-service/tests/test_api.py`
  - `apps/orchestrator-service/tests/test_router.py`
  - `apps/orchestrator-service/tests/test_runtime.py`
  - `apps/orchestrator-service/tests/test_api.py`
- log or failing validation reference(s):
  - owned tests now verify dependency-aware invoice planning, tool-order reordering, registry metadata exposure, and runtime hydration from declared session-context bindings

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - promoted additive tool-definition metadata for `session_context_bindings`, `session_context_output_keys`, and `prerequisite_tool_names` into the shared tool registry schemas and OpenAPI descriptions
  - promoted additive orchestrator planning metadata for `required_payload_fields`, `missing_payload_fields`, `deferred_payload_fields`, `depends_on_tool_call_ids`, session-context input/output keys, and per-tool `readiness`
  - promoted additive task/handoff dependency and session-context metadata, refreshed shared README/contract summaries, and hardened the foundation validator to catch regressions
