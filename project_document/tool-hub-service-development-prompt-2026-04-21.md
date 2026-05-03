# Tool Hub Service Development Prompt

You are working inside the `SmartCloud-X` repository. Continue improving `apps/tool-hub-service` based on the current implementation, status files, and development documents. Do not rebuild the service from scratch.

## Required reading

Read these files first:

- `/home/ljr/SmartCloud/开发文档拆分版/05-服务拆分与前端设计.md`
- `/home/ljr/SmartCloud/开发文档拆分版/03-RAG编排与事务补偿设计.md` (MCP/A2A section)
- `/home/ljr/SmartCloud-X/apps/tool-hub-service/README.md`
- `/home/ljr/SmartCloud-X/apps/tool-hub-service/app/main.py`
- `/home/ljr/SmartCloud-X/apps/tool-hub-service/app/core/config.py`
- `/home/ljr/SmartCloud-X/apps/tool-hub-service/app/core/business_tools_sdk.py`
- `/home/ljr/SmartCloud-X/apps/tool-hub-service/app/core/redis_client.py`
- `/home/ljr/SmartCloud-X/apps/tool-hub-service/app/core/database.py`
- `/home/ljr/SmartCloud-X/apps/tool-hub-service/app/services/registry.py`
- `/home/ljr/SmartCloud-X/apps/tool-hub-service/app/services/business_tools_client.py`
- `/home/ljr/SmartCloud-X/apps/tool-hub-service/app/services/idempotency.py`
- `/home/ljr/SmartCloud-X/apps/tool-hub-service/app/services/audit_service.py`
- `/home/ljr/SmartCloud-X/apps/tool-hub-service/app/api/routes/tools.py`
- `/home/ljr/SmartCloud-X/apps/tool-hub-service/app/api/routes/health.py`
- `/home/ljr/SmartCloud-X/apps/tool-hub-service/app/api/dependencies.py`
- `/home/ljr/SmartCloud-X/apps/tool-hub-service/app/models/tools.py`
- `/home/ljr/SmartCloud-X/apps/tool-hub-service/app/models/audit.py`
- `/home/ljr/SmartCloud-X/apps/tool-hub-service/test_tool_hub_service.py`

## Original service responsibilities

According to the development document (05-服务拆分与前端设计), tool-hub-service owns:

1. **MCP gateway** — Model Context Protocol compatible tool discovery and execution interface
2. **Tool 注册** — central tool catalog for orchestrator discovery
3. **Tool 调用** — unified tool execution with auth/payload validation
4. **参数校验** — consistent payload/auth validation before execution
5. **tool trace** — audit trail for all tool executions

Current implementation covers: tool registry (local + remote), HTTP dispatch to business-tools-service, preflight validation, idempotency (Redis/file), query cache, MySQL audit storage, MCP-compatible endpoints (`/tools/list`, `/tools/call`), compensation execution, internal caller authentication. The service has comprehensive tests.

## First step: gap analysis

Before coding, produce a short gap report covering:

- whether the MCP protocol implementation is fully compliant or baseline only (check against MCP spec for tool schema, streaming, resource discovery)
- whether tool registration is dynamic (runtime add/remove) or static (startup only)
- whether tool tracing integrates with OpenTelemetry for distributed tracing or only audit records
- whether parameter validation covers all JSON Schema features (nested objects, arrays, oneOf, anyOf, refs) or baseline only
- whether the compensation mechanism handles nested/dependent compensations or only single-level
- whether idempotency key collision handling is robust (concurrent requests with same key)
- whether the query cache invalidation strategy is sufficient (TTL only vs event-based)
- whether README, tests, and route behavior are consistent
- whether there are missing tests around concurrent idempotency, cache invalidation, MCP streaming, compensation chains

Do not skip this analysis.

## Main objectives for this round

### P1. OpenTelemetry tracing integration

Current service has audit records but no distributed tracing. Add:

- Configure OpenTelemetry tracing similar to knowledge-service and rag-service
- Add spans for: tool discovery, preflight validation, tool execution, business-tools HTTP calls, compensation execution
- Propagate trace context from incoming requests (`traceparent`, `X-Trace-Id`) to business-tools-service calls
- Add span attributes: `tool_name`, `operation`, `status`, `latency_ms`, `provider`, `idempotency_key`
- Exclude `/healthz` and `/metrics` from tracing
- Add OTLP export configuration via `SMARTCLOUD_TRACE_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`
- Wire tracing into existing middleware

### P2. Prometheus metrics

Current service lacks observability metrics. Add:

- `tool_hub_requests_total` (counter) with labels: `tool_name`, `operation`, `status`, `provider`
- `tool_hub_request_duration_seconds` (histogram) with labels: `tool_name`, `operation`
- `tool_hub_cache_hits_total` / `tool_hub_cache_misses_total` (counters)
- `tool_hub_idempotency_hits_total` / `tool_hub_idempotency_stores_total` (counters)
- `tool_hub_upstream_errors_total` (counter) with labels: `provider`, `error_type`
- `tool_hub_readiness_state` (gauge)
- `tool_hub_audit_records_total` (counter)
- Add `GET /metrics` endpoint
- Update `/healthz` to include metric snapshot

### P3. MCP protocol enhancements

Current MCP implementation is baseline (`/tools/list`, `/tools/call`). Enhance:

- Add `GET /tools/describe/{tool_name}` for individual tool schema (MCP spec)
- Add tool schema validation against JSON Schema draft-07 (the MCP standard)
- Add `x-mcp-*` extension fields support in tool definitions for custom metadata
- Add `resources` field support in tool responses for follow-up references
- Consider streaming support via SSE for long-running tools (optional, mark as future if complex)
- Ensure tool input/output schemas follow MCP naming conventions (`inputSchema`, `name`, `description`)

### P4. Idempotency hardening

Current idempotency has basic Redis/file backends. Harden:

- Add distributed lock when checking+storing idempotency to prevent race conditions on concurrent requests with same key
- Add idempotency conflict detection: if a request is in-flight with the same key, return 409 or wait
- Add idempotency key format validation (UUID or custom pattern)
- Add idempotency expiry notification in response headers (`X-Idempotency-Expires-At`)
- Add idempotency stats to health/metrics endpoints
- Add test for concurrent idempotency requests

### P5. Improve tests

Add or improve tests for:

- OpenTelemetry span export verification (similar to knowledge-service tests)
- Prometheus metrics endpoint and counter values
- MCP `/tools/describe/{tool_name}` endpoint
- Concurrent idempotency requests (same key, different requests)
- Cache invalidation behavior
- Compensation chain execution (multiple compensations)
- Tool registration edge cases (duplicate names, invalid schemas)
- Internal caller authentication failure paths
- Audit record filtering edge cases
- Business-tools HTTP timeout and retry behavior

Use the existing test style in `apps/tool-hub-service/test_tool_hub_service.py`.

### P6. Update docs if behavior changes

If you change behavior, update:
- `/home/ljr/SmartCloud-X/apps/tool-hub-service/README.md`

Documentation must clearly state:
- new endpoints added (metrics, MCP describe)
- tracing configuration
- metrics available
- idempotency behavior and headers
- known limitations
- validation commands

## Coding constraints

- Do not redesign the whole tool-hub architecture.
- Do not change the business-tools-service integration contract.
- Do not remove existing tool definitions from the registry.
- Do not break existing `/api/v1/tools/*`, `/internal/v1/tools/*`, or `/tools/*` routes.
- Do not change the audit record schema (additive fields only).
- Keep Redis and file backends optional — service must work with MySQL-only or degraded mode.
- Prefer small, reviewable edits.
- Keep compatibility with existing tests.

## Required validation

Use the repository virtual environment and explicit PYTHONPATH.

### Unit tests
```bash
PYTHONPATH="/home/ljr/SmartCloud-X/apps/tool-hub-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" \
/home/ljr/SmartCloud-X/.venv/bin/pytest \
/home/ljr/SmartCloud-X/apps/tool-hub-service/test_tool_hub_service.py -q
```

### Compile check
```bash
cd /home/ljr/SmartCloud-X && \
/home/ljr/SmartCloud-X/.venv/bin/python -m compileall apps/tool-hub-service/app
```

## Required final output

Provide:

1. file-by-file change summary
2. service duty completion table:

| Duty | Status | Notes |
|---|---|---|
| MCP gateway | ... | ... |
| Tool 注册 | ... | ... |
| Tool 调用 | ... | ... |
| 参数校验 | ... | ... |
| tool trace | ... | ... |

3. exact validation commands run
4. exact results
5. known limitations
6. whether the service is ready to hand back for review

## Relevant official documentation

FastAPI:
- https://fastapi.tiangolo.com/tutorial/bigger-applications/
- https://fastapi.tiangolo.com/tutorial/dependencies/
- https://fastapi.tiangolo.com/tutorial/testing/

Pydantic:
- https://docs.pydantic.dev/latest/concepts/models/
- https://docs.pydantic.dev/latest/concepts/validators/

OpenTelemetry:
- https://opentelemetry.io/docs/languages/python/
- https://opentelemetry-python.readthedocs.io/en/latest/

Prometheus:
- https://prometheus.github.io/client_python/

MCP (Model Context Protocol):
- https://modelcontextprotocol.io/docs/concepts/tools
- https://spec.modelcontextprotocol.io/

Redis:
- https://redis.io/docs/manual/patterns/distributed-locks/

Pytest:
- https://docs.pytest.org/en/stable/how-to/fixtures.html
- https://docs.pytest.org/en/stable/how-to/monkeypatch.html

## 停止与上报规则

### 必须立即停止并上报的情况

1. **环境阻塞**：虚拟环境 `.venv` 缺少关键依赖（如 fastapi、httpx、pydantic、redis）且安装失败时，停止编码，报告缺少的包和错误信息。
2. **编译失败**：`python -m compileall apps/tool-hub-service/app` 报语法错误或导入错误时，停止后续开发，先修复编译问题。如果修复两轮仍然不通过，停止并上报。
3. **原有测试回归**：你的修改导致已有测试失败时，立即回退该修改并上报冲突原因。不允许删除或跳过已有测试来通过验证。
4. **合约冲突**：发现已有的公共路由名称或响应结构需要改变时，停止并上报，这些是冻结合约。
5. **上游依赖不可控**：需要修改 `business-tools-service` 或 `orchestrator-service` 的接口才能完成本轮任务时，停止并上报为跨服务合约变更。
6. **循环失败**：同一问题修复超过 3 次仍然不通过时，停止并上报问题本身，不要继续尝试。

### 必须停止并输出交付物的情况

7. **全部 P1-P5 完成**：所有优先级任务完成且验证通过后，停止编码，输出完整的交付物（变更总结 + 完成度表格 + 验证结果 + 已知限制）。
8. **部分完成但无法继续**：如果某个优先级任务因外部原因无法完成，标记为 blocked，继续完成其他任务，最终交付时明确标注哪些已完成、哪些被阻塞及原因。

### 不允许的行为

- 不允许跳过验证命令直接报告"完成"
- 不允许用 `# type: ignore` 或 `noqa` 掩盖真实的类型或逻辑错误（已有合理标注的除外）
- 不允许在测试失败时删除或注释掉测试
- 不允许引入破坏性变更后不运行回归测试
- 不允许在遇到阻塞时静默继续下一个任务而不记录

### 上报格式

遇到需要上报的情况时，输出以下格式：

```
## BLOCKER REPORT
- 类型：[code | environment | dependency | contract | upstream]
- 服务：tool-hub-service
- 问题描述：（一句话描述）
- 错误信息：（原始错误或日志）
- 已尝试修复：（列出已尝试的方案）
- 需要的下一步动作：（需要谁做什么）
- 当前完成状态：（已完成哪些 P 任务、哪些被阻塞）
```
