# Change Request

## Summary
- requester: supervisor-orchestrator
- date: 2026-04-16
- affected frozen path: shared orchestrator continuation schemas/OpenAPI plus shared tool `user_action_hint` / `pending_user_actions` models
- blocking: no

## Background
Owned orchestrator, tool-hub, and business-tools flows already surface `collect-auth-context` pauses when a tool needs `account_id`, `user_id`, roles, or permissions. However, the current frozen continuation payload only documents `field_values`, `confirm_tool_names`, and `session_context_patch`, which is enough for tool-input clarification but not enough to resume auth-required steps without rebuilding a full upstream request.

This rollout adds a practical owner-local baseline for auth continuation:
- business-tools now emits additive `user_profile_bindings` inside `user_action_hint` for `auth-required` results
- tool-hub forwards the same binding metadata through internal/direct tool-call responses and audits
- orchestrator aggregates those bindings into `pending_user_actions[]`
- `POST /api/v1/chat/sessions/{conversation_id}/continue` now accepts additive `user_profile_patch` so callers can resume auth-required steps without reconstructing the original request envelope
- orchestrator also persists collected auth context into session runtime state (`session_context.attributes.auth_profile`) so later turns can reuse it when the caller omits repeated auth/profile fields

## Current Gap
Frozen shared contracts do not yet describe:
- additive `user_profile_bindings` on shared `ToolUserActionHint`
- additive `user_profile_bindings` on orchestrator `PendingUserAction`
- additive `user_profile_patch` on `SessionContinueRequest`
- the documented continuation semantics for persisting collected auth/profile context into runtime session state for later turns

## Proposed Change
Promote the following additive baseline into frozen shared space:
1. extend shared `ToolUserActionHint` with optional `user_profile_bindings` for auth-continuation guidance
2. extend orchestrator `PendingUserAction` with the same additive `user_profile_bindings`
3. extend `SessionContinueRequest` with optional `user_profile_patch` (`user_id`, `account_id`, `roles[]`, `permissions[]`, and other additive profile fields)
4. document that current orchestrator baseline may persist collected auth/profile context into runtime session state as an additive convenience layer for later turns, without changing external auth ownership semantics

## Impacted Consumers
- supervisor(s): supervisor-orchestrator, supervisor-foundation, supervisor-web-user, supervisor-integration-qa
- service(s) or surface(s): orchestrator-service, tool-hub-service, business-tools-service, future gateway/web continuation clients
- required follow-up work: foundation promotion into frozen schemas/OpenAPI and shared DTOs once the additive auth-continuation baseline is accepted

## Compatibility
- breaking or non-breaking: non-breaking additive
- fallback or migration plan: existing consumers may keep reconstructing full follow-up requests manually; newer consumers can adopt `user_profile_patch` and `user_profile_bindings`
- temporary workaround already in use: owned services already emit/consume the additive auth-continuation metadata locally without editing frozen files directly

## Evidence
- code reference(s):
  - `apps/business-tools/src/business_tools/interfaces.py`
  - `apps/tool-hub-service/app/models/tools.py`
  - `apps/orchestrator-service/app/models/orchestration.py`
  - `apps/orchestrator-service/app/api/routes/orchestration.py`
- mock/example/stub reference(s):
  - `apps/business-tools/tests/test_catalog.py`
  - `apps/business-tools/tests/test_service_app.py`
  - `apps/tool-hub-service/tests/test_api.py`
  - `apps/tool-hub-service/tests/test_business_tools_client.py`
  - `apps/orchestrator-service/tests/test_api.py`
  - `apps/orchestrator-service/tests/test_tool_hub_client.py`
- log or validation reference(s):
  - owned pytest coverage now verifies auth-required hints expose `user_profile_bindings`, `/continue` accepts `user_profile_patch`, and collected auth profile can be reused on later turns

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - promoted additive `user_profile_bindings` on shared `ToolUserActionHint` and `PendingUserAction` models so auth-required pauses can advertise how missing context maps onto continuation profile fields
  - promoted shared `UserProfilePatch` plus additive `user_profile_patch` on `SessionContinueRequest`, and aligned the shared internal `UserProfile` baseline with the live additive `locale` / `channel` fields already accepted by orchestrator
  - refreshed shared API conventions, foundation baseline docs, and orchestrator/tool-hub/business-tools OpenAPI descriptions/examples so auth continuation and runtime `session_context.attributes.auth_profile` persistence are explicitly documented
- deferred:
  - no external auth ownership changes were made; the promotion only freezes additive continuation metadata and request fields for the current shared runtime baseline
- rationale:
  - auth-required tool pauses now cross business-tools, tool-hub, orchestrator, UI, and QA boundaries, so the continuation contract can no longer remain owner-local without blocking shared integration
