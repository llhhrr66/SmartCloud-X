# Tool Hub Service Baseline

FastAPI service that exposes registry, MCP aliases, and internal tool-call contracts for SmartCloud-X business tools.

## Endpoints
- `GET /healthz`
- `GET /api/v1/tools` (`/api/tool-hub/v1/tools` compatibility alias; supports `capability`, `mode`, `tag`, `query`)
- `GET /api/v1/tools/{tool_name}`
- `POST /api/v1/tools/{tool_name}/invoke`
- `POST /api/v1/tools/preflight`
- `GET /api/v1/tool-calls` (supports `tool_name`, `status`, `trace_id`, `conversation_id`, `tenant_id`, `idempotency_key`, `audit_tag`)
- `GET /api/v1/tool-calls/{tool_call_id}`
- `GET /internal/v1/tools`
- `GET /internal/v1/tools/{tool_name}`
- `POST /internal/v1/tool-compensations/call`
- `POST /internal/v1/tools/call`
- `POST /internal/v1/tools/preflight`
- `GET /tools/list`
- `POST /tools/call`

## Purpose
- central tool catalog for orchestrator discovery
- consistent payload/auth validation for direct invoke and internal tool-call flows
- HTTP-first dispatch to `apps/business-tools`, with degraded local fallback on downstream connect failures in local/dev/test
- compensation execution bridge for orchestrator Saga rollback flows
- starter MCP-compatible list/call surface
- MySQL-first audit storage for tool-call records with degraded local fallback spools
- public `POST /api/v1/tools/{tool_name}/invoke` requests are now audited too (with synthetic tool_call ids when needed), so direct debug/operator invokes land in the same `/api/v1/tool-calls` trail as internal and MCP executions
- public `POST /api/v1/tools/{tool_name}/invoke` responses now also echo the effective `tool_call_id`, so callers can immediately correlate the invoke result with `/api/v1/tool-calls/{tool_call_id}` without reconstructing the audit identifier themselves
- passes through compensation/idempotency metadata for confirmed write tools
- passes through `session_context_patch` metadata and stores a preview of it in tool-call audit records
- passes through `audit_tags` such as `cache-hit` so downstream orchestrator/admin flows can inspect query-cache reuse
- exposes the canonical non-audited `POST /api/v1/tools/preflight` route plus the internal `/internal/v1/tools/preflight` alias so orchestrator or debug consumers can inspect missing payload/auth/confirmation blockers before execution
- preflight responses now also surface `session_context_bindings` plus execution-policy metadata (`tool_mode`, `timeout_ms`, `idempotent`, `cache_ttl_seconds`), so clarification/resume callers can see both how to satisfy missing fields and how the downstream tool will execute
- direct/internal tool-call responses and audit records now preserve additive `user_action_hint` metadata from business-tools so downstream continuation clients can recover structured clarification/auth/confirmation instructions
- auth-required hints now also preserve additive `user_profile_bindings`, so continuation clients know which `/continue.user_profile_patch` fields can satisfy missing account/user/role/permission context
- when `BUSINESS_TOOLS_TRANSPORT=http`, registry/detail/preflight surfaces can now resolve descriptors from the running business-tools provider instead of assuming only the local starter catalog
- public/internal tool-list routes now support additive capability/mode/tag/query filters so admin/debug consumers can inspect narrower tool slices without bespoke registry code
- when `BUSINESS_TOOLS_TRANSPORT=http`, direct `POST /api/v1/tools/{tool_name}/invoke` requests can now validate against the remote descriptor and execute through the business-tools provider while preserving `ToolExecutionResult` fields such as `status`, `summary`, `result`, and `citations`
- dev now defaults `BUSINESS_TOOLS_TRANSPORT=http`, while staging/prod require `BUSINESS_TOOLS_TRANSPORT=http` so deployed tool dispatch follows the real service boundary by default
- the starter registry now surfaces `product.recommend_instance` for GPU sizing guidance, plus the newer marketing poster/copy/promotion-link and research export tools alongside the earlier billing/order/ticket/ICP flows
- the starter registry now also exposes `support.query_service_status`, so tool-hub can broker baseline实例/服务健康检查结果 and the resulting incident/session-context patch through the same public/internal/MCP tool surfaces
- the starter registry now also exposes `support.handoff_brief`, so complaint/故障 escalations can generate a structured human-operator packet through the same internal/public/MCP tool surfaces
- `support.handoff_brief` descriptors and execute results now preserve additive diagnostic inputs such as `service_status`, `incident_code`, `status_summary`, and `recommended_action`, so downstream direct invokes can pass along the latest baseline incident context into人工交接摘要
- `ticket.create` descriptors and execute results now also preserve additive handoff / incident inputs such as `queue`, `incident_code`, `service_status`, and `related_resources`, so downstream callers can create a richer support ticket from the structured escalation context emitted by orchestrator
- the starter registry now exposes recommendation-aware marketing metadata (`product_summary`, recommendation-backed session-context bindings), so downstream orchestrator/debug consumers can turn a prior GPU sizing recommendation into a grounded copy/poster follow-up without bespoke adapter code
- the starter registry now also surfaces `billing.query_instance_cost`, so operators or orchestrator follow-up turns can inspect a concrete per-instance cost breakdown instead of only monthly statement totals
- the starter registry now also exposes finance follow-up query tools such as `order.query_order` and `invoice.query_invoice`, so deployed hubs can answer post-refund and post-invoice status lookups without custom adapters
- the starter registry now also exposes `icp.verify_subject`, so tool-hub can broker实名认证 verification and the resulting persisted contacts/subject context for downstream ICP submit flows
- downstream business-tools internal prefix is now configurable with `BUSINESS_TOOLS_INTERNAL_API_PREFIX`, so HTTP-mode tool discovery/calls are not hard-wired to `/internal/v1`
- internal `/internal/v1/tools`, `/internal/v1/tools/{tool_name}`, `/internal/v1/tools/call`, `/internal/v1/tools/preflight`, and `/internal/v1/tool-compensations/call` now require an allowed caller from `ALLOWED_INTERNAL_CALLERS`, and the execute/preflight/compensation routes are no longer exposed on the public `/api/v1` prefix
- honors shared runtime env aliases such as `SMARTCLOUD_TIMEZONE`, `SMARTCLOUD_DEFAULT_LOCALE`, `SMARTCLOUD_REQUEST_TIMEOUT_MS`, and the shared `SMARTCLOUD_*_HEADER` names used for internal request propagation
- local business-tools execution can reuse the shared Redis query cache; configure with `TOOL_QUERY_CACHE_ENABLED`, `TOOL_QUERY_CACHE_TTL_CAP_SECONDS`, and `SMARTCLOUD_REDIS_URL`
- `AUDIT_STORE_PATH`, `BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH`, and `BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH` now act as degraded fallback spools when MySQL/Redis-backed runtime storage is configured but unavailable
- tool-call audits now distinguish `invalid-payload` failures from auth/confirmation/idempotency errors so operator flows can debug malformed invocations earlier

## Run
```bash
uvicorn app.main:app --reload --port 8020
```
