# SmartCloud-X Gateway Service

统一 API Gateway / BFF，承接 `web-user` 默认外部入口 `http://localhost:8000`，同时为管理侧保留 gateway 自有聚合面与 upstream 代理面。

## 当前职责边界

Gateway 今天只拥有并强化这 5 类职责：

1. 统一入口
2. 鉴权
3. SSE 输出透传
4. 结构化请求/上游日志
5. 单实例基线限流

它不负责把上游业务逻辑搬进网关；用户侧 `billing/orders/refunds/tickets/icp/files/citations` 仍然只是 BFF / 兼容聚合层，真实业务状态仍以后端服务为准。

## 当前路由面

- 用户侧统一入口：`/api/v1/auth/*`、`/api/v1/users/me*`、`/api/v1/chat/*`、`/api/v1/marketing/*`、`/api/v1/research/*`
- 用户侧 BFF：`/api/v1/billing/*`、`/api/v1/orders*`、`/api/v1/refunds*`、`/api/v1/tickets*`、`/api/v1/icp*`、`/api/v1/files*`、`/api/v1/citations/*`
- 管理侧入口：`/api/v1/admin/dashboard/summary`、`/api/v1/admin/knowledge-bases*`、`/api/v1/admin/knowledge-documents*`、`/api/v1/admin/jobs/*`、`/api/v1/admin/retrieval/*`
- owner-local / debug 代理：`/api/knowledge/v1/*`、`/api/rag/v1/*`

## 工程强化现状

### 结构化日志

Gateway 现在会输出三类结构化日志事件：

- `request_completed` / `request_rejected`
- `upstream_call`
- `stream_started` / `stream_completed` / `stream_aborted`

最小字段覆盖：

- 请求日志：`request_id`、`trace_id`、`method`、`path`、`subject_type`、`subject_id`、`tenant_id`、`response_status`、`latency_ms`、`rate_limit_remaining`
- 上游日志：`upstream_service`、`upstream_method`、`upstream_path`、`upstream_status`、`upstream_latency_ms`、`error_category`
- SSE 日志：开始/结束/异常中止、总字节数、事件计数、citation 缓存计数

日志约束：

- 不记录 bearer token、密码、原始附件内容
- 不记录 SSE 原始事件 payload
- 目前默认是 stdout 结构化字典日志；未接入集中式日志后端

### 限流策略

当前仍是单进程内存 fixed-window 基线，但已不是最早的 `client_host:path` 粗粒度版本：

- 健康检查与 `OPTIONS` 预检豁免
- 聊天 SSE 单独 bucket（`chat_sse`）与更低阈值
- 已区分 authenticated / tenant / anonymous / chat-anon key
- 对写请求会继续补齐并透传幂等键

已知限制：

- 仍然不是 Redis / shared backend 限流
- 多实例部署不会共享桶状态
- 认证前匿名流量仍只能按 host/path 或 tenant/path 粗分桶

## SSE 行为

- 保持 upstream event-stream 原样透传，不改写事件体
- 网关只做 citation 旁路缓存，供 `/api/v1/citations/{citation_id}` 查询
- 记录 stream_started / stream_completed / stream_aborted，但不落 raw payload

## 依赖服务与默认端口

| 服务 | 默认地址 |
| --- | --- |
| `auth-user-service` | `http://localhost:8001` |
| `marketing-service` | `http://localhost:8002` |
| `research-service` | `http://localhost:8003` |
| `orchestrator-service` | `http://localhost:8010` |
| `tool-hub-service` | `http://localhost:8020` |
| `business-tools-service` | `http://localhost:8030` |
| `knowledge-service` | `http://localhost:8031` |
| `rag-service` | `http://localhost:8040` |

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SMARTCLOUD_CORS_ALLOWED_ORIGINS` | `http://localhost:5173,...` | 允许的浏览器来源 |
| `SMARTCLOUD_REQUEST_TIMEOUT_MS` | `10000` | upstream HTTP 超时 |
| `SMARTCLOUD_REQUEST_ID_HEADER` | `X-Request-Id` | request id header 名称 |
| `SMARTCLOUD_TRACE_ID_HEADER` | `X-Trace-Id` | trace id header 名称 |
| `SMARTCLOUD_TENANT_ID_HEADER` | `X-Tenant-Id` | tenant id header 名称 |
| `SMARTCLOUD_CALLER_SERVICE_HEADER` | `X-Caller-Service` | internal caller header 名称 |
| `SMARTCLOUD_IDEMPOTENCY_KEY_HEADER` | `Idempotency-Key` | 幂等键 header 名称 |
| `SMARTCLOUD_OPERATOR_REASON_HEADER` | `X-Operator-Reason` | admin 写审计 header 名称 |
| `AUTH_USER_SERVICE_BASE_URL` | `http://localhost:8001` | auth upstream |
| `MARKETING_SERVICE_BASE_URL` | `http://localhost:8002` | marketing upstream |
| `RESEARCH_SERVICE_BASE_URL` | `http://localhost:8003` | research upstream |
| `ORCHESTRATOR_SERVICE_BASE_URL` | `http://localhost:8010` | orchestrator upstream |
| `TOOL_HUB_SERVICE_BASE_URL` | `http://localhost:8020` | tool-hub upstream |
| `BUSINESS_TOOLS_SERVICE_BASE_URL` | `http://localhost:8030` | business-tools upstream |
| `KNOWLEDGE_SERVICE_BASE_URL` | `http://localhost:8031` | knowledge upstream |
| `RAG_SERVICE_BASE_URL` | `http://localhost:8040` | rag upstream |
| `GATEWAY_STORE_PATH` | `apps/gateway-service/data/gateway-store.json` | gateway 本地兼容读模型与 citation / 文件缓存 |
| `GATEWAY_RATE_LIMIT_REQUESTS` | `120` | 普通请求固定窗口阈值 |
| `GATEWAY_RATE_LIMIT_WINDOW_SECONDS` | `60` | 固定窗口秒数 |

## 运行方式

```bash
cd /home/ljr/SmartCloud-X/apps/gateway-service
/home/ljr/SmartCloud-X/.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

## 验证

```bash
PYTHONPATH="/home/ljr/SmartCloud-X/apps/gateway-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" \
/home/ljr/SmartCloud-X/.venv/bin/pytest \
/home/ljr/SmartCloud-X/apps/gateway-service/tests/test_gateway_api.py

cd /home/ljr/SmartCloud-X && \
/home/ljr/SmartCloud-X/.venv/bin/python -m compileall apps/gateway-service/app

cd /home/ljr/SmartCloud-X/apps/gateway-service && \
/home/ljr/SmartCloud-X/.venv/bin/python -m uvicorn app.main:app --reload --port 8000

cd /home/ljr/SmartCloud-X && \
/home/ljr/SmartCloud-X/.venv/bin/python scripts/qa/gateway_acceptance_probe.py --base-url http://127.0.0.1:8000 --timeout 30
```

## 已知限制

- `/readyz` 与 acceptance probe 依赖全部 upstream 可连通；若上游未启动，网关会如实报 `not_ready`
- 限流仍为单实例内存基线，不适合直接当作生产多副本方案
- 当前日志是 stdout 结构化输出，未带集中采集、采样、脱敏策略中心化配置
- owner-local 路由仍属于联调 / debug 面，不应对外作为正式公开契约
- gateway 当前对本地依赖抛出的 `HTTPException` 仍保持 FastAPI 默认 `detail` 结构；本轮已用测试锁定该现状，但若后续要求所有 4xx/5xx 都统一为 canonical envelope，需要新增全局异常封装层并同步更新契约文档
