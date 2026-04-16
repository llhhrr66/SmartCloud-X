# @smartcloud-x/common-schemas

Foundation-owned shared schema package for SmartCloud-X.

Published baseline:
- common JSON Schemas for envelopes, tracing, caller context, pagination, and health, including additive internal `ApiEnvelope.error=null` success-envelope compatibility
- canonical external HTTP envelope schemas for public user/admin gateway contracts plus a generic SSE envelope baseline
- `schemaRegistry` path exports covering every frozen `*.schema.json` file published from this package so downstream tooling can resolve promoted contracts without path guessing
- user/auth/admin-auth DTO schemas for login, refresh, account update, password recovery/change, admin bootstrap menus, internal auth validation/check routes, nullable auth-profile avatars, plus reusable marketing copy/promotion-link request, detail, and history-list DTOs alongside task-history/status/result DTOs
- orchestrator stream-event payload schemas covering the current emitted `meta/reasoning/retrieval/tool_call/tool_result/delta/citation/done` sequence
- current orchestrator DTO schemas, including route planning, session CRUD/history/chat-completion contracts, additive chat-completion compatibility fields (`context`, `options`, `context_control`, `client_meta`), continue/cancel/soft-delete markers, execution details, internal chat payloads, session state snapshots with versioned runtime context, execution events, and Saga compensation metadata
- promoted tool definition / invocation / execution schemas shared across orchestrator, tool-hub, and business-tools, including additive descriptor metadata (`version`, `input_schema`, `output_schema`), dependency/session-context metadata (`session_context_bindings`, `session_context_output_keys`, `prerequisite_tool_names`), `input_field_hints`, execution-policy metadata (`tool_mode`, `timeout_ms`, `idempotent`, `cache_ttl_seconds`), aligned business-tools execute fidelity fields (`tool_name`, `operation`, `status`, `summary`, `result`, `citations`), direct tool-call fidelity fields (`status`, `summary`, `result`, `citations`) with compatibility `message`/`data` aliases, audit `summary`/`citations`, preflight/readiness response models, `session_context_patch`, `audit_tags`, malformed-payload `invalid-payload` audit semantics, `missing_fields` error-detail support, rollback/compensation execution models, and retry-attempt metadata on direct tool-call responses
- current tool-call bridge schemas for tool-hub MCP/internal routes and business-tools execute routes
- admin-facing dashboard/knowledge/retrieval DTO baselines, knowledge-document detail/job-query read models, plus user-facing research-task, poster-task, and marketing-campaign DTO/list schemas for downstream OpenAPI alignment
- shared admin-audit DTOs plus a lightweight knowledge runtime snapshot schema for the live `knowledge-service` internal inspection routes, with owner-local source/document/integration sections intentionally kept opaque
- shared error catalog in `errors/error_codes.yaml`

Downstream supervisors should keep app-local DTOs in owned directories until a schema is reused across services or surfaces and promoted through the frozen-space workflow.
