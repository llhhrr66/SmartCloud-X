# Research Service Development Prompt

You are working inside the `SmartCloud-X` repository. Continue improving `apps/research-service` based on the current implementation, status files, and development documents. Do not rebuild the service from scratch.

## Required reading

Read these files first:

- `/home/ljr/SmartCloud/开发文档拆分版/05-服务拆分与前端设计.md`
- `/home/ljr/SmartCloud/开发文档拆分版/03-RAG编排与事务补偿设计.md`
- `/home/ljr/SmartCloud-X/docs/status/supervisor-auth-marketing-research-status.md`
- `/home/ljr/SmartCloud-X/apps/research-service/README.md`
- `/home/ljr/SmartCloud-X/apps/research-service/app/main.py`
- `/home/ljr/SmartCloud-X/apps/research-service/app/core/config.py`
- `/home/ljr/SmartCloud-X/apps/research-service/app/core/logging.py`
- `/home/ljr/SmartCloud-X/apps/research-service/app/models.py`
- `/home/ljr/SmartCloud-X/apps/research-service/app/routes.py`
- `/home/ljr/SmartCloud-X/apps/research-service/app/store.py`
- `/home/ljr/SmartCloud-X/apps/research-service/app/dependencies.py`
- `/home/ljr/SmartCloud-X/apps/research-service/app/security.py`
- `/home/ljr/SmartCloud-X/apps/research-service/app/mongo_runtime.py`
- `/home/ljr/SmartCloud-X/apps/research-service/tests/conftest.py`
- `/home/ljr/SmartCloud-X/apps/research-service/tests/test_research_api.py`

## Original service responsibilities

According to the development document (05-服务拆分与前端设计), research-service owns:

1. **Deep Research Agent** — orchestrate multi-step research with external sources
2. **外部搜索** — web search, API-based data retrieval for research context
3. **报告生成** — structured report generation from research findings
4. **导出** — export reports in markdown/PDF format

Current implementation covers: task CRUD lifecycle (SQLAlchemy with MySQL/SQLite), JWT auth with optional strict mode calling auth-user-service, idempotency via Idempotency-Key header scoped by (tenant_id, user_id), MongoDB report storage with DisabledResearchMongoRuntime fallback, auto-completion lifecycle (_maybe_complete with time-based progress simulation), placeholder results (Chinese summary templates + placeholder citations/download URLs). 21 tests passing.

**Current gaps (critical)**:
- No actual deep research agent integration — only placeholder results with template summaries
- No external search capability — no web search, no API search, no data retrieval
- No real report generation — `_build_result()` returns hardcoded placeholder content
- No export functionality — placeholder download URLs only, no actual PDF/markdown file generation
- No OpenTelemetry tracing — unlike knowledge-service and rag-service
- No Prometheus metrics — no `/metrics` endpoint, no `/readyz` endpoint
- Auto-completion is artificial — `_maybe_complete()` uses time-based progress simulation, not real task progress
- No task cancellation — no way to cancel a running/queued task
- No webhook/callback notification for task completion

## First step: gap analysis

Before coding, produce a short gap report covering:

- whether the current task lifecycle is just a time-based simulation or has any real processing
- whether the report content generation is real or all placeholder templates
- whether the MongoDB runtime stores actual research data or just mirrors the placeholder result
- whether the idempotency mechanism handles concurrent creation correctly (single-threaded RLock only)
- whether the auth validation covers all edge cases (expired tokens, revoked tokens)
- whether the service has any observability (tracing, metrics) compared to knowledge-service/rag-service
- whether README, tests, and route behavior are consistent
- whether there are missing tests around task cancellation, export, concurrent creation, large topic handling

Do not skip this analysis.

## Main objectives for this round

### P1. OpenTelemetry tracing integration

Current service has no distributed tracing. Add tracing consistent with knowledge-service and rag-service:

- Configure OpenTelemetry tracing with `SMARTCLOUD_TRACE_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`
- Add spans for: task creation, task retrieval, task listing, result/report generation, MongoDB upsert, auth validation
- Propagate trace context from incoming requests (`traceparent`, `X-Trace-Id`)
- Add span attributes: `task_id`, `operation`, `status`, `depth`, `output_format`, `user_id`, `tenant_id`
- Exclude `/healthz`, `/readyz`, and `/metrics` from tracing
- Add OTLP export configuration
- Wire tracing into existing middleware (add `traceparent` to response headers when tracing is active)

Reference implementation: see knowledge-service tracing setup.

### P2. Prometheus metrics

Current service lacks observability metrics. Add:

- `research_requests_total` (counter) with labels: `operation`, `status`, `depth`
- `research_request_duration_seconds` (histogram) with labels: `operation`
- `research_tasks_created_total` (counter)
- `research_tasks_completed_total` (counter)
- `research_idempotency_replays_total` (counter)
- `research_upstream_errors_total` (counter) with labels: `backend`, `error_type`
- `research_readiness_state` (gauge)
- `research_mongo_operations_total` (counter) with labels: `operation`, `status`
- Add `GET /metrics` endpoint (Prometheus text format)
- Add `GET /readyz` endpoint (check database connectivity + MongoDB status)

### P3. Research agent interface abstraction

Current service returns placeholder results. Create a pluggable interface so real agents can be integrated later:

- Create `app/services/research_agent.py` with a `ResearchAgentProvider` protocol:
  ```python
  class ResearchAgentProvider(Protocol):
      async def execute(self, task: ResearchTask, *, on_progress: Callable[[int, str], None] | None = None) -> ResearchResult: ...
      def capabilities(self) -> dict[str, Any]: ...
  ```
- Implement `PlaceholderResearchAgent` (current behavior — instant placeholder results, for tests and cold environments)
- Implement `HttpResearchAgent` stub that calls an external research agent API when configured (`RESEARCH_AGENT_API_URL`, `RESEARCH_AGENT_API_KEY`, `RESEARCH_AGENT_TIMEOUT_SECONDS`)
- Add `ResearchResult` model with fields: `summary`, `sections` (list of titled content blocks), `citations` (list of source references), `metadata` (dict)
- Wire the agent into task creation flow: after task row is created, dispatch to agent; update task status based on agent result
- Add `research_agent_provider` setting to config, default to `placeholder`
- Add `GET /api/v1/research/capabilities` endpoint that returns the active agent's capabilities and configuration
- Keep backward compatibility: PlaceholderResearchAgent produces the same results as current `_build_result()`

### P4. Task lifecycle improvements

Current lifecycle is limited. Add:

- `POST /api/v1/research/tasks/{task_id}/cancel` — cancel a queued/running task (set status to `failed` with `error_message = "cancelled by user"`)
- `DELETE /api/v1/research/tasks/{task_id}` — soft-delete or archive a completed/failed task (add `deleted_at` column, filter from list queries)
- Add `GET /readyz` endpoint that checks database connectivity and MongoDB availability
- Add `task_cancelled_total` metric counter
- Ensure cancel and delete respect tenant/user scoping (same ownership rules as get/list)
- Add `cancelled` as a valid terminal status alongside `completed` and `failed`, or map cancellation to `failed` with a specific error_message pattern

### P5. Improve tests

Add or improve tests for:

- OpenTelemetry span export verification
- Prometheus metrics endpoint and counter values
- Research capabilities endpoint
- Task cancellation lifecycle (cancel queued task, cancel running task, cancel already-completed task returns error)
- Task deletion/archival
- Readyz endpoint (database up/down scenarios)
- Concurrent task creation with same idempotency key (if feasible with SQLite test backend)
- Large topic/scope strings (boundary testing)
- Auth token edge cases: empty bearer, malformed JWT, expired token, wrong audience
- MongoDB runtime fallback behavior (DisabledResearchMongoRuntime)

Use the existing test style in `apps/research-service/tests/test_research_api.py` and fixtures from `tests/conftest.py`.

### P6. Update docs if behavior changes

If you change behavior, update:
- `/home/ljr/SmartCloud-X/apps/research-service/README.md`

Documentation must clearly state:
- new endpoints added (metrics, readyz, capabilities, cancel, delete)
- tracing configuration
- metrics available
- research agent provider configuration
- task lifecycle states and transitions
- known limitations (placeholder agent, no real search/export)
- validation commands

## Coding constraints

- Do not redesign the whole research service architecture.
- Do not change the task creation/idempotency contract (request/response shape).
- Do not change the ResearchTaskRow schema destructively (additive columns only).
- Do not break existing `/api/v1/research/*` routes or their response envelopes.
- Do not remove the DisabledResearchMongoRuntime fallback.
- Do not remove the auto-completion lifecycle (it serves as a test/demo mode).
- Keep SQLite as a valid test/local backend — service must work without MySQL.
- Keep MongoDB optional — service must work without MongoDB.
- Prefer small, reviewable edits.
- Keep compatibility with existing 21 tests.

## Environment dependency resolution

If the virtual environment `.venv` is missing packages needed for new features (e.g., `opentelemetry-api`, `opentelemetry-sdk`, `prometheus-client`), attempt to install them:

```bash
cd /home/ljr/SmartCloud-X && .venv/bin/pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp-proto-http prometheus-client
```

Only report as a blocker if installation fails after attempting.

## Required validation

Use the repository virtual environment and explicit PYTHONPATH.

### Unit tests
```bash
PYTHONPATH="/home/ljr/SmartCloud-X/apps/research-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" \
/home/ljr/SmartCloud-X/.venv/bin/pytest \
/home/ljr/SmartCloud-X/apps/research-service/tests -q
```

### Compile check
```bash
cd /home/ljr/SmartCloud-X && \
/home/ljr/SmartCloud-X/.venv/bin/python -m compileall apps/research-service/app
```

## Required final output

Provide:

1. file-by-file change summary
2. service duty completion table:

| Duty | Status | Notes |
|---|---|---|
| Deep Research Agent | ... | ... |
| 外部搜索 | ... | ... |
| 报告生成 | ... | ... |
| 导出 | ... | ... |

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

SQLAlchemy:
- https://docs.sqlalchemy.org/en/20/orm/quickstart.html

MongoDB (pymongo):
- https://pymongo.readthedocs.io/en/stable/

Pytest:
- https://docs.pytest.org/en/stable/how-to/fixtures.html
- https://docs.pytest.org/en/stable/how-to/monkeypatch.html

## 停止与上报规则

### 必须立即停止并上报的情况

1. **环境阻塞**：虚拟环境 `.venv` 缺少关键依赖（如 fastapi、httpx、pydantic、sqlalchemy）且安装失败时，停止编码，报告缺少的包和错误信息。
2. **编译失败**：`python -m compileall apps/research-service/app` 报语法错误或导入错误时，停止后续开发，先修复编译问题。如果修复两轮仍然不通过，停止并上报。
3. **原有测试回归**：你的修改导致已有测试失败时，立即回退该修改并上报冲突原因。不允许删除或跳过已有测试来通过验证。
4. **合约冲突**：发现已有的公共路由名称或响应结构需要改变时，停止并上报，这些是冻结合约。
5. **上游依赖不可控**：需要修改 `orchestrator-service` 的接口才能完成本轮任务时，停止并上报为跨服务合约变更。
6. **循环失败**：同一问题修复超过 3 次仍然不通过时，停止并上报问题本身，不要继续尝试。

### 环境依赖处理

遇到缺少 Python 包（如 pytest、opentelemetry、prometheus-client 等）时，**先尝试安装**：
```bash
cd /home/ljr/SmartCloud-X && .venv/bin/pip install <package-name>
```
只有在安装失败后才上报为环境阻塞。

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
- 服务：research-service
- 问题描述：（一句话描述）
- 错误信息：（原始错误或日志）
- 已尝试修复：（列出已尝试的方案）
- 需要的下一步动作：（需要谁做什么）
- 当前完成状态：（已完成哪些 P 任务、哪些被阻塞）
```
