# Orchestrator Service Baseline

FastAPI-based starter for SmartCloud-X multi-agent orchestration.

## Scope
- supervisor-style intent routing with handoff planning and agent metadata
- baseline execution flow that actually invokes starter tools
- internal gateway-facing chat contract at `/internal/v1/orchestrator/chat`
- in-memory conversation/session management baseline with message history, retry, archive, and restore flows
- service-level `/api/v1/chat/completions` alias for spec-shaped chat execution, including compatibility with `context`, `options`, `context_control`, and enriched non-stream response fields
- session state snapshot endpoint at `/api/v1/sessions/{conversation_id}/state`
- local or HTTP tool-hub integration with config-driven transport
- HTTP tool-hub mode can now hydrate route/tool metadata from the running tool-hub registry, so planning stays aligned with provider-backed tool contracts instead of only local starter definitions
- process-local checkpoint/event/saga-compensation baseline with optional file-backed persistence per conversation
- session-context continuity baseline that reuses prior tool outputs (for example `statement_no` and `open_ticket_id`) on follow-up turns
- versioned in-memory state snapshots with compact `tool_context` + derived `session_context`
- rollback execution endpoint for armed Saga compensation steps
- soft-delete session route at `DELETE /api/v1/chat/sessions/{conversation_id}`
- cooperative cancel route at `POST /api/v1/chat/sessions/{conversation_id}/cancel` for running chat-completion turns
- query-tool cache hit audit tags propagated from business-tools/tool-hub into orchestrator tool traces
- clarification-first tool planning/runtime that asks for missing required business fields before execution and hydrates later tool payloads from same-turn tool results
- finance routing now distinguishes status-style follow-ups from write intents, using `order.query_order` and `invoice.query_invoice` to answer refund / invoice progress questions from persisted session context
- ICP routing now distinguishes实名认证核验 from材料/状态 flows, using `icp.verify_subject` plus persisted contacts/subject context to support later备案提交 turns
- `/continue` flows can now resume composite ICP contact payloads with either flat keys (`contact_name`) or dotted keys (`contacts.contact_name`), letting callers progressively assemble `icp.submit_application.contacts`
- marketing planning now keeps poster/promotion-link/copy requests inside the marketing agent unless the user is also asking for real technical guidance, and the baseline supports poster generation, promotion-copy, promotion-link, and report-export starter flows end to end
- route/state tool plans now carry execution-policy metadata such as `tool_mode`, `timeout_ms`, `idempotent`, and `cache_ttl_seconds`
- end-of-turn response review is now materialized as a real guard step, persisted into state snapshots, and can force `retry-or-escalate` when the orchestrator would otherwise return a response that violates basic handoff/tool/citation policy
- blocking tool steps now preserve structured `user_action_hint` metadata, and orchestrator responses/state snapshots aggregate additive `pending_user_actions[]` so `/continue` callers can resume from machine-readable clarification/auth/confirmation instructions
- additive admin agent-config endpoints now expose process-local `enabled`, `max_tool_calls`, `fallback_agent`, and `timeout_seconds` overrides; the router now honors `fallback_agent` for disabled-primary routing and the runtime enforces `timeout_seconds` as a cooperative per-agent execution budget
- APP_* + SMARTCLOUD_* compatible config loading with legacy route aliases

## Endpoints
- `GET /healthz`
- `GET /api/v1/agents` (`/api/orchestrator/v1/agents` compatibility alias)
- `GET /api/v1/admin/agents`
- `PATCH /api/v1/admin/agents/{agent_code}`
- `POST /api/v1/route`
- `POST /api/v1/chat/sessions`
- `GET /api/v1/chat/sessions`
- `GET /api/v1/chat/sessions/{conversation_id}`
- `GET /api/v1/chat/sessions/{conversation_id}/messages`
- `GET /api/v1/chat/sessions/{conversation_id}/agent-routes`
- `PATCH /api/v1/chat/sessions/{conversation_id}`
- `POST /api/v1/chat/sessions/{conversation_id}/archive`
- `POST /api/v1/chat/sessions/{conversation_id}/restore`
- `DELETE /api/v1/chat/sessions/{conversation_id}`
- `POST /api/v1/chat/sessions/{conversation_id}/retry`
- `POST /api/v1/chat/sessions/{conversation_id}/continue`
- `POST /api/v1/chat/sessions/{conversation_id}/cancel`
- `POST /api/v1/chat/completions`
- `POST /api/v1/sessions/{conversation_id}/messages`
- `GET /api/v1/sessions/{conversation_id}/state`
- `POST /api/v1/sessions/{conversation_id}/rollback`
- `POST /internal/v1/orchestrator/chat`

## Run
```bash
uvicorn app.main:app --reload --port 8010
```

## Notes
- default tool execution mode is local via `apps/business-tools`
- set `TOOL_HUB_TRANSPORT=http` to call a running tool-hub service
- override downstream tool-hub internal paths with `TOOL_HUB_INTERNAL_API_PREFIX` when the deployed tool-hub does not use the local default `/internal/v1`
- confirmed write tools can be resumed from public or internal chat flows by sending `session_context.confirmed_tool_names`
- clarification or confirmation pauses can now be resumed with `POST /api/v1/chat/sessions/{conversation_id}/continue`, using `field_values` and `confirm_tool_names` instead of manually constructing `session_context`
- continuation field binding now tolerates dotted composite keys such as `contacts.contact_phone`, mapping them onto the same shared session-context bindings used by flat aliases
- running chat-completion turns can now be cooperatively cancelled with `POST /api/v1/chat/sessions/{conversation_id}/cancel`, and cancelled runs are recorded in session history/state
- session state snapshots and the additive `GET /api/v1/chat/sessions/{conversation_id}/agent-routes` endpoint now expose a structured agent-route journal with handoff transitions, action_required state, and context highlights per step
- rollback requests execute armed compensation steps in reverse order via the tool-hub adapter
- shared runtime aliases such as `SMARTCLOUD_TIMEZONE`, `SMARTCLOUD_DEFAULT_LOCALE`, `SMARTCLOUD_REQUEST_TIMEOUT_MS`, and `SMARTCLOUD_SSE_HEARTBEAT_INTERVAL_SECONDS` are now honored by the config loader
- per-agent admin overrides can optionally persist via `AGENT_CONFIG_STORE_PATH`, while `DEFAULT_AGENT_TIMEOUT_SECONDS` supplies the baseline timeout surfaced on admin agent records and enforced by runtime execution
- shared header aliases such as `SMARTCLOUD_REQUEST_ID_HEADER`, `SMARTCLOUD_TRACE_ID_HEADER`, `SMARTCLOUD_CONVERSATION_ID_HEADER`, `SMARTCLOUD_CALLER_SERVICE_HEADER`, and `SMARTCLOUD_IDEMPOTENCY_KEY_HEADER` now drive internal header parsing/propagation
- local tool execution can reuse the business-tools query cache; configure with `TOOL_QUERY_CACHE_ENABLED` and `TOOL_QUERY_CACHE_TTL_CAP_SECONDS`
- optional file-backed local durability can be enabled with `CONVERSATION_STORE_PATH`, `STATE_STORE_PATH`, `BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH`, and `BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH`
- HTTP tool-hub mode now preserves downstream `invalid-payload`, `idempotency-conflict`, and `confirmation-required` tool statuses instead of collapsing them into generic failures
- sequential tool execution now reuses successful `session_context_patch` data inside the same turn, so a billing query can feed a confirmed invoice request without waiting for a second message
- the current timeout implementation is cooperative: the runtime stops further orchestration once an over-budget step returns, but does not hard-interrupt an already in-flight downstream call
- frozen shared contracts still need foundation promotion for the new internal chat/tool-call schemas
