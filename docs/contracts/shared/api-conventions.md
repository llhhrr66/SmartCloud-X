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

This is the baseline for current in-repo internal services such as orchestrator, rag, and knowledge.

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
- readiness routes are probe contracts, not public business DTOs; they may return direct JSON instead of canonical envelope when the owner service already uses that probe style
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
- optional scope members such as `conversationId`, `userId`, `tenantId`, `callerService`, `toolCallId`, `idempotencyKey`, and `operatorReason` may be omitted or explicit `null` when that context is unknown or not applicable
- downstream validators and consumers should treat missing and explicit `null` optional trace members as equivalent unknown-context states

## Response headers
Current internal HTTP services standardize these response headers when available:
- `X-Request-Id`
- `X-Trace-Id`
- `X-App-Name`
- `X-App-Version`
- `X-Response-Time`

## Health and readiness payload boundaries
Runtime probe payloads should keep the following semantics aligned with `docs/contracts/shared/runtime-health.md`:
- `/healthz`
  - primary fields: `status`, `service`, optional `runtime_mode`, optional `degraded_components`, optional `runtime`
  - `status` uses `ok` / `degraded`
- `/readyz`
  - primary fields: `status`, `service`, optional `runtime_mode`, `not_ready_components`, `runtime`
  - `status` uses `ready` / `not_ready`
- downstream probe sections should use nested `dependencyReadiness` objects with `ready`, `status`, `mode`, `service`, optional `httpStatus`, optional `notReadyComponents`, optional `error`
- gateway readiness aggregation may wrap its probe result in the external canonical envelope, but owner-service `/readyz` routes may return direct JSON readiness bodies

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

Legacy or internal orchestrator event names may continue to exist on service-local streaming routes, but public gateway/user surfaces should normalize them before treating them as stable external contract:
- `meta` -> `message.started`
- `route` -> `agent.routed`
- `tool_call` -> `tool.started`
- `tool_result` -> `tool.finished`
- `delta` -> `message.delta`
- `citation` -> `citation.delta`
- `done` -> `message.completed`
- `error` -> `message.error`
- `ping` -> `heartbeat`

### Retrieval and citation boundaries
The current streaming baseline distinguishes internal retrieval evidence from public citation rendering:
- `retrieval`
  - currently a real internal event in orchestrator streaming
  - should represent retrieval execution state and sources derived from actual retrieval results, not placeholder success markers
  - may include fields such as `query`, `top_k`, `degraded`, `backend_used`, and `sources[]`
  - remains primarily an internal/service-level event unless a gateway explicitly projects it into a public event family
- `citation` / `citation.delta`
  - citation payloads should be derived from real retrieval sources or tool-backed evidence, not synthetic success placeholders
  - compatibility `citations[]` summaries may remain additive, but source-of-truth evidence should come from structured retrieval sources where available
  - gateway citation caching should only treat citation events backed by actual source entries as successful citation material
- `message.error`
  - the canonical streaming failure event for user-facing consumers
  - should carry structured fields such as `code`, `message`, optional `retryable`, and optional `details`
  - should be used when orchestration or downstream retrieval fails in-stream instead of implying success through empty or synthetic citation output

`reasoning` remains an internal/debug event today. It is not part of the canonical public SSE contract and must not be required for stable user-facing integrations.

## Current orchestrator streaming baseline
- orchestrator service-level streaming still emits the internal sequence `meta`, `reasoning`, `retrieval`, `tool_call`, `tool_result`, `delta`, `citation`, `done`, with `message.error` used for structured in-stream failures when needed
- this service-level sequence is a real current implementation detail and may be consumed by trusted internal integrations
- gateway or frontend public contracts should depend on the canonical family, not on raw internal names, unless an owner explicitly freezes a lower-level route contract
- `retrieval` is now expected to reflect real retrieval results and degraded state where applicable; it must not be documented as if placeholder retrieval sources were equivalent to verified retrieval evidence
- `POST /api/v1/chat/completions` may reuse the same stream sequence when `stream=true`; when `stream=false` it returns a non-stream response instead

## Current orchestrator session lifecycle baseline
- `POST /api/v1/chat/sessions` plus `GET/PATCH /api/v1/chat/sessions/{conversation_id}` are now frozen as the current service-level session management surface for gateway or web alignment
- `POST /api/v1/chat/sessions/{conversation_id}/continue` is the frozen continuation route for clarification/confirmation resumes; callers may submit `field_values`, `confirm_tool_names`, additive `session_context_patch`, and additive `user_profile_patch` without relying on owner-local session keys
- orchestrator response/state payloads may also expose additive `pending_user_actions[]` advisory metadata copied from tool-level `user_action_hint` records; this metadata helps UI/gateway callers render structured continuation instructions but does not replace `pending_actions[]` or `/continue` semantics
- auth-related `user_action_hint` / `pending_user_actions[]` records may also expose additive `user_profile_bindings` so continuation clients know which `/continue.user_profile_patch` fields can satisfy missing user/account/role/permission context
- current orchestrator baseline may persist collected continuation auth/profile values into `session_context.attributes.auth_profile` as a runtime convenience layer for later turns; this does not change external auth ownership or token semantics
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

## Error codes
- all shared or cross-service internal error codes must be registered in `packages/common-schemas/errors/error_codes.yaml`
- external/public numeric codes follow the primary spec ranges and may remain owner-documented in OpenAPI until a dedicated frozen public error catalog is promoted
- service-specific additions remain downstream until promoted
