# Shared Schema Catalog

## Purpose

This catalog records **shared schema contract maturity**, not product completion.

A schema listed here may be:
- frozen and widely reusable,
- only a baseline shared DTO,
- still owner-defined downstream,
- or merely part of a draft contract surface.

Schema presence in `packages/common-schemas` or a reference from OpenAPI does **not** prove the underlying runtime behavior is fully delivered. Always cross-check code, tests, status docs, and runbooks.

## Maturity labels

| Label | Meaning |
| --- | --- |
| `implemented` | Shared contract is aligned to live code behavior and backed by direct code/test evidence. |
| `placeholder` | Reserved or draft schema slot; not field-complete and not implementation proof. |
| `baseline` | Reusable minimal/current schema for a live surface, but not target-state or field-final in all respects. |
| `owner-defined` | Payload family exists, but exact field ownership remains with downstream service owners instead of foundation-frozen shared schemas. |
| `frozen` | Stable shared schema intended for cross-service reuse; changes should go through contract review. |

## Contract maturity vs implementation completion

| Topic | Contract maturity question | Implementation completion question |
| --- | --- | --- |
| Shared schema | Is the JSON schema published and stable enough to reuse? | Do live code and tests prove the service behavior behind it? |
| OpenAPI ref | Is the referenced component explicit or still owner-defined/draft? | Is the referenced route actually implemented and verified? |

Do not collapse these questions into one.

## Root-level shared schemas

### Frozen shared schemas
These are the root-level schemas that should be reused first instead of creating parallel equivalents.

| Path | Maturity | Notes |
| --- | --- | --- |
| `packages/common-schemas/src/schemas/trace-context.schema.json` | frozen | Shared trace context across internal contracts. |
| `packages/common-schemas/src/schemas/api-envelope.schema.json` | frozen | Shared internal `ApiEnvelope` wrapper. |
| `packages/common-schemas/src/schemas/error-info.schema.json` | frozen | Shared internal error object. |
| `packages/common-schemas/src/schemas/pagination-meta.schema.json` | frozen | Shared pagination meta building block. |
| `packages/common-schemas/src/schemas/service-caller-context.schema.json` | frozen | Shared internal caller identity context. |
| `packages/common-schemas/src/schemas/runtime-readiness-status.schema.json` | frozen | Preferred root-level readiness body schema. Reuse this rather than defining a parallel readiness object elsewhere. |
| `packages/common-schemas/src/schemas/runtime-dependency-readiness.schema.json` | frozen | Preferred root-level downstream dependency readiness schema. |

### Baseline shared runtime schemas

| Path | Maturity | Notes |
| --- | --- | --- |
| `packages/common-schemas/src/schemas/health-status.schema.json` | baseline | Generic health/liveness status; useful but less specific than readiness. |
| `packages/common-schemas/src/schemas/runtime-health-status.schema.json` | baseline | Shared runtime-health baseline; not by itself proof that every service exposes the same payload. |

## External canonical schemas

### Frozen canonical envelope schemas
- `packages/common-schemas/src/schemas/external/canonical-success-envelope.schema.json`
- `packages/common-schemas/src/schemas/external/canonical-error-envelope.schema.json`
- `packages/common-schemas/src/schemas/external/canonical-error-detail.schema.json`
- `packages/common-schemas/src/schemas/external/offset-pagination.schema.json`
- `packages/common-schemas/src/schemas/external/sse-event-envelope.schema.json`

Maturity: **frozen**

These provide shared external envelope and pagination building blocks. They do not prove a given service has completed every external route using them.

### External auth schemas
- `packages/common-schemas/src/schemas/external/auth/*.schema.json`

Maturity: **baseline to frozen depending on DTO**

Use as shared account/login DTO references where already promoted. Do not infer that every alias route mentioned in OpenAPI is equally mature.

## Admin-facing DTO baselines

The following groups are currently best read as **baseline** admin DTO space unless a specific consumer and route are separately proven and frozen:
- `packages/common-schemas/src/schemas/external/admin/admin-audit-record.schema.json`
- `packages/common-schemas/src/schemas/external/admin/admin-audit-list-data.schema.json`
- `packages/common-schemas/src/schemas/external/admin/dashboard-summary-data.schema.json`
- `packages/common-schemas/src/schemas/external/admin/knowledge-base*.schema.json`
- `packages/common-schemas/src/schemas/external/admin/knowledge-base-update-request.schema.json`
- `packages/common-schemas/src/schemas/external/admin/knowledge-chunk-stats.schema.json`
- `packages/common-schemas/src/schemas/external/admin/knowledge-document-detail-data.schema.json`
- `packages/common-schemas/src/schemas/external/admin/knowledge-document*.schema.json`
- `packages/common-schemas/src/schemas/external/admin/knowledge-chunk*.schema.json`
- `packages/common-schemas/src/schemas/external/admin/async-job.schema.json`
- `packages/common-schemas/src/schemas/external/admin/retrieval-*.schema.json`

Important: these are shared DTOs or DTO baselines, not evidence that admin runtime behavior is fully complete.

## User-facing DTO baselines

The following groups are currently **baseline** shared DTO space:
- `packages/common-schemas/src/schemas/external/user/marketing-campaign*.schema.json`
- `packages/common-schemas/src/schemas/external/user/marketing-copy-*.schema.json`
- `packages/common-schemas/src/schemas/external/user/poster-result-data.schema.json`
- `packages/common-schemas/src/schemas/external/user/poster-task*.schema.json`
- `packages/common-schemas/src/schemas/external/user/promotion-link-*.schema.json`
- `packages/common-schemas/src/schemas/external/user/research-task-result-data.schema.json`
- `packages/common-schemas/src/schemas/external/user/research-task-status-data.schema.json`
- `packages/common-schemas/src/schemas/external/user/research-task*.schema.json`

## Internal DTO baselines

### Auth internal schemas
- `packages/common-schemas/src/schemas/internal/auth/*.schema.json`

Maturity: **baseline**

These cover internal auth validation, permission-check, and cache invalidation DTOs. Presence here does not by itself prove every internal auth flow is adopted by all callers.

### Knowledge internal schemas
- `packages/common-schemas/src/schemas/internal/knowledge/knowledge-runtime-snapshot.schema.json`

Maturity: **baseline**

This is a promoted runtime snapshot contract, not proof that knowledge indexing has reached full per-domain target state.

### Orchestrator internal schemas
- `packages/common-schemas/src/schemas/internal/orchestrator/*.schema.json`

Maturity: **baseline**, with some route/session/event contracts approaching implemented shared space where code/tests directly prove them.

Important limitation: orchestrator remains a baseline router overall. Do not read the existence of rich orchestration schemas as proof of full LangGraph-style orchestration.

### Tool-hub and business-tools internal schemas
- `packages/common-schemas/src/schemas/internal/tool-hub/*.schema.json`
- `packages/common-schemas/src/schemas/internal/business-tools/*.schema.json`

Maturity: **baseline**

## Readiness-related shared schemas

### Real schema locations
Use these existing files as the authoritative shared readiness schema set:

| Path | Maturity | Real usage note |
| --- | --- | --- |
| `packages/common-schemas/src/schemas/runtime-readiness-status.schema.json` | frozen | Root-level readiness body schema with `status`, `service`, `not_ready_components`, and `runtime`. |
| `packages/common-schemas/src/schemas/runtime-dependency-readiness.schema.json` | frozen | Root-level dependency readiness schema with `ready`, `status`, `mode`, `service`, `httpStatus`, `notReadyComponents`, and `error`. |
| `packages/common-schemas/src/schemas/runtime-health-status.schema.json` | baseline | Runtime health payload baseline. |
| `packages/common-schemas/src/schemas/health-status.schema.json` | baseline | Generic health summary baseline. |

### Implementation evidence note
Readiness implementation must be proven from service code and tests, not from schema presence alone.

Current code-backed readiness routes exist in:
- `apps/auth-user-service/app/routes.py`
- `apps/knowledge-service/app/api/routes/health.py`
- `apps/rag-service/app/api/routes/health.py`
- `apps/gateway-service/app/api/routes/health.py`
- `apps/orchestrator-service/app/api/routes/health.py`

Current evidence explicitly referenced by status/review docs includes:
- gateway readiness aggregation tests
- orchestrator readiness tests
- review notes requiring docs to distinguish readiness contract maturity from implementation truth

Do not create a second readiness schema family under `internal/runtime/**` or similar unless the root-level schemas are proven insufficient.

## Retrieval-related shared schemas

### Real schema locations

| Path | Maturity | Notes |
| --- | --- | --- |
| `packages/common-schemas/src/schemas/internal/rag/retrieval-result.schema.json` | baseline | Shared internal retrieval result contract for rag → orchestrator exchange. |
| `packages/common-schemas/src/schemas/internal/orchestrator/stream-retrieval-event-data.schema.json` | baseline | Shared retrieval event payload for orchestrator SSE/replay. |
| `packages/common-schemas/src/schemas/internal/orchestrator/stream-retrieval-source.schema.json` | baseline | Shared retrieval source item used by orchestrator stream events. |
| `packages/common-schemas/src/schemas/external/admin/retrieval-diagnostics-data.schema.json` | baseline | Admin retrieval diagnostics DTO. |
| `packages/common-schemas/src/schemas/external/admin/retrieval-search-preview-data.schema.json` | baseline | Admin retrieval preview DTO. |
| `packages/common-schemas/src/schemas/external/admin/retrieval-search-source.schema.json` | baseline | Admin retrieval source DTO. |

### What is implemented vs what is only baseline

Implemented by code/tests:
- orchestrator now has code/test-backed real retrieval/citation success, degraded, hard-failure, and stream-event paths
- rag now has code/test-backed degraded/no-citation behavior and retrieval-route degraded handling

Still only baseline/shared-contract level:
- the retrieval shared DTOs above
- additive retrieval fields that may continue evolving
- admin retrieval diagnostics DTOs

Still not safe to claim from schema alone:
- that any retrieval-looking field equals trustworthy citation proof
- that product chat is complete just because retrieval schemas exist
- that knowledge has fully exited single-baseline or mixed index mode

### Required documentation guardrails
- `baseline://router-retrieval` is not valid citation evidence and must not be documented as a successful retrieval source.
- Gateway does not repair orchestrator event semantics; retrieval event meaning remains orchestrator-owned.
- Knowledge must not be documented as fully per-domain unless runtime evidence proves complete cutover.

These guardrails align with:
- `docs/status/supervisor-orchestrator-status.md`
- `docs/status/supervisor-knowledge-rag-status.md`
- `docs/reviews/known-issues.md`
- `docs/runbooks/release-readiness.md`

## Highlighted promoted shared contracts
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
