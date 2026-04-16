# Shared Schema Catalog

## Common schemas
- `trace-context.schema.json`
- `api-envelope.schema.json`
- `error-info.schema.json`
- `pagination-meta.schema.json`
- `health-status.schema.json`
- `runtime-dependency-readiness.schema.json`
- `runtime-health-status.schema.json`
- `runtime-readiness-status.schema.json`
- `service-caller-context.schema.json`

## External canonical schemas
- `external/canonical-success-envelope.schema.json`
- `external/canonical-error-envelope.schema.json`
- `external/canonical-error-detail.schema.json`
- `external/offset-pagination.schema.json`
- `external/sse-event-envelope.schema.json`
- `external/auth/*.schema.json`

## Admin-facing DTO baselines
- `external/admin/admin-audit-record.schema.json`
- `external/admin/admin-audit-list-data.schema.json`
- `external/admin/dashboard-summary-data.schema.json`
- `external/admin/knowledge-base*.schema.json`
- `external/admin/knowledge-base-update-request.schema.json`
- `external/admin/knowledge-chunk-stats.schema.json`
- `external/admin/knowledge-document-detail-data.schema.json`
- `external/admin/knowledge-document*.schema.json`
- `external/admin/knowledge-chunk*.schema.json`
- `external/admin/async-job.schema.json`
- `external/admin/retrieval-*.schema.json`

## User-facing DTO baselines
- `external/user/marketing-campaign*.schema.json`
- `external/user/marketing-copy-*.schema.json`
- `external/user/poster-result-data.schema.json`
- `external/user/poster-task*.schema.json`
- `external/user/promotion-link-*.schema.json`
- `external/user/research-task-result-data.schema.json`
- `external/user/research-task-status-data.schema.json`
- `external/user/research-task*.schema.json`

## Internal DTO baselines
- `internal/auth/*.schema.json`
- `internal/knowledge/knowledge-runtime-snapshot.schema.json`
- `internal/orchestrator/*.schema.json`
- `internal/tool-hub/*.schema.json`
- `internal/business-tools/*.schema.json`

Highlighted promoted shared contracts:
- orchestrator routing/session DTOs now include scenes, runtime constraints, richer session context, session CRUD/history/chat-completion/continue/cancel DTOs, additive chat-completion compatibility fields, soft-delete response markers, handoff plans, tool plans, execution checkpoints, internal chat payloads, `AgentRouteRecord`, versioned session state snapshots with `session_context` + `agent_routes` + `tool_context`, additive lightweight `ResponseReview` / `ResponseReviewIssue` metadata on response/state surfaces, additive `pending_user_actions[]` continuation metadata, propagated tool-level `user_action_hint` on `ToolInvocation`, the `review_result` execution-event variant, the current `review-answer` checkpoint marker, Saga compensation stacks, current stream-event payload schemas for the live SSE route, and stored stream replay page/record schemas for message-event replays
- orchestrator continuation contracts now also include `UserProfilePatch`, additive `user_profile_patch` on `SessionContinueRequest`, and additive `user_profile_bindings` on shared auth-continuation hint models so auth-required tool pauses can resume without reconstructing a full upstream request
- tool-hub contracts now include `ToolDefinition`, `ToolExecutionContext`, `ToolInvocationRequest`, `ToolExecutionResult`, `ToolPreflightResult`, `ToolPreflightResponse`, current HTTP route-body aliases, MCP tool-list wrappers, a reusable `ToolUserActionHint` baseline, direct tool-call request/response models with additive fidelity fields (`status`, `summary`, `result`, `citations`) plus compatibility `message`/`data` aliases, compensation-call request/response models, tool-call audit records with additive `summary` / `citations`, `user_action_hint`, `input_field_hints`, `session_context_patch`, surfaced preflight `session_context_bindings`, execution-policy metadata (`tool_mode`, `timeout_ms`, `idempotent`, `cache_ttl_seconds`), `audit_tags`, `invalid-payload` audit status coverage, retry `attempts`, `missing_fields` error-detail support, and `ToolCompensationAction`
- tool-hub direct invoke contracts also include additive `downstream_target` and `auth_requirements` metadata, and shared audit enums now treat `completed` as the current success-path status while keeping `success` as a compatibility alias
- orchestrator agent contracts now include descriptor metadata (`version`, `owner`, `input_schema_version`, `output_schema_version`) plus additive `risk_flags` on `AgentExecutionResult`
- tool-definition contracts now also include additive `version`, `input_schema`, `output_schema`, `session_context_bindings`, `session_context_output_keys`, and `prerequisite_tool_names` discovery metadata alongside the existing hint-driven fields
- orchestrator planning contracts now also include dependency-aware tool/task/handoff metadata such as `depends_on_tool_call_ids`, `deferred_payload_fields`, session-context input/output keys, and per-tool `readiness`
- business-tools bridge contracts now include execute request/response payloads plus operator/subject context schemas, aligned execute-result fidelity fields (`tool_name`, `operation`, `status`, `summary`, `result`, `citations`) alongside compatibility `message`/`data` aliases, propagated `audit_tags`, additive `user_action_hint`, `missing_fields` error-detail support, compensation-execute request/response models, compensation metadata, and idempotency echo fields for the current tool-hub HTTP integration path
- external admin-facing contracts now include dashboard summary, knowledge-base/document/chunk, knowledge-base update request, document-detail chunk stats, async-job, retrieval-diagnostics/search-preview DTO baselines, plus admin auth bootstrap menu/session DTOs for gateway/admin alignment
- external admin-facing contracts now also include orchestrator admin-agent config record/list/update DTO baselines for the current process-local agent tuning surface
- shared knowledge-service inspection contracts now also include reusable `AdminAuditRecord` / `AdminAuditListData` DTOs plus a lightweight `KnowledgeRuntimeSnapshot` schema for the live internal audit-export/runtime-snapshot routes, while keeping owner-local source/document/integration sections opaque
- external user-facing contracts now include canonical HTTP envelopes plus reusable DTOs for marketing campaign/copy/promotion-link detail and history flows and research/poster task history baselines

## Shared catalogs
- `errors/error_codes.yaml`
- `FoundationErrorCode` / `foundationErrorCodes` exports in `@smartcloud-x/common-schemas` stay validator-synchronized with the YAML error catalog

## Registry surface
- `@smartcloud-x/common-schemas` publishes `schemaRegistry` as the stable path lookup for every frozen `*.schema.json` file under `packages/common-schemas/src/schemas`
- foundation validation now treats missing or stale `schemaRegistry` entries as a frozen-space regression

## Intended consumers
- orchestrator-service and tool-hub-service for immediate contract reuse
- business-tools-service for execute-route stability plus provider-backed descriptor/preflight discovery when tool-hub switches from local to HTTP transport
- web-user and future gateway/public specs for canonical response and task-history alignment
- rag-service and knowledge-service for request tracing continuity and common envelopes
- auth-user-service and gateway/service middleware for login bootstrap, shared account DTOs, and internal permission-check/cache-invalidation contracts
- downstream CI or validation tooling via root-level foundation scripts

## Change management
Do not overload the shared schemas with business-specific fields. Prefer additive, narrow schemas per cross-service concern and promote them only after review.
Do not create `packages/common-schemas/frontend/**` mirrors of frontend-sdk user-business typings until the underlying service contracts are promoted into frozen OpenAPI/common-schema space; until then, `packages/frontend-sdk/` may keep owned typing outlets that map from the published service-level contracts.
The current frontend-sdk-owned ICP history list contract for `GET /api/v1/icp/applications` remains deferred for the same reason: no backend-owned frozen service contract exists yet for foundation to promote.
