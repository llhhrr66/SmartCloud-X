# Business Tools Baseline

Owned baseline assets for SmartCloud-X business tool domains.

## Included
- Python interface definitions for business tools
- local invocation/result contracts used by orchestrator and tool-hub
- spec-aligned starter tool catalog (`billing.query_statement`, `billing.create_invoice`, `order.create_refund`, `ticket.*`, `icp.*`, `marketing.*`, `research.*`)
- finance starter flows now also include `order.query_order` and `invoice.query_invoice` for post-payment / post-invoice status follow-up turns
- ICP starter flows now include `icp.verify_subject` so orchestrator/tool-hub can baseline备案实名认证 checks and persist verified subject/contact context for later submit flows
- ICP submit/verification flows now preserve richer subject/contact state such as `certificate_no`, `contact_email`, and the assembled `contacts` object so follow-up `/continue` turns can satisfy composite备案联系人 inputs incrementally
- marketing starter flows now include poster-brief generation, poster asset generation, promotion-copy generation, and tracked promotion-link generation, and research starter flows now include report export artifacts
- compensation metadata for confirmed write actions so orchestrator can build a Saga rollback stack
- session-context patch metadata on tool results so orchestrator can carry forward billing/ticket/ICP state across turns
- preflight metadata and `input_field_hints` so orchestrator/tool-hub can ask for missing business inputs before execution
- preflight responses now also surface execution-policy metadata (`tool_mode`, `timeout_ms`, `idempotent`, `cache_ttl_seconds`) derived from the shared tool definitions
- internal service routes now expose both full tool descriptors (`GET /internal/v1/tools/{tool_name}`) and provider-backed readiness checks (`POST /internal/v1/preflight/{tool_name}`) for downstream discovery/debug flows
- in-memory query-result cache for read tools, including `cache-hit` audit tags on replayed results
- executable compensation handlers plus `/internal/v1/compensations/execute` for rollback flows
- lightweight internal FastAPI service at `business_tools_service.main:app`
- legacy alias normalization such as `billing.summary(month=...)` so tool-hub/orchestrator compatibility flows behave predictably

## Current usage
- `apps/tool-hub-service`: registry source of truth plus internal `/internal/v1/execute/{tool_name}` adapter target
- `apps/orchestrator-service`: local execution path for baseline orchestration and optional HTTP tool-hub flow
- query/write results now emit `session_context_patch` hints such as `statement_no`, `open_ticket_id`, and `invoice_no`
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
- `business_tools_service` can now act as the provider-backed source of truth for tool metadata when tool-hub runs in HTTP transport mode
- `business_tools_service` tool discovery now supports additive `capability`, `mode`, `tag`, and `query` filters on `GET /internal/v1/tools`
- `business_tools_service` config now honors shared runtime aliases like `SMARTCLOUD_TIMEZONE`, `SMARTCLOUD_DEFAULT_LOCALE`, `SMARTCLOUD_REQUEST_TIMEOUT_MS`, and the shared `SMARTCLOUD_*_HEADER` names for internal request parsing
- `business_tools_service` internal routes now require an allowed caller from `ALLOWED_INTERNAL_CALLERS` (defaulting to `tool-hub-service`) before exposing descriptors, preflight checks, execution, or compensation handlers
- query-cache behavior can be tuned with `TOOL_QUERY_CACHE_ENABLED` and `TOOL_QUERY_CACHE_TTL_CAP_SECONDS`
- process-local idempotency/query-cache stores can optionally persist to files via `BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH` and `BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH`
- required payload fields are now enforced inside the shared tool catalog, returning `invalid-payload` results before auth/confirmation/idempotency logic tries to continue with malformed writes

## Run internal service
```bash
PYTHONPATH=src uvicorn business_tools_service.main:app --reload --port 8030
```
