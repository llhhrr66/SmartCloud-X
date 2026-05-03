# Gateway Service Development Prompt

You are working inside the `SmartCloud-X` repository. Your task is to continue improving `apps/gateway-service` based on the existing implementation, project documentation, and current status files. Do not rebuild the gateway from scratch. Extend and harden the current implementation.

## 1. Context and required reading

Read these files first and use them as the authoritative baseline:

- `/home/ljr/SmartCloud/开发文档拆分版/05-服务拆分与前端设计.md`
- `/home/ljr/SmartCloud-X/docs/status/supervisor-gateway-status.md`
- `/home/ljr/SmartCloud-X/apps/gateway-service/README.md`
- `/home/ljr/SmartCloud-X/apps/gateway-service/app/main.py`
- `/home/ljr/SmartCloud-X/apps/gateway-service/app/core/config.py`
- `/home/ljr/SmartCloud-X/apps/gateway-service/app/core/upstreams.py`
- `/home/ljr/SmartCloud-X/apps/gateway-service/app/services/http.py`
- `/home/ljr/SmartCloud-X/apps/gateway-service/app/services/auth.py`
- `/home/ljr/SmartCloud-X/apps/gateway-service/app/services/streaming.py`
- `/home/ljr/SmartCloud-X/apps/gateway-service/app/services/store.py`
- `/home/ljr/SmartCloud-X/apps/gateway-service/app/services/dashboard.py`
- `/home/ljr/SmartCloud-X/apps/gateway-service/app/middleware/rate_limit.py`
- `/home/ljr/SmartCloud-X/apps/gateway-service/app/api/routes/health.py`
- `/home/ljr/SmartCloud-X/apps/gateway-service/app/api/routes/auth.py`
- `/home/ljr/SmartCloud-X/apps/gateway-service/app/api/routes/chat.py`
- `/home/ljr/SmartCloud-X/apps/gateway-service/app/api/routes/business.py`
- `/home/ljr/SmartCloud-X/apps/gateway-service/app/api/routes/admin.py`
- `/home/ljr/SmartCloud-X/apps/gateway-service/app/api/routes/marketing.py`
- `/home/ljr/SmartCloud-X/apps/gateway-service/app/api/routes/owner_local.py`
- `/home/ljr/SmartCloud-X/apps/gateway-service/tests/test_gateway_api.py`

## 2. Original gateway requirements

According to the project development document, `gateway-service` is responsible for only these core duties:

1. unified entry
2. authentication
3. SSE output
4. request logging
5. rate limiting

The current code already covers unified entry, authentication, SSE passthrough, basic health/readiness, basic rate limiting, and a set of BFF routes. Your task is to improve the service without breaking those existing responsibilities.

## 3. First step: gap analysis before coding

Before editing code, inspect the current implementation and produce a short gap report covering:

- which of the 5 gateway duties are fully implemented
- which are only baseline implementations
- whether request logging is truly implemented as structured logs instead of only response headers
- whether rate limiting is still a single-process in-memory development baseline
- whether timeout, upstream failure, and degradation behaviors are sufficiently tested
- whether README, runbook, and tests still match current implementation

Do not skip this analysis.

## 4. Main objectives for this round

Your priority is to make `gateway-service` closer to a complete engineering delivery.

### P1. Improve request logging

Implement a consistent structured logging strategy for gateway requests and upstream proxy behavior.

At minimum, log these fields for each incoming request:
- request_id
- trace_id
- method
- path
- subject_type
- subject_id
- tenant_id
- response_status
- latency_ms
- rate_limit_remaining

At minimum, log these fields for each upstream call:
- upstream_service
- upstream_method
- upstream_path
- upstream_status
- upstream_latency_ms
- error_category (`timeout`, `connect_error`, `bad_response`, `unauthorized`, etc.)

For SSE requests:
- log stream_started
- log stream_completed or stream_aborted
- do not log raw event payloads
- it is acceptable to log total bytes, event count, and citation cache count

Security requirements for logging:
- do not log tokens
- do not log passwords
- do not log complete sensitive PII
- do not log raw attachment contents

### P2. Improve rate limiting without overengineering

The current limiter is a simple in-memory fixed window. Keep behavior backward-compatible, but improve it where reasonable.

Possible improvements:
- use a better limiter key than only `client_host:path`
- support different keys for authenticated user, tenant, and anonymous traffic
- support separate thresholds for chat SSE vs normal API calls
- keep health and readiness endpoints exempt
- document clearly that this is still a single-instance baseline unless a shared backend is introduced

Do not introduce heavy distributed infrastructure unless the repository already has a natural shared backend path.

### P3. Expand test coverage

Add or improve tests for:

1. structured request logging
2. upstream timeout handling
3. upstream error passthrough
4. SSE passthrough behavior
5. citation caching from SSE
6. rate limit headers and route exemption behavior
7. degradation in `/readyz`
8. at least one happy path and one error path for the important BFF surfaces

Use existing test style from `apps/gateway-service/tests/test_gateway_api.py`.

### P4. Update delivery documents

After coding, update these if needed:
- `/home/ljr/SmartCloud-X/apps/gateway-service/README.md`
- `/home/ljr/SmartCloud-X/docs/status/supervisor-gateway-status.md`
- `/home/ljr/SmartCloud-X/docs/runbooks/gateway-live-web-user.md`
- `/home/ljr/SmartCloud-X/docs/runbooks/local-validation.md`

The documentation must clearly state:
- what gateway owns today
- what still remains owner-local or debug-only
- how to run it
- how to validate it
- known limitations
- logging strategy
- rate limiting strategy

## 5. Coding constraints

- Do not redesign the whole gateway.
- Do not rename existing routes.
- Do not move business logic from upstream services into the gateway unless it is already part of the current BFF role.
- Keep request_id, trace_id, tenant_id, and idempotency key forwarding intact.
- Keep SSE passthrough semantics intact.
- Prefer small, reviewable edits.
- Keep compatibility with existing tests unless there is a justified contract issue.

## 6. Required validation commands

Use the repository virtual environment and explicit PYTHONPATH.

### Unit tests
```bash
PYTHONPATH="/home/ljr/SmartCloud-X/apps/gateway-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" \
/home/ljr/SmartCloud-X/.venv/bin/pytest \
/home/ljr/SmartCloud-X/apps/gateway-service/tests/test_gateway_api.py
```

### Compile check
```bash
cd /home/ljr/SmartCloud-X && \
/home/ljr/SmartCloud-X/.venv/bin/python -m compileall apps/gateway-service/app
```

### Run service locally
```bash
cd /home/ljr/SmartCloud-X/apps/gateway-service && \
/home/ljr/SmartCloud-X/.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

### Acceptance probe
```bash
cd /home/ljr/SmartCloud-X && \
/home/ljr/SmartCloud-X/.venv/bin/python scripts/qa/gateway_acceptance_probe.py --base-url http://127.0.0.1:8000 --timeout 30
```

## 7. Required final output

When finished, provide:

1. file-by-file change summary
2. gateway duty completion table:

| Duty | Status | Notes |
|---|---|---|
| unified entry | ... | ... |
| authentication | ... | ... |
| SSE output | ... | ... |
| request logging | ... | ... |
| rate limiting | ... | ... |

3. exact validation commands run
4. exact results
5. known limitations
6. whether the service is ready for handoff back to the main reviewer

## 8. Relevant official documentation

FastAPI:
- https://fastapi.tiangolo.com/tutorial/bigger-applications/
- https://fastapi.tiangolo.com/tutorial/middleware/
- https://fastapi.tiangolo.com/tutorial/dependencies/
- https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse
- https://fastapi.tiangolo.com/tutorial/testing/

HTTPX:
- https://www.python-httpx.org/async/
- https://www.python-httpx.org/advanced/transports/
- https://www.python-httpx.org/advanced/timeouts/

Pytest:
- https://docs.pytest.org/en/stable/how-to/fixtures.html
- https://docs.pytest.org/en/stable/how-to/monkeypatch.html
- https://docs.pytest.org/en/stable/how-to/logging.html

## 停止与上报规则

### 必须立即停止并上报的情况

1. **环境阻塞**：虚拟环境 `.venv` 缺少关键依赖（如 fastapi、httpx、pydantic）且安装失败时，停止编码，报告缺少的包和错误信息。
2. **编译失败**：`python -m compileall apps/gateway-service/app` 报语法错误或导入错误时，停止后续开发，先修复编译问题。如果修复两轮仍然不通过，停止并上报。
3. **原有测试回归**：你的修改导致已有测试失败时，立即回退该修改并上报冲突原因。不允许删除或跳过已有测试来通过验证。
4. **合约冲突**：发现已有的公共路由名称需要改变请求或响应结构时，停止并上报，这些是冻结合约。
5. **上游依赖不可控**：需要修改其他服务的接口才能完成本轮任务时，停止并上报为跨服务合约变更。
6. **循环失败**：同一问题修复超过 3 次仍然不通过时，停止并上报问题本身，不要继续尝试。

### 必须停止并输出交付物的情况

7. **全部 P1-P3 完成**：所有优先级任务完成且验证通过后，停止编码，输出完整的交付物（变更总结 + 完成度表格 + 验证结果 + 已知限制）。
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
- 服务：gateway-service
- 问题描述：（一句话描述）
- 错误信息：（原始错误或日志）
- 已尝试修复：（列出已尝试的方案）
- 需要的下一步动作：（需要谁做什么）
- 当前完成状态：（已完成哪些 P 任务、哪些被阻塞）
```
