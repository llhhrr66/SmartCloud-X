# API Conventions

## Envelope split: internal vs external

### Internal service-to-service HTTP
Shared internal APIs should prefer the `ApiEnvelope<T>` shape from `@smartcloud-x/common-schemas`:
- `success`: boolean
- `data`: payload or `null`
- `requestId`: optional correlation identifier
- `trace`: optional trace context when a downstream service returns it
- `error`: present on failures with `code`, `message`, optional `details`, and optional `retryable`; success responses may omit `error` or return `error: null`
- `meta`: optional non-domain metadata such as pagination or degraded mode flags; success responses may omit `meta` or return `meta: null`

This is the baseline for current in-repo internal services such as orchestrator, tool-hub, rag, and knowledge.

### External gateway-facing HTTP
Gateway-facing or public user-surface APIs must publish the canonical contract from spec sections `20.5.5`, `20.5.6`, and `20.13`:
- success: `CanonicalSuccessEnvelope<T>`
  - `code=0`
  - `message`
  - `data`
  - `request_id`
  - `timestamp`
- failure: `CanonicalErrorEnvelope`
  - numeric `code`
  - `message`
  - optional `error`
  - `request_id`
  - `timestamp`
  - optional `data=null` when gateway normalization keeps the field

Compatibility rule:
- internal services may keep `ApiEnvelope<T>` behind the gateway
- gateways or public owner services should normalize outbound payloads to the canonical external envelope
- admin surfaces published under `/api/v1/admin/**` follow the same canonical external envelope family
- clients may temporarily accept both formats during migration, but new public OpenAPI placeholders must document the canonical external contract first

## Contract-only access markers for auth/bootstrap routes
On auth/bootstrap routes where the primary spec describes access state instead of a concrete RBAC permission code, foundation freezes these `x-permission-code` markers:
- `anonymous`
- `authenticated:user`
- `authenticated:admin`

These markers are route-contract hints only. They are not RBAC permission codes and must not be persisted in `permissions[]` claims.

## Tracing and service-call headers
Service boundaries should preserve:
- `X-Request-Id`
- `X-Trace-Id`
- `X-Tenant-Id`
- `X-Caller-Service`

Conversation-aware flows should also preserve:
- `X-Conversation-Id`

Tool execution hops between orchestrator, tool-hub, and business-tools should also preserve:
- `X-Tool-Call-Id`
- `Idempotency-Key` for write or replay-sensitive operations

Admin write surfaces should additionally require:
- `X-Operator-Reason` with a short operator-supplied audit reason

Trusted internal aliases or private routes protected by `ALLOWED_INTERNAL_CALLERS` must additionally require:
- `X-Caller-Service`
- a service-local allow-list check against the shared `ALLOWED_INTERNAL_CALLERS` key
- a structured `403` with the published caller-forbidden code when the header is missing or rejected
- OpenAPI operations that declare `x-permission-code: service:internal.call` must document the shared `X-Caller-Service` header, either inline or via `./components.openapi.yaml#/components/parameters/XCallerServiceHeader`

The `TraceContext` JSON Schema is the baseline shared internal structure.

## Response headers
Current internal HTTP services standardize these response headers when available:
- `X-Request-Id`
- `X-Trace-Id`
- `X-App-Name`
- `X-App-Version`
- `X-Response-Time`

## Canonical user-facing SSE
Canonical user-facing event names are:
- `message.started`
- `agent.routed`
- `citation.delta`
- `tool.started`
- `tool.finished`
- `message.delta`
- `message.completed`
- `message.error`
- `heartbeat`

Current legacy/mock aliases may continue behind owned apps or mock layers, but they should normalize as follows before becoming public contract:
- `meta` -> `message.started`
- `route` -> `agent.routed`
- `tool_call` -> `tool.started`
- `tool_result` -> `tool.finished`
- `delta` -> `message.delta`
- `citation` -> `citation.delta`
- `done` -> `message.completed`
- `error` -> `message.error`
- `ping` -> `heartbeat`

`reasoning` remains an internal/debug event today. It is not part of the canonical public SSE contract and must not be required for stable user-facing integrations.

Current orchestrator-service baseline note:
- `POST /api/v1/sessions/{conversation_id}/messages/stream` currently emits the pre-gateway sequence `meta`, `reasoning`, `retrieval`, `tool_call`, `tool_result`, `delta`, `citation`, `done`
- that route is frozen as the service-level streaming contract for current downstream integration
- public gateway/user surfaces should normalize those events to the canonical family above before treating them as stable external contract
- `POST /api/v1/chat/completions` reuses the same event sequence when `stream=true`; when `stream=false` it returns an internal `ApiEnvelope<ChatCompletionResponse>`
- `POST /api/v1/chat/completions` additionally accepts additive compatibility fields `context`, `options`, `context_control`, and `client_meta`; non-stream responses may also expose top-level summary aliases `answer`, `citations`, `tool_calls`, `usage`, and `finish_reason` alongside the nested `response`

## Current orchestrator session lifecycle baseline
- `POST /api/v1/chat/sessions` plus `GET/PATCH /api/v1/chat/sessions/{conversation_id}` are now frozen as the current service-level session management surface for gateway or web alignment
- `POST /api/v1/chat/sessions/{conversation_id}/continue` is the frozen continuation route for clarification/confirmation resumes; callers may submit `field_values`, `confirm_tool_names`, and additive `session_context_patch` without relying on owner-local session keys
- orchestrator response/state payloads may also expose additive `pending_user_actions[]` advisory metadata copied from tool-level `user_action_hint` records; this metadata helps UI/gateway callers render structured continuation instructions but does not replace `pending_actions[]` or `/continue` semantics
- `POST /api/v1/chat/sessions/{conversation_id}/cancel` is the frozen cooperative cancellation route for the currently running message in a conversation
- `DELETE /api/v1/chat/sessions/{conversation_id}` is a soft delete: the underlying conversation transitions to `status=deleted`, but deleted sessions are hidden from normal list/detail/history flows and should subsequently surface `CHAT_CONVERSATION_NOT_FOUND`
- archived conversations must reject new `/api/v1/chat/completions` and retry execution until `POST /api/v1/chat/sessions/{conversation_id}/restore` succeeds
- retry appends a new user/assistant exchange while preserving prior history returned by `GET /api/v1/chat/sessions/{conversation_id}/messages`
- current promoted session-level error codes are `CHAT_CONVERSATION_NOT_FOUND`, `CHAT_MESSAGE_NOT_FOUND`, `CHAT_CONVERSATION_ARCHIVED`, `CHAT_CONVERSATION_RESTORE_INVALID`, `CHAT_CONTINUATION_NOT_AVAILABLE`, `CHAT_MESSAGE_NOT_RUNNING`, `CHAT_MESSAGE_CANCELLED`, and `CHAT_CONVERSATION_RUNNING`

## Idempotency
- write endpoints must document whether `Idempotency-Key` is required
- duplicate-write behavior must be defined in the owning service OpenAPI description
- idempotency semantics must not be implied only by code comments
- same `Idempotency-Key` plus the same normalized payload/context must replay the prior successful write result
- same `Idempotency-Key` plus a different normalized payload/context must surface the shared conflict case `4090001` / `IDEMPOTENCY_CONFLICT`
- retry-aware tool-call responses may include `attempts` so gateways and audit consumers can distinguish first-pass success from replay/retry paths
- async task creation routes such as poster generation and research task creation should return the first accepted task status on duplicate idempotent submissions

## Query replay and audit tags
- successful read/query tool responses may replay a prior successful result from a local or process-local cache during the current baseline phase
- shared tool contracts should surface replay annotations through `audit_tags`
- the current frozen replay tag is `cache-hit`
- `audit_tags` are additive execution hints for debugging, observability, and admin inspection; they must not be treated as authorization signals

## Tool-call result fidelity
- internal tool-hub direct tool-call responses may now surface additive `status`, `summary`, `result`, and `citations` fields alongside compatibility `message` and `data`
- during the current additive phase, `result` and `data` should carry the same payload when both are present so legacy callers remain compatible
- `summary` is the preferred human-readable execution text for trusted downstream consumers, while audit reads may persist additive `summary` and `citations` for debugging and admin inspection
- direct tool invoke responses may also surface additive `downstream_target` and `auth_requirements` metadata so trusted callers can inspect where the request was dispatched and what auth context the tool expects

## Tool-call audit status baseline
- the current success-path persisted audit status is `completed`
- legacy `success` remains an additive compatibility value in shared enums and filters while downstream readers normalize to the current `completed` baseline
- malformed required-field tool failures continue to use the frozen `invalid-payload` status

## Tool preflight / clarification baseline
- canonical tool preflight now publishes at `POST /api/v1/tools/preflight`, with `/internal/v1/tools/preflight` documented as the current compatibility alias used by orchestrator HTTP clients
- preflight returns a non-audited readiness model that can expose `missing_payload_fields`, `missing_payload_hints`, `missing_auth_context`, `required_permissions`, `requires_account_context`, `confirmation_required`, surfaced `session_context_bindings`, additive `user_action_hint`, and additive execution-policy metadata (`tool_mode`, `timeout_ms`, `idempotent`, `cache_ttl_seconds`)
- shared tool definitions may publish additive `input_field_hints` so orchestrator and trusted debug/admin consumers can turn missing-field checks into meaningful clarification prompts
- preflight validates readiness only: it must not execute the downstream tool and must not create a tool-call audit record

## Tool continuation hint baseline
- shared business-tools, tool-hub, and orchestrator contracts may expose additive `user_action_hint` metadata when a tool step needs caller follow-up
- the current frozen action families are `clarify-tool-input`, `collect-auth-context`, and `user-confirmation`
- tool-hub audit reads may persist the same hint object so trusted debugging/admin consumers can reconstruct continuation instructions without scraping human-readable summaries

## Provider-backed tool discovery
- when tool-hub or orchestrator is configured for HTTP transport, descriptor and readiness metadata may be sourced from downstream internal providers instead of local starter metadata only
- the current provider-facing business-tools discovery baseline includes `GET /internal/v1/tools/{tool_name}` and `POST /internal/v1/preflight/{tool_name}`
- the current structured internal-caller baseline also applies to `tool-hub-service` and `business-tools-service` internal aliases/routes that reuse `ALLOWED_INTERNAL_CALLERS`
- deployed transport overrides should use `BUSINESS_TOOLS_INTERNAL_API_PREFIX` and `TOOL_HUB_INTERNAL_API_PREFIX` instead of hardcoding alternate internal prefixes in app-local code

## Error codes
- all shared or cross-service internal error codes must be registered in `packages/common-schemas/errors/error_codes.yaml`
- current baseline uses stable internal string codes with numeric mappings for future alignment
- external/public numeric codes follow the primary spec ranges and may remain owner-documented in OpenAPI until a dedicated frozen public error catalog is promoted
- service-specific additions remain downstream until promoted

## Versioning
- shared path baselines should use explicit version segments such as `/v1`
- when a service keeps a legacy or internal compatibility alias, OpenAPI should document the canonical path and record aliases in descriptions or vendor extensions instead of treating all paths as equal primaries
- breaking contract changes must publish a new versioned schema or path instead of silently changing field meaning
- OpenAPI operations must declare `x-owner-service`, `x-error-codes`, `x-idempotency-required`, and `x-rate-limit-scope`

## Admin write/audit baseline
- external admin surfaces must publish under `/api/v1/admin/**`; current placeholder routes live in `openapi/admin-api.openapi.yaml`
- admin write routes should declare `x-audit-log-required` and `x-operator-reason-required`
- high-risk admin routes must also declare `x-confirm-token-required: true` and require a `confirm_token` request field
- the minimum audit field set remains `audit_id, operator_type, operator_id, resource_type, resource_id, action, reason, before_json, after_json, operator_ip, created_at`
- temporary gateway proxying to internal owner routes is allowed only when the admin OpenAPI description explicitly records the internal owner route used during the baseline phase
