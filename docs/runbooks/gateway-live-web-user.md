# Gateway Live Web User Runbook

## 目标

用真实 `gateway-service` 作为 `web-user` 的统一 API 入口，让前端在 `VITE_USE_MOCK_API=false` 下通过 `http://localhost:8000` 完成真实交互。

## 前置环境变量分层

### 必须配置

- `SMARTCLOUD_MYSQL_DSN`
- `SMARTCLOUD_MONGODB_URI`
- `SMARTCLOUD_MONGODB_DATABASE`
- `SMARTCLOUD_REDIS_URL`
- `SMARTCLOUD_MINIO_ENDPOINT`
- `SMARTCLOUD_MINIO_BUCKET`
- `SMARTCLOUD_MINIO_ACCESS_KEY`
- `SMARTCLOUD_MINIO_SECRET_KEY`
- `SMARTCLOUD_QDRANT_URL`
- `SMARTCLOUD_OPENSEARCH_URL`
- `SMARTCLOUD_JWT_SECRET`
- `VITE_API_BASE_URL=http://localhost:8000`
- `VITE_USE_MOCK_API=false`

### 可选增强

- `SMARTCLOUD_LLM_API_KEY`
- `SMARTCLOUD_LLM_BASE_URL`
- `SMARTCLOUD_LLM_MODEL`
- `SMARTCLOUD_EMBEDDING_PROVIDER`
- `SMARTCLOUD_EMBEDDING_API_URL`
- `SMARTCLOUD_EMBEDDING_API_KEY`
- `SMARTCLOUD_EMBEDDING_MODEL`
- `SMARTCLOUD_DIFY_EXTERNAL_KNOWLEDGE_API_KEY`

### 仅观测性

- `SMARTCLOUD_TRACE_ENABLED`
- `SMARTCLOUD_PHOENIX_COLLECTOR_ENDPOINT`
- `OTEL_EXPORTER_OTLP_ENDPOINT`
- `OTEL_EXPORTER_OTLP_PROTOCOL`
- `LANGSMITH_*`

### 前端构建变量

- `VITE_API_BASE_URL=http://localhost:8000`
- `VITE_USE_MOCK_API=false`
- `VITE_KNOWLEDGE_SERVICE_BASE_URL=http://localhost:8031/api/knowledge/v1`（仅 `web-admin`）
- `VITE_RAG_SERVICE_BASE_URL=http://localhost:8040/api/rag/v1`（仅 `web-admin`）
- `VITE_OPERATOR_REASON_HEADER=X-Operator-Reason`（仅 `web-admin`）

## canonical 端口

| 服务 | 地址 |
| --- | --- |
| `gateway-service` | `http://localhost:8000` |
| `auth-user-service` | `http://localhost:8001` |
| `marketing-service` | `http://localhost:8002` |
| `research-service` | `http://localhost:8003` |
| `orchestrator-service` | `http://localhost:8010` |
| `tool-hub-service` | `http://localhost:8020` |
| `business-tools-service` | `http://localhost:8030` |
| `knowledge-service` | `http://localhost:8031` |
| `rag-service` | `http://localhost:8040` |

关键对齐：
- host-side `knowledge-service` 是 `8031`
- compose-network `knowledge-service` 是 `knowledge-service:8030`
- host-side `rag-service` 指向 knowledge 时应使用 `KNOWLEDGE_SERVICE_BASE_URL=http://localhost:8031`
- `web-admin` 默认 knowledge base URL 必须是 `http://localhost:8031/api/knowledge/v1`

## 启动顺序

### 1. 启动基础依赖

建议先准备：MySQL、MongoDB、Redis、MinIO、Qdrant、OpenSearch、Phoenix。

如果走 compose：

```bash
cp deploy/docker-compose/.env.example deploy/docker-compose/.env
docker compose -f deploy/docker-compose/docker-compose.yml up --build
```

### 2. 启动后端 upstream

手工启动建议顺序：

```powershell
cd apps/auth-user-service
python -m uvicorn app.main:app --reload --port 8001

cd apps/business-tools
$env:PYTHONPATH="src"
python -m uvicorn business_tools_service.main:app --reload --port 8030

cd apps/tool-hub-service
python -m uvicorn app.main:app --reload --port 8020

cd apps/knowledge-service
python -m uvicorn app.main:app --reload --port 8031

cd apps/marketing-service
python -m uvicorn app.main:app --reload --port 8002

cd apps/research-service
python -m uvicorn app.main:app --reload --port 8003

cd apps/orchestrator-service
python -m uvicorn app.main:app --reload --port 8010

cd apps/rag-service
$env:KNOWLEDGE_SERVICE_BASE_URL="http://localhost:8031"
python -m uvicorn app.main:app --reload --port 8040
```

### 3. 启动 gateway

```powershell
cd apps/gateway-service
python -m uvicorn app.main:app --reload --port 8000
```

### 4. 启动 web-user live 模式

```powershell
cd apps/web-user
$env:VITE_USE_MOCK_API="false"
$env:VITE_API_BASE_URL="http://localhost:8000"
npm run dev
```

## 验证顺序

### 1. readiness 检查

```bash
curl -sS http://127.0.0.1:8001/readyz | jq .
curl -sS http://127.0.0.1:8030/readyz | jq .
curl -sS http://127.0.0.1:8020/readyz | jq .
curl -sS http://127.0.0.1:8010/readyz | jq .
curl -sS http://127.0.0.1:8031/readyz | jq .
curl -sS http://127.0.0.1:8040/readyz | jq .
curl -sS http://127.0.0.1:8000/readyz | jq .
```

必须确认 gateway `/readyz` 中 required upstream 都存在，且 `contract="readyz"`。

### 2. HTTP acceptance probe

```bash
python3 scripts/qa/gateway_acceptance_probe.py --base-url http://127.0.0.1:8000
```

该 probe 会验证：
- `healthz`
- `readyz`
- 未登录 chat 返回 `401`
- 登录、`auth/me`
- chat session create
- chat SSE stream
- marketing / research / orders / refunds / tickets / ICP / upload

### 3. 前端 live 验证

- 登录：`demo@smartcloud.local / Password123!`
- 核心路径：
  - 聊天建会话 + 流式回答
  - 营销活动列表
  - 研究任务创建
  - 订单列表 + 退款提交
  - 工单创建 / 回复
  - ICP 材料检查 / 申请提交
  - 文件上传策略 / 完成登记

## 发布式命令

```bash
scripts/qa/run_full_stack_validation.sh
python3 scripts/qa/release_readiness.py --strict
```

如果环境支持更强验证：

```bash
SMARTCLOUD_QA_RUN_COMPOSE=1 SMARTCLOUD_QA_RUN_TRACE=1 scripts/qa/run_full_stack_validation.sh
```

## 常见问题

### `readyz` 不通过

- 先检查基础依赖是否已就绪
- 再检查 gateway `/readyz` 的 `not_ready_upstreams`
- 对于 `knowledge-service` / `rag-service`，确认 knowledge 端口和 RAG 上游 knowledge 地址没有配错

### web-user 仍走 mock

- 确认 `VITE_USE_MOCK_API=false`
- 确认 `VITE_API_BASE_URL=http://localhost:8000`
- 确认浏览器控制台没有旧的 `runtime-config.js` 覆盖

### web-admin 打到错误 knowledge 端口

- 确认 `VITE_KNOWLEDGE_SERVICE_BASE_URL=http://localhost:8031/api/knowledge/v1`
- 不要把 host-side knowledge URL 配成 `http://localhost:8030/...`

### chat 通过但 citation 是占位符

- `scripts/qa/gateway_acceptance_probe.py` 已把 `baseline://` 视为失败
- 若 live 页面仍出现占位引用，继续检查 orchestrator/rag 路径，而不要把它当作主链路通过证据
