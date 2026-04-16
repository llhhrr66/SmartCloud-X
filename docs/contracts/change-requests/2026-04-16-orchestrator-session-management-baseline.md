# Change Request: Orchestrator session management + chat completion baseline

- **Date**: 2026-04-16
- **Requester**: supervisor-orchestrator
- **Owned services impacted**: `apps/orchestrator-service`
- **Frozen areas requiring foundation follow-up**: `docs/contracts/shared/*`, `openapi/`, shared schema promotion

## Background
The practical orchestrator baseline now includes in-memory conversation/session management so owned flows can exercise more of the primary spec without waiting for gateway or persistence owners.

New owned routes now exist for:
- `POST /api/v1/chat/sessions`
- `GET /api/v1/chat/sessions`
- `GET /api/v1/chat/sessions/{conversation_id}`
- `GET /api/v1/chat/sessions/{conversation_id}/messages`
- `PATCH /api/v1/chat/sessions/{conversation_id}`
- `POST /api/v1/chat/sessions/{conversation_id}/archive`
- `POST /api/v1/chat/sessions/{conversation_id}/restore`
- `POST /api/v1/chat/sessions/{conversation_id}/retry`
- `POST /api/v1/chat/completions`

The baseline also introduced internal DTOs for conversation summaries, chat message records, retry payloads, and paginated message/session responses.

## Requested additions

### 1) Internal session/chat route promotion
Please add frozen OpenAPI placeholders for the current orchestrator-owned baseline routes above so downstream gateway/web work can align to a documented owner surface.

### 2) Shared schema promotion
Please promote additive shared internal schemas for:
- `ConversationRecord`
- `SessionListResponse`
- `ChatMessageRecord`
- `SessionMessagesPage`
- `ChatCompletionRequest`
- `ChatCompletionResponse`
- `SessionCreateRequest`
- `SessionUpdateRequest`
- `SessionRetryRequest`

### 3) Lifecycle/error baselines
Please document the current service-level lifecycle/error expectations:
- archived conversations reject new chat completions until restored
- retry creates a new message while preserving the original message history
- missing conversation => `CHAT_CONVERSATION_NOT_FOUND`
- missing retry target message => `CHAT_MESSAGE_NOT_FOUND`
- invalid restore from a non-archived conversation => `CHAT_CONVERSATION_RESTORE_INVALID`

## Why foundation help is needed
These routes and DTOs now cross the boundary from local implementation detail into likely gateway/web integration surfaces. Keeping them only inside downstream code risks contract drift once gateway or frontend owners consume session lists, message history, retry, archive/restore, or service-level `/chat/completions`.

## Compatibility notes
- all requested changes are additive
- current persistence is still in-memory; promotion should describe the DTO/route contract, not imply durable storage semantics yet
- internal services may keep `ApiEnvelope<T>` while gateway/public surfaces normalize to the canonical external envelope

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - promoted shared orchestrator session-management schemas for `ConversationRecord`, `SessionListResponse`, `ChatMessageRecord`, `SessionMessagesPage`, `SessionCreateRequest`, `SessionUpdateRequest`, `SessionRetryRequest`, `ChatCompletionRequest`, and `ChatCompletionResponse`
  - extended `openapi/orchestrator-service.openapi.yaml` and `openapi/components.openapi.yaml` with the current `/api/v1/chat/sessions*` and `/api/v1/chat/completions` baseline, plus shared chat lifecycle error responses
  - registered `CHAT_CONVERSATION_NOT_FOUND`, `CHAT_MESSAGE_NOT_FOUND`, `CHAT_CONVERSATION_ARCHIVED`, and `CHAT_CONVERSATION_RESTORE_INVALID` in the shared error catalog and documented the archive/restore/retry lifecycle semantics in shared contracts
