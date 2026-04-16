# Change Request: Agent + tool metadata promotion for orchestrator baseline

- **Date**: 2026-04-16
- **Requester**: supervisor-orchestrator
- **Owned services impacted**: `apps/orchestrator-service`, `apps/tool-hub-service`, `apps/business-tools`
- **Frozen areas requiring foundation follow-up**: shared internal schemas/OpenAPI for agent descriptors, agent execution results, and tool definitions

## Background
The owned orchestrator/tool baseline now carries more of the primary spec's metadata contract directly in runtime responses so downstream gateway/admin/debug consumers can inspect richer descriptors without reverse-engineering app-local hints.

Implemented additive behavior now includes:
- orchestrator agent descriptors exposing `version`, `owner`, `input_schema_version`, and `output_schema_version`
- agent execution results exposing additive `risk_flags`
- business-tool definitions exposing additive `version`, `input_schema`, and `output_schema`
- tool-hub/business-tools registry/list surfaces serializing those richer tool-definition fields
- owned contract tests/stub fixtures for the orchestrator -> tool-hub and tool-hub -> business-tools chains, aligned to the current runtime payloads

## Requested additions

### 1) Agent descriptor metadata promotion
Please promote additive shared/OpenAPI coverage for `AgentDescriptor` fields:
- `version`
- `owner`
- `input_schema_version`
- `output_schema_version`

### 2) Agent execution risk flags
Please promote additive shared/OpenAPI coverage for `AgentExecutionResult.risk_flags`.

Current owner-local values include:
- `missing_tool_input`
- `missing_auth_context`
- `confirmation_required`
- `idempotency_conflict`
- `tool_failure`
- `human_handoff_requested`

### 3) Tool definition metadata promotion
Please promote additive shared/OpenAPI coverage for `ToolDefinition` fields:
- `version`
- `input_schema`
- `output_schema`

Current owner-local semantics:
- `input_schema` / `output_schema` are lightweight JSON-Schema-like objects derived from the existing owner-local hint fields
- they are descriptive metadata for discovery, validation hints, and contract inspection; current runtime validation logic still relies on explicit required-field/auth/preflight checks

## Why foundation help is needed
These metadata fields now cross service boundaries:
- orchestrator `GET /api/v1/agents`
- tool-hub tool registry/list surfaces
- business-tools internal tool listing
- agent execution payloads returned through orchestrator chat/session APIs

Leaving them only in owned code risks drift once shared schema/OpenAPI validators, gateway transforms, or admin/runtime inspection flows start depending on them.

## Compatibility notes
- all requested changes are additive
- existing consumers can ignore the new fields safely
- owned contract-test stub fixtures remain downstream-owned; this request is only for the promoted shared metadata surface, not for moving test fixtures into frozen space

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - promoted additive agent metadata fields (`version`, `owner`, `input_schema_version`, `output_schema_version`) into the shared orchestrator `AgentDescriptor` schema and TypeScript interfaces
  - promoted additive `risk_flags` coverage, including the current owner-local enum set, into the shared orchestrator execution-result contract
  - promoted additive tool-definition metadata (`version`, `input_schema`, `output_schema`) into the shared tool registry schemas and refreshed the relevant OpenAPI descriptions plus validation checks
