# Foundation Baseline Contract

This document defines the frozen-space baseline established by `supervisor-foundation`.

## Scope completed
- root workspace configuration files
- common package helpers for service ownership, assigned contract-placeholder service identities, reserved internal callers, shared supervisor-name helpers, and shared request/response headers
- common schema package with reusable baseline JSON Schemas for:
  - internal orchestrator, tool-hub, business-tools, and auth validation/check contracts
  - canonical external HTTP envelopes, auth/account DTOs, and user-facing task/list DTOs
  - session-state snapshots, execution events, and Saga compensation metadata
- common auth package with shared roles, starter permissions, internal caller helpers, auth-state route markers, and permission-check utilities
- OpenAPI baseline specs for cross-service alignment, shared components, current internal service route baselines, user-facing marketing/research placeholders, and auth-user-service placeholder routes
- supervisor-foundation logs and status artifacts

## Downstream usage rules
- downstream supervisors may consume these paths but must not directly edit frozen-space files
- any required additions to shared contracts should be proposed under `docs/contracts/change-requests/`
- business-specific DTOs should remain inside each owned app until promoted into shared space by foundation
- frozen-space baselines should track repository reality first; target-architecture upgrades that would break current consumers must go through a change request

## Promotion criteria into frozen space
A downstream concern should only move into shared packages when all are true:
1. used by at least two owned surfaces or services
2. naming and ownership are stable enough for reuse
3. compatibility expectations are documented before or during promotion

## Current baseline notes
- shared JSON Schemas now cover both internal service contracts and the canonical external user-facing HTTP envelope family required by the primary spec
- internal orchestrator schemas now include `session_context.confirmed_tool_names`, `state_snapshot`, `ExecutionEvent`, `SagaCompensationStep`, and `SessionStateSnapshot`
- frozen tool contracts now include `ToolCompensationAction`, `compensation`, and `idempotency_key` metadata across orchestrator, tool-hub, and business-tools bridge flows
- frozen orchestrator streaming contracts now cover the current SSE event payloads and emitted `meta -> reasoning -> retrieval -> tool_call -> tool_result -> delta -> citation -> done` sequence used by the live orchestrator baseline
- frozen orchestrator session-management contracts now cover the current `POST/GET/PATCH/DELETE /api/v1/chat/sessions*`, `GET /api/v1/chat/sessions/{conversation_id}/messages`, `POST /api/v1/chat/sessions/{conversation_id}/retry`, and `POST /api/v1/chat/completions` DTO/route baseline used by the live in-memory session store
- frozen chat-completion contracts now also cover additive request compatibility fields (`context`, `options`, `context_control`, `client_meta`) plus the top-level non-stream response aliases `answer`, `citations`, `tool_calls`, `usage`, and `finish_reason`
- frozen orchestrator response/state contracts now also cover lightweight response-review metadata (`review.status`, `review.summary`, `review.issues[]`, `review.requires_escalation`), the additive `review_result` execution-event variant, and the current `review-answer` checkpoint marker used by the live orchestrator baseline
- frozen tool-hub contracts now cover direct tool-call response fidelity (`status`, `summary`, `result`, `citations`) with compatibility `message`/`data` aliases plus audit read models for `GET /api/v1/tool-calls` and `GET /api/v1/tool-calls/{tool_call_id}`, including additive audit `summary`/`citations`, retry `attempts`, propagated `audit_tags`, and the current query-cache replay annotation baseline (`cache-hit`) on direct tool-call responses and audit records
- frozen tool bridge contracts now also document the current malformed-payload baseline: in-band code `4001001`, message `invalid tool payload`, audit status `invalid-payload`, and `missing_fields` error-detail hints for required-field failures
- frozen tool continuation contracts now also cover additive `user_action_hint` metadata across business-tools, tool-hub, and orchestrator tool invocation flows plus aggregated `pending_user_actions[]` advisory continuation data on orchestrator response/state payloads
- frozen business-tools execute contracts now also align with the richer shared `ToolExecutionResult` fidelity fields (`tool_name`, `operation`, `status`, `summary`, `result`, `citations`) while keeping `message` and `data` as additive compatibility aliases for older callers
- frozen tool-hub preflight contracts now document the current clarification-first baseline: additive `input_field_hints`, canonical `POST /api/v1/tools/preflight` with `/internal/v1/tools/preflight` alias, surfaced `session_context_bindings`, and shared readiness/execution-policy fields used to stop before execution when payload/auth/confirmation blockers exist
- internal `ApiEnvelope<T>` now treats omitted and explicit `error: null` / `meta: null` as equivalent success-envelope states, matching the live orchestrator/knowledge success baseline
- canonical user-facing task/list baselines now exist for research tasks, poster tasks, and marketing campaign history views so downstream web integration can stop relying on undocumented empty-state fallbacks
- canonical user-facing compatibility baselines now also exist for research task status/result reads and poster result reads so downstream web integration can use the owner-published helper routes without app-local DTO guessing
- canonical user-facing marketing copy and promotion-link DTO/route baselines now exist for both generation and persisted artifact history/detail reads, so downstream web integration can stop relying on app-local marketing payload guesses or browser-local registries
- shared auth starter permissions now include the current user-web business domains (`order`, `ticket`, `icp`, `marketing`, `research`) requested by downstream consumers
- frozen auth profile contracts now allow `avatar_url=null` when no avatar is configured, and auth OpenAPI now documents the current mission-wording compatibility aliases for profile/password helper routes
- shared API conventions now explicitly separate internal `ApiEnvelope<T>` usage from canonical external `code/message/data/request_id/timestamp` contracts
- `@smartcloud-x/common-schemas` now treats `schemaRegistry` as a complete frozen lookup surface for every published `*.schema.json`, and root validation now rejects missing/stale registry entries so downstream tooling can resolve promoted contracts without path guessing
- shared runtime config now also reserves `ALLOWED_INTERNAL_CALLERS` as the service-local allow-list key reused by trusted orchestrator/tool-hub/business-tools internal routes
- OpenAPI files in `openapi/` now reserve the current known route surfaces for orchestrator, tool-hub, business-tools, rag-service, knowledge-service, marketing-service, and research-service
- frontend surfaces may temporarily keep app-local DTO mirrors and API adapters while `packages/frontend-sdk/` adoption is still being rolled out by its assigned owner; those fallbacks must still follow the published frozen OpenAPI/contracts instead of inventing parallel names
- foundation is intentionally not creating `packages/common-schemas/frontend/**` yet; frontend-sdk may keep owned user-business typing outlets until the backing billing/order/refund/ticket/ICP/file/citation-detail service contracts are promoted through frozen OpenAPI/common-schema baselines
- frozen rag/knowledge placeholders now track the live `POST /api/rag/v1/diagnose` and `GET /api/knowledge/v1/ingestions`, `GET /api/knowledge/v1/overview`, `POST /api/knowledge/v1/catalog:bootstrap` routes instead of lagging behind current service reality
- rag-service and knowledge-service health OpenAPI baselines now match the current envelope-based implementations instead of incorrectly documenting bare `HealthStatus` payloads
- the shared error catalog now includes the current orchestrator session lifecycle codes for missing conversations/messages and archived/invalid-restore flows, so session-management routes no longer rely on undocumented service-local string codes
- the error catalog lives at `packages/common-schemas/errors/error_codes.yaml` and now includes `ORCH_SESSION_STATE_NOT_FOUND`, `ORCH_TOOL_CALL_NOT_FOUND`, and `IDEMPOTENCY_CONFLICT` for the published state, audit, and replay-conflict baselines

## Latest additive baseline updates
- shared runtime/header config now reserves `X-Tool-Call-Id`, `Idempotency-Key`, and `X-Operator-Reason` naming in `.env.example` and `@smartcloud-x/common`; shared caller/trace contexts now expose those propagated values as additive fields
- frozen internal OpenAPI routes that declare `x-permission-code: service:internal.call` now also publish the shared `X-Caller-Service` header requirement, and root validation cross-checks shared env/header constants against `.env.example`, shared runtime docs, and `openapi/components.openapi.yaml` so the baseline cannot drift silently
- `@smartcloud-x/common` now freezes a platform service registry that includes active services, the assigned-but-still-placeholder auth/marketing/research services owned by `supervisor-auth-marketing-research`, and the reserved `gateway-service` identity so OpenAPI `x-owner-service` values and internal caller names stay aligned
- `@smartcloud-x/common` now also freezes the full seven-supervisor workspace registry, split into service-owning and shared-scope supervisor helpers so root tooling can align `supervisor-frontend-sdk` and `supervisor-integration-qa` with `docs/contracts/supervisor-ownership.md`
- shared auth now includes canonical admin RBAC codes from spec section `20.14`; `admin:knowledge.read/write` remain compatibility aliases that normalize to `admin:kb.read/write`
- shared schemas/OpenAPI now cover orchestrator rollback plus tool-hub/business-tools compensation execution contracts, including the `compensation_result` execution-event variant
- frozen admin API placeholders now exist for dashboard summary, knowledge/document management, search preview, and retrieval diagnostics at `openapi/admin-api.openapi.yaml`
- frozen `openapi/auth-user-service.openapi.yaml` now covers user login/account bootstrap, admin auth bootstrap, and internal token-validation/permission-check/cache-invalidation routes required by the primary spec and current web-user integration
- temporary gateway allowances for starter-catalog bootstrap and answer preview are documented in `docs/contracts/shared/admin-api-baseline.md` until dedicated admin routes are promoted
- runtime-context propagation is now part of the frozen baseline: tool responses may emit `session_context_patch`, and session-state snapshots may expose versioned `session_context` plus compact `tool_context` previews
- soft-deleted orchestrator sessions now have a frozen `SessionDeleteResponse` marker contract; deleted conversations are hidden from normal list/detail/history reads and later reads should surface `CHAT_CONVERSATION_NOT_FOUND`
- frozen knowledge-service placeholders now also track the live `GET /api/knowledge/v1/imports:preview` and `POST /api/knowledge/v1/files:ingest` routes instead of leaving the current file-import surface undocumented
- frozen knowledge-service placeholders now also track the live `GET /api/knowledge/v1/admin/audit-records` and `GET /api/knowledge/v1/snapshot` inspection routes, and shared schemas now expose reusable admin-audit DTOs plus a lightweight `KnowledgeRuntimeSnapshot` baseline for the stable parts of that payload
- shared runtime config now reserves `SMARTCLOUD_CORS_ALLOWED_ORIGINS` because the current browser-facing knowledge/rag surfaces already depend on a shared origin allow-list
- frozen admin API placeholders now also track the live `GET /api/v1/admin/knowledge-documents/{doc_id}` and `GET /api/v1/admin/jobs/{job_id}` routes used by the current knowledge-service admin baseline
- frozen admin API placeholders now also track the live `PATCH /api/v1/admin/knowledge-bases/{kb_id}` route used by the current knowledge-service/web-admin settings baseline
- shared orchestrator/tool metadata schemas now cover additive agent `version/owner/input_schema_version/output_schema_version`, `AgentExecutionResult.risk_flags`, and tool-definition `version/input_schema/output_schema` metadata already emitted by owner services
- shared dependency-aware planning contracts now also cover tool-definition session-context bindings/dependency metadata plus orchestrator tool/task/handoff fields for deferred payloads, tool-call dependencies, session-context input/output keys, and readiness inspection
- shared orchestrator state contracts now also expose ordered `agent_routes` journals plus the additive `GET /api/v1/chat/sessions/{conversation_id}/agent-routes` inspection route
- frozen orchestrator session-management contracts now also cover the live `POST /api/v1/chat/sessions/{conversation_id}/continue` and `POST /api/v1/chat/sessions/{conversation_id}/cancel` routes plus the current continuation/cancellation lifecycle error codes
- root/runtime baselines now also reserve `BUSINESS_TOOLS_INTERNAL_API_PREFIX` and `TOOL_HUB_INTERNAL_API_PREFIX`, and frozen business-tools OpenAPI now tracks the live provider-backed `GET /internal/v1/tools/{tool_name}` and `POST /internal/v1/preflight/{tool_name}` discovery routes used by HTTP transport
- frozen tool-hub direct invoke contracts now also align to the live additive `downstream_target` / `auth_requirements` metadata, and audit baselines accept the current success-path stored `completed` status
- nullable shared admin/research read models now align more closely with the current owner implementations so optional no-error/no-result fields may be emitted as explicit `null`
- root engineering scaffolding validation now also covers all seven supervisor run/prompt entrypoints and the README/registry alignment for `supervisor-auth-marketing-research`, `supervisor-frontend-sdk`, and `supervisor-integration-qa`
- root engineering scaffolding validation now also rejects blank change-request result fields and stale generated source artifacts inside the foundation-owned contract packages
