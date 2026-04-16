# Change Request: executable Saga compensation baseline for orchestrator/tool-hub/business-tools

- **Date**: 2026-04-16
- **Requester**: supervisor-orchestrator
- **Owned services impacted**: `apps/orchestrator-service`, `apps/tool-hub-service`, `apps/business-tools`
- **Frozen areas requiring foundation follow-up**: shared schemas/OpenAPI/error catalog for rollback + compensation execution routes/events

## Background
The current owned baseline already exposes Saga compensation metadata inside orchestrator state snapshots, but the stack is only descriptive. This round adds executable rollback plumbing so the orchestrator can actually invoke compensation actions through tool-hub/business-tools instead of only storing `compensation` payloads.

Implemented owned-scope runtime additions:
- `POST /api/v1/sessions/{conversation_id}/rollback` in `orchestrator-service`
- `POST /internal/v1/tool-compensations/call` in `tool-hub-service` (also reachable via the existing `/api/v1` service router alias)
- `POST /internal/v1/compensations/execute` in `business-tools-service`
- new `compensation_result` state event plus rollback response payloads

## Requested frozen-contract additions

### 1) Orchestrator rollback route + response schema
Please add baseline schema/OpenAPI coverage for:
- `POST /api/v1/sessions/{conversation_id}/rollback`

Suggested response payload:
- `conversation_id`
- `status`: `completed | partial | failed | noop`
- `compensated_steps[]`
  - `step_id`
  - `tool_name`
  - `action_name`
  - `status`
  - `success`
  - `message`
  - `data`
  - `provider`
  - `code`
  - `retryable`
  - `latency_ms`
  - `error_detail`
  - `idempotency_key`
- `state_snapshot`
- `trace`

### 2) Tool-hub / business-tools compensation execution contracts
Please promote shared internal schemas/OpenAPI for:
- `POST /internal/v1/tool-compensations/call`
- `POST /internal/v1/compensations/execute`

Suggested request fields:
- `trace_id`
- `conversation_id`
- `compensation_id`
- `action_name`
- `operator`
- `payload`
- optional `idempotency_key`

Suggested response fields:
- `success`
- `code`
- `message`
- `data`
- `compensation_id`
- `action_name`
- `latency_ms`
- `provider`
- optional `error`
- optional `idempotency_key`
- optional `attempts`

### 3) State/event schema update
Please extend the shared orchestrator execution-event schema to include:
- `compensation_result`

Suggested data fields:
- `step_id`
- `action_name`
- `status`
- `success`
- `provider`

## Why foundation follow-up is needed
These shapes now cross service boundaries and are no longer an implementation detail of a single owned app. Without frozen promotion, gateway/admin/persistence owners will not have a stable rollback contract or a shared event vocabulary for compensation execution.

## Compatibility notes
- additive only; existing state snapshot and tool-call contracts stay valid
- rollback is best-effort and currently operates on the in-memory session snapshot baseline
- compensation routes are internal-service contracts, not a public end-user API commitment yet

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - promoted shared schemas for `CompensationExecutionRecord`, `SessionRollbackResponse`, `CompensationCallRequest`, `CompensationCallResponse`, `BusinessCompensationExecuteRequest`, and `BusinessCompensationExecuteResponse`
  - extended `openapi/orchestrator-service.openapi.yaml`, `openapi/tool-hub-service.openapi.yaml`, `openapi/business-tools-service.openapi.yaml`, and `openapi/components.openapi.yaml` with rollback/compensation execution baseline coverage
  - updated the shared execution-event schema to include `compensation_result` so rollback state transitions are frozen consistently with the current runtime
  - hardened the foundation validator to require the new rollback/compensation schema roots and OpenAPI paths
