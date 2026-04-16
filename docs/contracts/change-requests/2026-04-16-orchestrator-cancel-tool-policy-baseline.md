# Change Request: Orchestrator session cancel + execution-policy metadata baseline

- **Date**: 2026-04-16
- **Requester**: supervisor-orchestrator
- **Owned services impacted**: `apps/orchestrator-service`, `apps/tool-hub-service`, `apps/business-tools`
- **Frozen areas requiring foundation follow-up**: `docs/contracts/shared/*`, `openapi/`, shared schema promotion

## Background
The owned chat/session baseline now supports structured continuation and rollback, but it still lacked a practical way to stop a running turn once a user cancels generation. In parallel, orchestrator planning and tool-hub preflight flows already rely on business-tool execution policy data such as query/write mode, timeout, idempotency, and cache TTL, yet that policy metadata is not frozen as part of the cross-service contract.

The current owner-local rollout adds:
- `POST /api/v1/chat/sessions/{conversation_id}/cancel` for cooperative cancellation of a currently running message
- additive `tool_mode`, `timeout_ms`, `idempotent`, and `cache_ttl_seconds` metadata on owned preflight/planning surfaces

## Requested additions

### 1) Orchestrator session cancel route promotion
Please add frozen OpenAPI/schema coverage for:
- `POST /api/v1/chat/sessions/{conversation_id}/cancel`

Current owned request body:
- `message_id`

Current owned response body:
- `conversation_id`
- `message_id`
- `status=cancelled`
- `cancelled=true`

Current service-local error additions:
- `CHAT_MESSAGE_NOT_RUNNING` when the target message is not currently running
- `CHAT_MESSAGE_CANCELLED` when the cancelled request later resolves back to the original caller
- `CHAT_CONVERSATION_RUNNING` when a second message tries to start while the conversation already has an active running turn

### 2) Tool execution-policy metadata promotion
Please extend the frozen internal tool-hub/orchestrator planning baselines so these additive fields can be documented on the relevant tool readiness/planning shapes:
- `tool_mode` (`query | write`)
- `timeout_ms`
- `idempotent`
- `cache_ttl_seconds`

Current owner-local surfaces emitting that metadata:
- `POST /api/v1/tools/preflight`
- `POST /internal/v1/tools/preflight`
- orchestrator route/state tool-plan payloads (`POST /api/v1/route`, orchestration responses, and persisted `ExecutionEvent.route_selected.data.tool_plan`)

## Why foundation help is needed
The cancel route is now part of the practical user-session lifecycle and should not remain an undocumented owner-local behavior once gateway/web consumers adopt it. Likewise, execution-policy metadata is now shared across business-tools, tool-hub, and orchestrator planning/preflight flows; freezing it will reduce the risk of each downstream consumer inventing its own timeout/idempotency interpretation.

## Compatibility notes
- all requested changes are additive
- cancellation remains cooperative/process-local in the current owner baseline; it does not promise forced interruption of already running downstream writes
- execution-policy metadata is optional for consumers and can be ignored by existing callers that only need readiness booleans and missing-field hints

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - added shared `SessionCancelRequest` and `SessionCancelResponse` schema/type coverage in `packages/common-schemas`
  - promoted `POST /api/v1/chat/sessions/{conversation_id}/cancel` into `openapi/orchestrator-service.openapi.yaml` with the current cooperative-cancellation semantics
  - extended shared tool preflight and orchestrator planning contracts with additive execution-policy metadata: `tool_mode`, `timeout_ms`, `idempotent`, and `cache_ttl_seconds`
  - registered `CHAT_MESSAGE_NOT_RUNNING`, `CHAT_MESSAGE_CANCELLED`, and `CHAT_CONVERSATION_RUNNING` in the shared error catalog and contract docs
