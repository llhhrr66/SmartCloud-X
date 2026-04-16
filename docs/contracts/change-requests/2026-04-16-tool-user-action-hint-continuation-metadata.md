# Change Request

## Summary
- requester: supervisor-orchestrator
- date: 2026-04-16
- affected frozen path: `docs/contracts/shared/schema-catalog.md`, `docs/contracts/shared/api-conventions.md`, and related frozen orchestrator/tool-hub/business-tools OpenAPI placeholders
- blocking: no

## Background
Owned orchestrator, tool-hub, and business-tools flows already support clarification, auth collection, and confirmation resumes, but the structured hint object that explains those next steps currently exists only in owner-local models.

This round promotes the practical baseline by:
- returning additive `user_action_hint` on business-tools execute failures such as `invalid-payload`, `auth-required`, and `confirmation-required`
- forwarding the same hint through tool-hub direct tool-call responses and tool-call audit records
- forwarding the hint into orchestrator `ToolInvocation` records
- aggregating additive `pending_user_actions[]` in orchestrator responses and session-state snapshots so continuation callers can resume from structured instructions instead of parsing summary text

## Current Gap
Frozen shared contracts do not yet describe:
- additive `user_action_hint` on business-tools execute responses
- additive `user_action_hint` on tool-hub direct/internal tool-call responses and audit read models
- additive `user_action_hint` on orchestrator tool invocation records
- additive orchestrator `pending_user_actions[]` response/state metadata for continuation-ready tool actions

## Proposed Change
Promote the following additive baseline into frozen shared space:
1. publish `user_action_hint` as an additive execution field on tool failure/readiness shapes that require caller follow-up
2. keep the existing action families aligned with the owner-local baseline:
   - `clarify-tool-input`
   - `collect-auth-context`
   - `user-confirmation`
3. add orchestrator `pending_user_actions[]` as an additive aggregation over the active tool-level hints, including tool name, tool call id, agent, and the copied action metadata
4. document that `pending_user_actions[]` is advisory continuation metadata and does not replace the existing `pending_actions[]` summary or `/continue` route semantics

## Impacted Consumers
- supervisor(s): supervisor-orchestrator, supervisor-foundation, supervisor-web-user, supervisor-integration-qa
- service(s) or surface(s): orchestrator-service, tool-hub-service, business-tools-service, future gateway/web/admin continuation consumers
- required follow-up work: foundation promotion into frozen schemas/OpenAPI and any shared DTO packages

## Compatibility
- breaking or non-breaking: non-breaking additive
- fallback or migration plan: existing consumers may continue using `pending_actions[]`, tool status, and summary text until they adopt the richer hints
- temporary workaround already in use: owned services already emit and consume the additive hint metadata locally without editing frozen files directly

## Evidence
- code reference(s):
  - `apps/business-tools/src/business_tools/catalog.py`
  - `apps/tool-hub-service/app/services/business_tools_client.py`
  - `apps/tool-hub-service/app/models/tools.py`
  - `apps/orchestrator-service/app/models/orchestration.py`
  - `apps/orchestrator-service/app/api/routes/orchestration.py`
  - `apps/orchestrator-service/app/services/tool_hub_client.py`
- mock/example/stub reference(s):
  - `apps/business-tools/tests/test_service_app.py`
  - `apps/tool-hub-service/tests/test_api.py`
  - `apps/tool-hub-service/tests/test_business_tools_client.py`
  - `apps/orchestrator-service/tests/test_api.py`
  - `apps/orchestrator-service/tests/test_tool_hub_client.py`
- log or validation reference(s):
  - owned pytest coverage now verifies local and HTTP-mode propagation of `user_action_hint` plus orchestrator `pending_user_actions[]` persistence

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - added reusable shared `ToolUserActionHint` and `PendingUserAction` schema/type baselines for machine-readable clarification, auth, and confirmation follow-up metadata
  - promoted additive `user_action_hint` coverage across business-tools, tool-hub direct/audit/preflight contracts, orchestrator tool invocation records, and additive `pending_user_actions[]` aggregation on orchestrator response/state payloads
  - refreshed shared API conventions, OpenAPI descriptions/examples, and validator coverage so continuation-hint metadata remains documented and cannot silently regress
