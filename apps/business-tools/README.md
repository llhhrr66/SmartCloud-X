# Business Tools Baseline

Owned baseline assets for SmartCloud-X business tool domains.

## Included
- Python interface definitions for business tools
- local invocation/result contracts used by orchestrator and tool-hub
- spec-aligned starter tool catalog (`product.recommend_instance`, `billing.query_statement`, `billing.create_invoice`, `order.create_refund`, `ticket.*`, `icp.*`, `marketing.*`, `research.*`)
- product-tech starter flows now also include `support.query_service_status`, so instance/service异常追问 can return a baseline health / incident summary before deciding whether to继续排查或转人工
- finance starter flows now also include `billing.query_instance_cost`, so billing follow-up turns can answer “某个实例费用” with a concrete per-instance cost breakdown
- finance starter flows now also include `order.query_order` and `invoice.query_invoice` for post-payment / post-invoice status follow-up turns
- ICP starter flows now include `icp.verify_subject` so orchestrator/tool-hub can baseline备案实名认证 checks and persist verified subject/contact context for later submit flows
- ICP submit/verification flows now preserve richer subject/contact state such as `certificate_no`, `contact_email`, and the assembled `contacts` object so follow-up `/continue` turns can satisfy composite备案联系人 inputs incrementally
- marketing starter flows now include poster-brief generation, poster asset generation, promotion-copy generation, and tracked promotion-link generation, and research starter flows now include report export artifacts
- marketing flows now also understand additive `product_summary` / recommendation context, so copy, campaign lookup, and poster brief generation can reuse a prior GPU sizing recommendation instead of falling back to generic “GPU” wording
- compensation metadata for confirmed write actions so orchestrator can build a Saga rollback stack
- session-context patch metadata on tool results so orchestrator can carry forward billing/ticket/ICP state across turns
- preflight metadata and `input_field_hints` so orchestrator/tool-hub can ask for missing business inputs before execution
- preflight responses now also surface execution-policy metadata (`tool_mode`, `timeout_ms`, `idempotent`, `cache_ttl_seconds`) derived from the shared tool definitions
- internal service routes now expose both full tool descriptors (`GET /internal/v1/tools/{tool_name}`) and provider-backed readiness checks (`POST /internal/v1/preflight/{tool_name}`) for downstream discovery/debug flows
- Redis-first query-result cache for read tools, including `cache-hit` audit tags on replayed results and degraded local fallback spools
- executable compensation handlers plus `/internal/v1/compensations/execute` for rollback flows
- lightweight internal FastAPI service at `business_tools_service.main:app`
- legacy alias normalization such as `billing.summary(month=...)` so tool-hub/orchestrator compatibility flows behave predictably

## Current usage
- `apps/tool-hub-service`: registry source of truth plus internal `/internal/v1/execute/{tool_name}` adapter target
- `apps/orchestrator-service`: local execution path for baseline orchestration and optional HTTP tool-hub flow
- query/write results now emit `session_context_patch` hints such as `statement_no`, `open_ticket_id`, and `invoice_no`
- `billing.query_statement` now also persists `primary_instance_id`, and `billing.query_instance_cost` writes instance-level cost context (`instance_id`, `instance_billing_cycle`, `last_instance_cost_total`) for later follow-up turns
- `product.recommend_instance` now emits reusable sizing context such as `recommended_instance_type`, `recommended_gpu_model`, and `recommended_instance_summary`, so later turns can continue from a concrete部署建议 instead of recomputing it
- `support.handoff_brief` now builds a structured人工升级摘要 (`queue`, `severity`, `summary`, `operator_notes`) and writes it back into `session_context.attributes.human_handoff_*`, so orchestrator can hand off complaint/故障 turns with a reusable operator packet
- `support.query_service_status` now persists `service_status`, `service_incident_code`, `service_status_summary`, `service_recommended_action`, and `service_affected_instance_id`, so later转人工或追问 can reuse the same technical incident context
- `support.handoff_brief` now also accepts additive service-status / incident inputs, allowing人工交接摘要 to carry the latest baseline诊断与事件编号 without scraping free text
- `ticket.create` now also accepts additive handoff / incident inputs (`queue`, `incident_code`, `service_status`, `related_resources`, `recommended_action`) and persists richer `ticket_*` state so later follow-up queries or operator tooling can reuse the structured escalation context
- marketing campaign lookup, copy generation, and poster brief generation now reuse `recommended_instance_summary` / `last_marketing_product_summary`, so a later “把刚才推荐的实例写成营销文案/海报” follow-up keeps the recommended机型细节 in downstream creative payloads
- order and invoice query tools now also persist `order_no` / `refund_status` / `invoice_status` context so later billing follow-ups can reuse them without re-entering identifiers
- ICP verification/material-check flows now persist `subject_type`, `contacts`, and real-name verification status so later备案提交 turns can hydrate required fields from session state
- ICP contact continuation can now be resumed with flat or dotted contact fields (for example `contact_phone` or `contacts.contact_phone`), because the shared tool bindings write both leaf contact attributes and the composite `attributes.contacts` object
- shared tool definitions now include `input_field_hints` for missing required payload fields such as billing range, refund order number, invoice title, and ICP contacts
- shared tool definitions now also carry the binding metadata needed for structured resume flows, including billing range -> `attributes.billing_range`
- marketing copy generation now reuses `campaign_lookup` outputs via `attributes.last_campaign_name` and writes the generated headline/body back into `session_context`
- poster generation now reuses `poster_brief` outputs via `attributes.poster_theme` and persists poster asset ids/preview/download metadata into `session_context`
- internal execute responses now surface `audit_tags`, so tool-hub/orchestrator can observe cache hits and other execution annotations
- internal execute responses now also expose the richer execution fields (`tool_name`, `operation`, `status`, `summary`, `result`, `citations`) alongside the legacy `message` + `data` compatibility aliases, so direct tool-hub invoke flows can stay provider-backed in HTTP mode
- execute failures that need caller follow-up now also emit additive `user_action_hint` metadata so tool-hub/orchestrator can surface machine-readable clarification, auth, and confirmation instructions
- auth-required `user_action_hint` payloads now also expose `user_profile_bindings`, so continuation callers can map missing account/user/role/permission context onto orchestrator `user_profile_patch` resumes
- `business_tools_service` can now act as the provider-backed source of truth for tool metadata when tool-hub runs in HTTP transport mode
- `business_tools_service` tool discovery now supports additive `capability`, `mode`, `tag`, and `query` filters on `GET /internal/v1/tools`
- `business_tools_service` config now honors shared runtime aliases like `SMARTCLOUD_TIMEZONE`, `SMARTCLOUD_DEFAULT_LOCALE`, `SMARTCLOUD_REQUEST_TIMEOUT_MS`, and the shared `SMARTCLOUD_*_HEADER` names for internal request parsing
- `business_tools_service` internal routes now require an allowed caller from `ALLOWED_INTERNAL_CALLERS` (defaulting to `tool-hub-service`) before exposing descriptors, preflight checks, execution, or compensation handlers
- query-cache behavior can be tuned with `TOOL_QUERY_CACHE_ENABLED` and `TOOL_QUERY_CACHE_TTL_CAP_SECONDS`
- idempotency and query-cache behavior now use Redis on the mainline when `SMARTCLOUD_REDIS_URL` is configured; `BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH` and `BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH` are retained as degraded fallback spools
- confirmed write idempotency now respects each tool definition’s `idempotency_window_seconds`, so Redis-backed mainline keys expire on schedule instead of growing without retention bounds
- required payload fields are now enforced inside the shared tool catalog, returning `invalid-payload` results before auth/confirmation/idempotency logic tries to continue with malformed writes

## Run internal service
```bash
PYTHONPATH=src uvicorn business_tools_service.main:app --reload --port 8030
```
