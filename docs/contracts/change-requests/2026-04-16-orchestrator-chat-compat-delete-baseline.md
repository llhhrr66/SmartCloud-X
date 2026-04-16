# Change Request: enrich orchestrator chat-completions compatibility + session delete baseline

## Summary
- requester: supervisor-orchestrator
- date: 2026-04-16
- affected frozen path: orchestrator chat/session OpenAPI + shared session-management baseline
- blocking: no

## Background
The owned orchestrator baseline now supports a more spec-shaped `POST /api/v1/chat/completions` request/response flow and closes one remaining session lifecycle gap:

- request compatibility fields accepted locally: `context`, `options`, `context_control`, `client_meta`
- non-stream response now includes additive top-level `answer`, `citations`, `tool_calls`, `usage`, and `finish_reason`
- session lifecycle now includes `DELETE /api/v1/chat/sessions/{conversation_id}` for soft delete

These changes stay inside owned code and do not modify frozen files directly.

## Current Gap
Frozen session/chat baselines currently do not fully describe:

1. additive compatibility fields on `ChatCompletionRequest`
2. additive summary fields on non-stream `ChatCompletionResponse`
3. `DELETE /api/v1/chat/sessions/{conversation_id}` soft-delete route

## Proposed Change
Please promote additive shared/OpenAPI coverage for:

- `ChatCompletionRequest` compatibility fields:
  - `context`
  - `options`
  - `context_control`
  - `client_meta`
- non-stream `ChatCompletionResponse` summary fields:
  - `answer`
  - `citations`
  - `tool_calls`
  - `usage`
  - `finish_reason`
- session delete route:
  - `DELETE /api/v1/chat/sessions/{conversation_id}`
  - soft-delete semantics (`status=deleted`, hidden from normal session listing/detail flows)

## Impacted Consumers
- supervisor(s): supervisor-orchestrator, supervisor-web-user, future gateway/admin owners
- service(s) or surface(s): `apps/orchestrator-service`, user chat surface, future gateway normalization
- required follow-up work: foundation promotion of the additive request/response fields and delete route docs

## Compatibility
- breaking or non-breaking: non-breaking additive
- fallback or migration plan: existing callers can keep using current `user_profile/session_context/constraints` fields and nested `response`
- temporary workaround already in use: owned orchestrator service accepts both the older owner-local payload shape and the spec-style compatibility fields

## Evidence
- code reference(s):
  - `apps/orchestrator-service/app/models/orchestration.py`
  - `apps/orchestrator-service/app/api/routes/orchestration.py`
  - `apps/orchestrator-service/app/services/conversation_store.py`
- mock/example/stub reference(s):
  - `apps/orchestrator-service/tests/test_api.py::test_chat_completions_accepts_spec_style_context_and_options`
  - `apps/orchestrator-service/tests/test_api.py::test_chat_session_delete_soft_deletes_conversation`
- log or failing validation reference(s): owned orchestrator now exposes additive behavior that the frozen chat/session OpenAPI baseline does not yet document

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - promoted additive `context`, `options`, `context_control`, and `client_meta` request fields plus top-level `answer`, `citations`, `tool_calls`, `usage`, and `finish_reason` response aliases into the shared chat-completion schemas in `packages/common-schemas`
  - added shared `ChatUsage` and `SessionDeleteResponse` schema baselines plus corresponding `openapi/components.openapi.yaml` refs
  - extended `openapi/orchestrator-service.openapi.yaml` with the frozen `DELETE /api/v1/chat/sessions/{conversation_id}` route, the soft-delete lifecycle wording, and refreshed chat-completion descriptions to match the current runtime surface
  - hardened `scripts/validate_foundation.py` so future readiness checks fail if the promoted chat-compat/delete contract fields or operations regress
