# Marketing Service Development Prompt

You are working inside the `SmartCloud-X` repository. Continue improving `apps/marketing-service` based on the current implementation, status files, and development documents. Do not rebuild the service from scratch.

## Required reading

Read these files first:

- `/home/ljr/SmartCloud/开发文档拆分版/05-服务拆分与前端设计.md`
- `/home/ljr/SmartCloud/开发文档拆分版/03-RAG编排与事务补偿设计.md`
- `/home/ljr/SmartCloud-X/docs/status/supervisor-auth-marketing-research-status.md`
- `/home/ljr/SmartCloud-X/apps/marketing-service/README.md`
- `/home/ljr/SmartCloud-X/apps/marketing-service/app/main.py`
- `/home/ljr/SmartCloud-X/apps/marketing-service/app/core/config.py`
- `/home/ljr/SmartCloud-X/apps/marketing-service/app/core/logging.py`
- `/home/ljr/SmartCloud-X/apps/marketing-service/app/models.py`
- `/home/ljr/SmartCloud-X/apps/marketing-service/app/routes.py`
- `/home/ljr/SmartCloud-X/apps/marketing-service/app/store.py`
- `/home/ljr/SmartCloud-X/apps/marketing-service/app/tasks.py`
- `/home/ljr/SmartCloud-X/apps/marketing-service/app/celery_app.py`
- `/home/ljr/SmartCloud-X/apps/marketing-service/app/dependencies.py`
- `/home/ljr/SmartCloud-X/apps/marketing-service/app/security.py`
- `/home/ljr/SmartCloud-X/apps/marketing-service/app/mongo_runtime.py`
- `/home/ljr/SmartCloud-X/apps/marketing-service/tests/conftest.py`
- `/home/ljr/SmartCloud-X/apps/marketing-service/tests/test_marketing_api.py`

## Original service responsibilities

According to the development document (05-服务拆分与前端设计), marketing-service owns:

1. **营销活动** — campaign management (create, publish, schedule, list active campaigns)
2. **海报生成** — poster/image generation from campaign data
3. **推广链接** — tracked promotion link creation with UTM parameters
4. **文案生成** — marketing copy generation (headline, summary, body, CTA)

Current implementation covers: all four domains with full CRUD/read flows. Campaign listing with date-range filtering (published + active only). Poster generation with full lifecycle (queued→running→completed/failed), idempotency via Idempotency-Key, optional Celery worker path with Redis broker, MinIO artifact storage with CDN fallback, MongoDB poster asset documents. Promotion link generation with UTM parameters and short URLs. Copy generation with template-based output. JWT auth with optional strict mode. Multi-tenant isolation. SQLAlchemy with MySQL/SQLite. 28 tests passing.

**Current gaps**:
- Copy generation is template-based string interpolation — no LLM integration
- Poster generation produces a 1x1 transparent PNG placeholder — no image generation service
- No OpenTelemetry tracing — unlike knowledge-service and rag-service
- No Prometheus metrics — no `/metrics` endpoint, no `/readyz` endpoint
- No admin campaign CRUD (only user-facing read of published campaigns)
- No structured logging
- In-memory snapshot pattern loads all rows and rebuilds after every write (won't scale)

## First step: gap analysis

Before coding, produce a short gap report covering:

- whether copy generation is template-based or has any LLM integration
- whether poster generation produces real images or placeholder PNGs
- whether the Celery worker path actually generates real poster content or just auto-completes
- whether campaign management has admin CRUD or only user-facing read
- whether MinIO integration handles all error paths (bucket missing, upload failure, object deletion)
- whether the idempotency mechanism handles concurrent poster requests correctly
- whether the service has any observability (tracing, metrics)
- whether README, tests, and route behavior are consistent
- whether there are missing tests around Celery worker execution, MinIO failure paths, concurrent poster creation, campaign edge cases

Do not skip this analysis.

## Main objectives for this round

### P1. OpenTelemetry tracing integration

Current service has no distributed tracing. Add tracing consistent with knowledge-service and rag-service:

- Configure OpenTelemetry tracing with `SMARTCLOUD_TRACE_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`
- Add spans for: campaign listing, copy generation, promotion link generation, poster task creation, poster result retrieval, MinIO operations, MongoDB upsert, Celery enqueue, auth validation
- Propagate trace context from incoming requests (`traceparent`, `X-Trace-Id`)
- Add span attributes: `operation`, `status`, `campaign_id`, `poster_task_id`, `user_id`, `tenant_id`
- Exclude `/healthz`, `/readyz`, and `/metrics` from tracing
- Add OTLP export configuration
- Wire tracing into existing middleware

Reference implementation: see knowledge-service tracing setup.

### P2. Prometheus metrics

Current service lacks observability metrics. Add:

- `marketing_requests_total` (counter) with labels: `operation`, `status`, `resource_type`
- `marketing_request_duration_seconds` (histogram) with labels: `operation`
- `marketing_posters_created_total` (counter)
- `marketing_posters_completed_total` (counter)
- `marketing_copies_generated_total` (counter)
- `marketing_links_generated_total` (counter)
- `marketing_idempotency_replays_total` (counter)
- `marketing_upstream_errors_total` (counter) with labels: `backend`, `error_type`
- `marketing_minio_operations_total` (counter) with labels: `operation`, `status`
- `marketing_readiness_state` (gauge)
- Add `GET /metrics` endpoint (Prometheus text format)
- Add `GET /readyz` endpoint (check database connectivity + MinIO + MongoDB + Celery/Redis status)

### P3. Generation service interface abstraction

Current service uses template-based generation for both copy and posters. Create pluggable interfaces:

#### Copy generation:
- Create `app/services/copy_generator.py` with a `CopyGeneratorProvider` protocol:
  ```python
  class CopyGeneratorProvider(Protocol):
      async def generate(self, campaign: CampaignContext, *, tone: str, keywords: list[str]) -> GeneratedCopy: ...
      def capabilities(self) -> dict[str, Any]: ...
  ```
- Implement `TemplateCopyGenerator` (current behavior — deterministic string interpolation, for tests)
- Implement `LLMCopyGenerator` stub that calls an OpenAI-compatible API when configured (`MARKETING_LLM_API_URL`, `MARKETING_LLM_API_KEY`, `MARKETING_LLM_MODEL`)
- Add `copy_generator_provider` setting to config, default to `template`
- Keep backward compatibility: TemplateCopyGenerator produces the same results as current code

#### Poster generation:
- Create `app/services/poster_generator.py` with a `PosterGeneratorProvider` protocol:
  ```python
  class PosterGeneratorProvider(Protocol):
      async def generate(self, task: PosterTaskContext) -> PosterResult: ...
      def capabilities(self) -> dict[str, Any]: ...
  ```
- Implement `PlaceholderPosterGenerator` (current behavior — 1x1 PNG placeholder, for tests)
- Implement `ImageServicePosterGenerator` stub that calls an image generation API when configured (`MARKETING_IMAGE_API_URL`, `MARKETING_IMAGE_API_KEY`)
- Add `poster_generator_provider` setting to config, default to `placeholder`

- Add `GET /api/v1/marketing/capabilities` endpoint returning active provider info for both copy and poster generation

### P4. Admin campaign management

Current service only has user-facing campaign read. Add admin CRUD:

- `POST /api/v1/marketing/admin/campaigns` — create a new campaign (requires `admin:marketing.write` permission)
- `PUT /api/v1/marketing/admin/campaigns/{campaign_id}` — update campaign fields (title, description, status, dates, highlights)
- `DELETE /api/v1/marketing/admin/campaigns/{campaign_id}` — soft-delete a campaign (add `deleted_at` column, filter from list queries)
- `GET /api/v1/marketing/admin/campaigns` — list all campaigns including draft/expired (requires `admin:marketing.read`)
- Admin routes should use the same canonical envelope pattern
- Admin routes should require `subject_type == "admin"` or admin-level permissions
- Keep the user-facing `GET /api/v1/marketing/campaigns` unchanged (still only shows published + active)

### P5. Improve tests

Add or improve tests for:

- OpenTelemetry span export verification
- Prometheus metrics endpoint and counter values
- Marketing capabilities endpoint
- Copy generation with LLM provider (mock)
- Poster generation with image service provider (mock)
- Admin campaign CRUD (create, update, soft-delete, list including draft)
- Readyz endpoint (database up/down, MinIO up/down)
- Concurrent poster creation with same idempotency key
- Campaign date-range edge cases (starts today, ends today, timezone boundary)
- Copy generation with empty/long keywords
- Promotion link with special characters in UTM parameters
- Auth edge cases: admin permission checks, mixed user/admin tokens

Use the existing test style in `apps/marketing-service/tests/test_marketing_api.py` and fixtures from `tests/conftest.py`.

### P6. Update docs if behavior changes

If you change behavior, update:
- `/home/ljr/SmartCloud-X/apps/marketing-service/README.md`

Documentation must clearly state:
- new endpoints added (metrics, readyz, capabilities, admin CRUD)
- tracing configuration
- metrics available
- generation provider configuration (copy + poster)
- admin vs user route distinction
- known limitations (template-based generation, placeholder images)
- validation commands

## Coding constraints

- Do not redesign the whole marketing service architecture.
- Do not change the campaign/copy/link/poster response schemas (additive fields only).
- Do not change the poster creation/idempotency contract.
- Do not break existing `/api/v1/marketing/*` routes or their response envelopes.
- Do not remove the DisabledMarketingMongoRuntime fallback.
- Do not remove the auto-completion lifecycle for poster tasks (it serves as test/demo mode).
- Do not remove the Celery integration path.
- Keep SQLite as a valid test/local backend.
- Keep MinIO, MongoDB, Redis, and Celery optional — service must work without them.
- Prefer small, reviewable edits.
- Keep compatibility with existing 28 tests.

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
PYTHONPATH="/home/ljr/SmartCloud-X/apps/marketing-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" \
/home/ljr/SmartCloud-X/.venv/bin/pytest \
/home/ljr/SmartCloud-X/apps/marketing-service/tests -q
```

### Compile check
```bash
cd /home/ljr/SmartCloud-X && \
/home/ljr/SmartCloud-X/.venv/bin/python -m compileall apps/marketing-service/app
```

## Required final output

Provide:

1. file-by-file change summary
2. service duty completion table:

| Duty | Status | Notes |
|---|---|---|
| 营销活动 | ... | ... |
| 海报生成 | ... | ... |
| 推广链接 | ... | ... |
| 文案生成 | ... | ... |

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

Celery:
- https://docs.celeryq.dev/en/stable/getting-started/introduction.html

MinIO:
- https://min.io/docs/minio/linux/developers/python/API.html

Pytest:
- https://docs.pytest.org/en/stable/how-to/fixtures.html
- https://docs.pytest.org/en/stable/how-to/monkeypatch.html

## 停止与上报规则

### 必须立即停止并上报的情况

1. **环境阻塞**：虚拟环境 `.venv` 缺少关键依赖（如 fastapi、httpx、pydantic、sqlalchemy、minio）且安装失败时，停止编码，报告缺少的包和错误信息。
2. **编译失败**：`python -m compileall apps/marketing-service/app` 报语法错误或导入错误时，停止后续开发，先修复编译问题。如果修复两轮仍然不通过，停止并上报。
3. **原有测试回归**：你的修改导致已有测试失败时，立即回退该修改并上报冲突原因。不允许删除或跳过已有测试来通过验证。
4. **合约冲突**：发现已有的公共路由名称或响应结构需要改变时，停止并上报，这些是冻结合约。
5. **上游依赖不可控**：需要修改 `orchestrator-service` 或 `tool-hub-service` 的接口才能完成本轮任务时，停止并上报为跨服务合约变更。
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
- 服务：marketing-service
- 问题描述：（一句话描述）
- 错误信息：（原始错误或日志）
- 已尝试修复：（列出已尝试的方案）
- 需要的下一步动作：（需要谁做什么）
- 当前完成状态：（已完成哪些 P 任务、哪些被阻塞）
```
