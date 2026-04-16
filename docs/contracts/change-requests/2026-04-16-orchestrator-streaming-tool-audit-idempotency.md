# Change Request: Orchestrator streaming + tool audit + idempotency semantics

- **Date**: 2026-04-16
- **Requester**: supervisor-orchestrator
- **Owned services impacted**: `apps/orchestrator-service`, `apps/tool-hub-service`, `apps/business-tools`
- **Frozen areas requiring foundation follow-up**: `docs/contracts/shared/*`, `openapi/`, shared schema promotion

## Background
The orchestrator baseline now materially needs three cross-service contract additions that are not described in the frozen shared contracts/OpenAPI set:

1. a spec-aligned orchestrator SSE route for streamed chat/event playback
2. tool-hub audit read routes for tool-call tracing and admin inspection
3. explicit idempotency replay/conflict semantics for write tools, including the new `4090001` conflict case and optional `attempts` metadata on tool-call responses

## Requested additions

### 1) Orchestrator SSE contract
Please add a canonical OpenAPI/shared schema for:
- `POST /api/v1/sessions/{conversation_id}/messages/stream`
- response content type: `text/event-stream`
- baseline event sequence currently emitted: `meta`, `reasoning`, `retrieval`, `tool_call`, `tool_result`, `delta`, `citation`, `done`

Suggested payload fields:
- `meta`: `conversation_id`, `message_id`, `trace_id`, `agent`
- `reasoning`: `agent`, `summary`, `step`
- `tool_call`: `tool_name`, `tool_call_id`, `status`, `arguments`
- `tool_result`: `tool_name`, `tool_call_id`, `status`, `latency_ms`, `data_preview`
- `done`: `finish_reason`, `usage`, `next_action`, `pending_actions`

### 2) Tool audit read models
Please add canonical schemas/routes for:
- `GET /api/v1/tool-calls`
- `GET /api/v1/tool-calls/{tool_call_id}`

Suggested audit record fields:
- `tool_call_id`, `trace_id`, `conversation_id`, `tool_name`, `operation`
- `status`, `success`, `code`, `message`, `provider`, `retryable`
- `latency_ms`, `attempts`, `tenant_id`, `operator`, `user_context`
- `idempotency_key`, `data_preview`, `error`, `created_at`, `updated_at`

### 3) Idempotency behavior promotion
Please promote explicit shared guidance for write-tool duplicate handling:
- same `Idempotency-Key` + same normalized payload/context => replay prior successful result
- same `Idempotency-Key` + different normalized payload/context => return conflict (`4090001`)
- tool-call response may include `attempts` for retry-aware gateways/tool-hubs

Suggested error registration:
- `4090001`: idempotency conflict / key reused with different write request

## Why foundation help is needed
These semantics now span multiple owned services and should not remain only in downstream code comments/tests. Shared OpenAPI + schema promotion will keep gateway, admin, and future persistence owners aligned.

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - promoted shared orchestrator stream-event payload schemas plus the `POST /api/v1/sessions/{conversation_id}/messages/stream` OpenAPI baseline
  - promoted shared tool-call audit record schemas plus `GET /api/v1/tool-calls` and `GET /api/v1/tool-calls/{tool_call_id}` OpenAPI placeholders
  - documented explicit idempotency replay/conflict rules in shared API conventions, registered `IDEMPOTENCY_CONFLICT`, and added retry `attempts` metadata to the shared direct tool-call response contract
  - extended the foundation validator to require the new stream/audit baseline paths and schema roots
