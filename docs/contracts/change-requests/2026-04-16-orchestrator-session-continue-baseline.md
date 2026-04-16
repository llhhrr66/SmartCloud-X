# Change Request: Orchestrator session continue + tool preflight binding baseline

- **Date**: 2026-04-16
- **Requester**: supervisor-orchestrator
- **Owned services impacted**: `apps/orchestrator-service`, `apps/tool-hub-service`, `apps/business-tools`
- **Frozen areas requiring foundation follow-up**: `docs/contracts/shared/*`, `openapi/`, shared schema promotion

## Background
The owned orchestrator baseline already stops safely on clarification-required and confirmation-required tool states, but callers still had to know internal `session_context` wiring to resume those flows correctly. The practical baseline now adds a structured continue route that lets callers submit field values and confirmation decisions without reverse-engineering app-local context keys.

To keep that continuation flow observable and debuggable through the tool boundary, tool-hub preflight responses also now expose the relevant `session_context_bindings` metadata already carried by the owned business-tool definitions.

## Requested additions

### 1) Orchestrator session continue route promotion
Please add frozen OpenAPI/schema coverage for:
- `POST /api/v1/chat/sessions/{conversation_id}/continue`

Current owned request body:
- `message_id?`
- `user_input?`
- `field_values`
- `confirm_tool_names[]`
- `session_context_patch`

Current owned response:
- same internal `ApiEnvelope<ChatCompletionResponse>` family used by retry/chat-completions

Current service-local error addition:
- `CHAT_CONTINUATION_NOT_AVAILABLE` when no pending continuation state exists for the target conversation

### 2) Tool preflight additive metadata promotion
Please extend the frozen internal tool-hub preflight response baseline so `POST /api/v1/tools/preflight` and `/internal/v1/tools/preflight` can include:
- `session_context_bindings`

This field is additive and mirrors the existing tool-definition binding metadata for the fields relevant to continuation/resume flows.

### 3) Shared schema additions
Please promote additive shared internal schemas for:
- `SessionContinueRequest`
- additive `session_context_bindings` on the tool preflight response shape

## Why foundation help is needed
The new continue route and the additive preflight metadata are no longer just owner-local implementation details. Gateway, web, and future admin/debug consumers will need a documented contract for how clarification and confirmation resumes are submitted, and the tool-hub preflight response should expose the same binding semantics in frozen shared space before multiple consumers encode their own variants.

## Compatibility notes
- all requested changes are additive
- the continue route reuses existing session/chat completion DTOs and does not change current retry semantics
- the new preflight metadata is optional for consumers and can be ignored by existing callers

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - added shared `SessionContinueRequest` schema/type coverage in `packages/common-schemas`
  - promoted `POST /api/v1/chat/sessions/{conversation_id}/continue` into `openapi/orchestrator-service.openapi.yaml` with the current additive continuation payload and shared chat-completion response family
  - extended shared tool preflight contracts/OpenAPI descriptions to surface additive `session_context_bindings` so clarification/confirmation resumes can rely on frozen binding metadata
  - registered `CHAT_CONTINUATION_NOT_AVAILABLE` in the shared error catalog and foundation docs
