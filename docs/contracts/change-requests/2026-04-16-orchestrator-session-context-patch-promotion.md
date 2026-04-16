# Change Request: session-context patch + runtime snapshot promotion

- **Date**: 2026-04-16
- **Requester**: supervisor-orchestrator
- **Owned services impacted**: `apps/orchestrator-service`, `apps/tool-hub-service`, `apps/business-tools`
- **Frozen areas requiring foundation follow-up**: `docs/contracts/shared/*`, `openapi/`, shared schema promotion

## Background
The owned orchestration baseline now carries forward practical runtime context across turns instead of forcing callers to resend everything manually.

Implemented behavior now includes:
- business tools emitting additive `session_context_patch` metadata alongside normal results
- tool-hub forwarding that patch and storing a preview in tool-call audit records
- orchestrator merging successful tool patches into per-conversation runtime context so follow-up actions can reuse prior identifiers like `statement_no`, `open_ticket_id`, `invoice_no`, and `application_no`
- session state snapshots exposing derived `session_context`, compact `tool_context`, and an incrementing in-memory `version`

## Requested additions

### 1) Tool result contract promotion
Please promote additive shared schema/OpenAPI fields for:
- `session_context_patch` on internal business-tool execute responses
- `session_context_patch` on tool-hub internal tool-call responses and tool-call audit DTOs
- `session_context_patch` on orchestrator `ToolInvocation`

### 2) Runtime snapshot promotion
Please promote additive shared schema/OpenAPI fields for orchestrator session snapshots:
- `version`
- `session_context`
- `tool_context`

### 3) Contract notes
Please document the baseline semantics:
- only successful tool executions should be applied to persisted runtime session context
- patches are additive hints, not authoritative long-term storage
- runtime snapshot `version` increments on every persisted orchestrator state save, including rollback updates

## Why foundation help is needed
These fields now cross service boundaries. Keeping them only in owned local code risks drift once gateway, admin, or future persistence owners start consuming tool-call audits, runtime snapshots, or internal tool execution contracts.

## Compatibility notes
- all requested changes are additive
- current session context persistence remains in-memory and process-local
- downstream callers can ignore the new fields safely until foundation promotes them

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - promoted additive `session_context_patch` fields across business-tools execute responses, tool-hub tool-call responses/audit records, and orchestrator tool-invocation contracts
  - extended session-state snapshot schemas with `version`, derived `session_context`, and compact `tool_context` item baselines
  - documented the runtime-context semantics in shared schema/catalog/OpenAPI notes and hardened the foundation validator to require the new schema root
