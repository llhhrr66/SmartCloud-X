# Orchestrator Service Baseline

FastAPI-based starter for SmartCloud-X multi-agent orchestration.

## Scope
- supervisor-style intent routing with handoff planning and agent metadata
- baseline execution flow that actually invokes starter tools
- internal gateway-facing chat contract at `/internal/v1/orchestrator/chat`
- MySQL-first conversation/session management with message history, retry, archive, and restore flows, plus degraded JSON fallback
- service-level `/api/v1/chat/completions` alias for spec-shaped chat execution, including compatibility with `context`, `options`, `context_control`, and enriched non-stream response fields
- session state snapshot endpoint at `/api/v1/sessions/{conversation_id}/state`
- HTTP-first tool-hub integration with config-driven degraded local fallback on downstream connect failures
- A2A-compatible protocol surface with Agent Card discovery plus JSON-RPC `SendMessage` / `GetTask` routes
- HTTP tool-hub mode can now hydrate route/tool metadata from the running tool-hub registry, so planning stays aligned with provider-backed tool contracts instead of only local starter definitions
- MySQL/Redis-backed checkpoint/event/runtime baseline with degraded local fallback spools per conversation
- session-context continuity baseline that reuses prior tool outputs (for example `statement_no` and `open_ticket_id`) on follow-up turns
- versioned state snapshots with compact `tool_context` + derived `session_context`
- rollback execution endpoint for armed Saga compensation steps
- soft-delete session route at `DELETE /api/v1/chat/sessions/{conversation_id}`
- cooperative cancel route at `POST /api/v1/chat/sessions/{conversation_id}/cancel` for running chat-completion turns
- query-tool cache hit audit tags propagated from business-tools/tool-hub into orchestrator tool traces
- clarification-first tool planning/runtime that asks for missing required business fields before execution and hydrates later tool payloads from same-turn tool results
- finance routing now distinguishes status-style follow-ups from write intents, using `order.query_order` and `invoice.query_invoice` to answer refund / invoice progress questions from persisted session context
- finance routing now also supports `billing.query_instance_cost`, so a prior账单 turn can persist `primary_instance_id` and later answer “这台实例费用” without forcing the user to repeat the instance ID
- product-tech routing now adds `product.recommend_instance` for GPU / 大模型 sizing questions, so deployment-oriented turns return a concrete starter规格建议 alongside catalog and SOP hints
- product-tech routing now also adds `support.query_service_status` for 实例/服务状态异常追问, so technical-support turns can return a baseline health / incident summary and persist reusable diagnostic context into session state
- explicit human-escalation turns now prioritize `support.handoff_brief`, so “服务异常/投诉/转人工” requests can produce a reusable queue/severity/operator-notes packet without first blocking on unrelated finance/product queries
- technical-support incident requests that also ask for 工单 / 转人工 now stay on `product_tech_agent` first, then hand off to `finance_order_agent` for `ticket.create`, so the created ticket can reuse structured `service_*` and `human_handoff_*` context instead of a raw user-query echo
- ICP routing now distinguishes实名认证核验 from材料/状态 flows, using `icp.verify_subject` plus persisted contacts/subject context to support later备案提交 turns
- `/continue` flows can now resume composite ICP contact payloads with either flat keys (`contact_name`) or dotted keys (`contacts.contact_name`), letting callers progressively assemble `icp.submit_application.contacts`
- marketing planning now keeps poster/promotion-link/copy requests inside the marketing agent unless the user is also asking for real technical guidance, and the baseline supports poster generation, promotion-copy, promotion-link, and report-export starter flows end to end
- recommendation-aware marketing routing now treats “给 GPU 实例写文案/海报” 这类无既有推荐上下文的请求 as product grounding first, handing off from `product_tech_agent` to `ops_marketing_agent`; once `recommended_instance_summary` already exists in session context, later creative follow-ups stay on the marketing agent and reuse that sizing context directly
- route/state tool plans now carry execution-policy metadata such as `tool_mode`, `timeout_ms`, `idempotent`, and `cache_ttl_seconds`
- end-of-turn response review is now materialized as a real guard step, persisted into state snapshots, and can force `retry-or-escalate` when the orchestrator would otherwise return a response that violates basic handoff/tool/citation policy
- blocking tool steps now preserve structured `user_action_hint` metadata, and orchestrator responses/state snapshots aggregate additive `pending_user_actions[]` so `/continue` callers can resume from machine-readable clarification/auth/confirmation instructions
- `/continue` flows can now also accept `user_profile_patch` for auth-required tool resumes, and successful resumes persist additive `session_context.attributes.auth_profile` state so later turns can reuse collected account/permission context
- additive admin agent-config endpoints now expose database-backed `enabled`, `max_tool_calls`, `fallback_agent`, and `timeout_seconds` overrides; the router now honors `fallback_agent` for disabled-primary routing and the runtime enforces `timeout_seconds` as a cooperative per-agent execution budget
- APP_* + SMARTCLOUD_* compatible config loading with legacy route aliases

## Endpoints
- `GET /healthz`
- `GET /.well-known/agent-card.json`
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
- `POST /api/v1/a2a/jsonrpc`
- `POST /api/v1/sessions/{conversation_id}/messages`
- `GET /api/v1/sessions/{conversation_id}/state`
- `POST /api/v1/sessions/{conversation_id}/rollback`
- `POST /internal/v1/orchestrator/chat`

## Run
```bash
uvicorn app.main:app --reload --port 8010
```

## Notes
- dev now defaults `TOOL_HUB_TRANSPORT=http`, so a running tool-hub service becomes the mainline path; local execution is retained only as a degraded fallback for connect failures in local/dev/test
- staging/prod now require `TOOL_HUB_TRANSPORT=http`
- override downstream tool-hub internal paths with `TOOL_HUB_INTERNAL_API_PREFIX` when the deployed tool-hub does not use the local default `/internal/v1`
- confirmed write tools can be resumed from public or internal chat flows by sending `session_context.confirmed_tool_names`
- clarification or confirmation pauses can now be resumed with `POST /api/v1/chat/sessions/{conversation_id}/continue`, using `field_values` and `confirm_tool_names` instead of manually constructing `session_context`
- auth-required pauses can also be resumed through the same `/continue` route via `user_profile_patch`, and later turns can hydrate missing user/account/permission fields from the persisted runtime `auth_profile`
- continuation field binding now tolerates dotted composite keys such as `contacts.contact_phone`, mapping them onto the same shared session-context bindings used by flat aliases
- running chat-completion turns can now be cooperatively cancelled with `POST /api/v1/chat/sessions/{conversation_id}/cancel`, and cancelled runs are recorded in session history/state
- session state snapshots and the additive `GET /api/v1/chat/sessions/{conversation_id}/agent-routes` endpoint now expose a structured agent-route journal with handoff transitions, action_required state, and context highlights per step
- rollback requests execute armed compensation steps in reverse order via the tool-hub adapter
- shared runtime aliases such as `SMARTCLOUD_TIMEZONE`, `SMARTCLOUD_DEFAULT_LOCALE`, `SMARTCLOUD_REQUEST_TIMEOUT_MS`, and `SMARTCLOUD_SSE_HEARTBEAT_INTERVAL_SECONDS` are now honored by the config loader
- Redis-backed SSE replay keys now honor `SSE_EVENT_TTL_SECONDS` for retention instead of persisting indefinitely on the mainline
- per-agent admin overrides persist on the MySQL mainline when `SMARTCLOUD_MYSQL_DSN` is configured; `AGENT_CONFIG_STORE_PATH` is retained as the degraded fallback spool, and `DEFAULT_AGENT_TIMEOUT_SECONDS` supplies the baseline timeout surfaced on admin agent records and enforced by runtime execution
- shared header aliases such as `SMARTCLOUD_REQUEST_ID_HEADER`, `SMARTCLOUD_TRACE_ID_HEADER`, `SMARTCLOUD_CONVERSATION_ID_HEADER`, `SMARTCLOUD_CALLER_SERVICE_HEADER`, and `SMARTCLOUD_IDEMPOTENCY_KEY_HEADER` now drive internal header parsing/propagation
- local tool execution can reuse the business-tools Redis query cache; configure with `TOOL_QUERY_CACHE_ENABLED`, `TOOL_QUERY_CACHE_TTL_CAP_SECONDS`, and `SMARTCLOUD_REDIS_URL`
- `CONVERSATION_STORE_PATH`, `STATE_STORE_PATH`, `SSE_EVENT_STORE_PATH`, `AGENT_CONFIG_STORE_PATH`, `BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH`, and `BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH` now act as degraded fallback spools when MySQL/Redis is configured but unavailable
- HTTP tool-hub mode now preserves downstream `invalid-payload`, `idempotency-conflict`, and `confirmation-required` tool statuses instead of collapsing them into generic failures
- sequential tool execution now reuses successful `session_context_patch` data inside the same turn, so a billing query can feed a confirmed invoice request without waiting for a second message
- the same-turn handoff path now also reuses `recommended_instance_summary` into downstream marketing tools, so product sizing and creative generation can complete in one orchestrated turn without the user restating the recommended instance
- human handoff state is now persisted via `session_context.attributes.human_handoff_*`, making the generated escalation summary, queue, severity, and operator notes available to later admin/debug consumers
- service-status checks now persist `session_context.attributes.service_*` diagnostics such as status, incident code, summary, recommended action, region, and affected instance id, so later follow-up turns or人工交接 can reuse the same baseline incident context
- ticket creation now also persists richer `session_context.attributes.ticket_*` metadata such as queue, incident code, and related resources when the ticket was created from structured handoff / incident context
- the current timeout implementation is cooperative: the runtime stops further orchestration once an over-budget step returns, but does not hard-interrupt an already in-flight downstream call
- frozen shared contracts still need foundation promotion for the new internal chat/tool-call schemas
