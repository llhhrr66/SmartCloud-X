# AGENTS.md

## 项目概述
- 名称：SmartCloud-X
- 定位：面向业务工具、知识检索与多服务编排的 Python monorepo
- 一句话描述：一个以 gateway、auth、orchestrator、tool-hub、business-tools、knowledge、rag 为核心，配套 web-user、web-admin、OpenAPI、shared schemas、QA 门禁与本地 compose 基线的可运行多服务仓库。

## 技术栈
- 后端：Python 3.11、FastAPI、Pydantic、部分 dataclass 配置
- 前端：Vite、TypeScript、React 风格前端应用（`apps/web-admin`、`apps/web-user`）
- AI/LLM：OpenAI-compatible API、LLM Function Calling（tool_use）驱动的工具调用循环
- 数据与运行时：MySQL、Redis、MongoDB、MinIO、Qdrant、OpenSearch
- 服务间通信：HTTP/JSON、SSE
- 观测性：Prometheus `/metrics`、OTLP tracing、Phoenix、Grafana、cAdvisor
- 契约与共享：OpenAPI 3.x、`packages/common-schemas`、`packages/frontend-sdk`
- CI/CD：GitHub Actions（测试 + 自动部署）
- 部署：Docker Compose 本地基线，Kubernetes 迁移说明在 `deploy/k8s/README.md`

## 目录结构
- `apps/`
  - `gateway-service/`：统一入口、BFF、代理、SSE 透传、聚合 readiness
  - `auth-user-service/`：用户登录、刷新、管理员认证、内部鉴权
  - `marketing-service/`：营销任务与 worker 路径
  - `research-service/`：研究任务路径
  - `orchestrator-service/`：会话、chat、SSE、LLM 工具调用循环、Agent 编排
  - `tool-hub-service/`：工具发现、preflight、invoke 中间层
  - `business-tools/`：订单/退款/工单/ICP 等业务工具服务
  - `knowledge-service/`：知识库、文档、导入、索引、admin、Dify external
  - `rag-service/`：检索、诊断、回答、admin diagnostics
  - `web-admin/`：管理台，直连 knowledge/rag
  - `web-user/`：用户前端，走 gateway
- `deploy/`
  - `docker-compose/docker-compose.yml`：本地整栈部署基线
  - `docker-compose/.env.example`：环境变量模板
  - `docker-compose/smoke-test.py`：compose smoke 验证
  - `docker-compose/trace-smoke.py`：OTLP tracing 验证
  - `k8s/README.md`：Kubernetes 映射说明
- `.github/workflows/ci-cd.yml`：GitHub Actions CI/CD 流水线
- `docs/runbooks/`
  - `local-validation.md`：本地验证与 readiness 解释
  - `release-readiness.md`：发布门禁与证据要求
  - `gateway-live-web-user.md`：web-user live 路径说明
- `scripts/qa/`
  - `gateway_acceptance_probe.py`：统一入口真实验收探针
  - `run_full_stack_validation.sh`：全栈验证脚本
  - `release_readiness.py`：strict release gate
  - `project_smoke.py`、`infra_persistence_matrix.py`、`verify_openapi_contracts.py` 等 QA 资产
- `openapi/`：服务级 OpenAPI 基线
- `packages/`：共享 schema、frontend SDK 等

## 现有模块
- Gateway：统一 API 入口、健康聚合、认证前置、聊天流式代理、citation 缓存
- Auth：登录、refresh、profile、admin login、internal validate-token
- Orchestrator：会话管理、SSE、LLM 工具调用循环、Agent 编排、tool-hub 协同、RAG 引用链路
- Tool Hub / Business Tools：工具发现、预检、调用、幂等、查询缓存
- Knowledge：知识库/文档/admin/import/runtime sync/index target/对象存储链路
- RAG：knowledge readiness 探测、检索缓存、诊断、回答预览
- Marketing / Research：业务侧异步与任务链路
- Web Admin / Web User：分别承担管理侧与用户侧联调入口
- QA / Release：OpenAPI 校验、smoke、gateway acceptance、strict readiness

## AI Agent 体系

Orchestrator 管理 5 个 AI Agent，每个 Agent 绑定特定业务域的工具集：

| Agent | 职责 | 可用工具域 |
|-------|------|-----------|
| product_tech_agent | 云产品咨询、实例推荐、规格对比 | product |
| finance_order_agent | 账单查询、退款申请、发票开具 | billing |
| icp_service_agent | ICP 备案咨询、材料提交、进度查询 | icp |
| ops_marketing_agent | 营销活动查询、海报/文案生成、推广链接 | marketing |
| deep_research_agent | 技术选型分析、行业调研、报告生成 | research |

### LLM 工具调用循环

Orchestrator 采用 LLM Function Calling 模式选择和调用业务工具（BetaToolRunner 模式）：

1. Router 根据用户 query 关键词路由到对应 Agent
2. 将 Agent 可用工具的 JSON Schema 传入 LLM `tools=` 参数
3. LLM 返回 `tool_calls`，决定调用哪些工具
4. 执行工具调用（hydrate payload → preflight → invoke），将结果作为 `tool` 消息回传 LLM
5. 循环直到 LLM 不再请求工具或达到最大轮次
6. LLM 生成最终文本回答

关键行为：
- 高风险工具（`high_risk=True`，如退款、发票）自动降级为 `operation="preview"`，需确认后执行
- `hydrate_payload_from_session_context` 自动从会话上下文补全缺失参数
- 关键词路由作为备用路径，在 LLM 不可用时自动切换（`tool_call_enabled=False` 或 `llm_ready()=False`）

关键文件：
- `apps/orchestrator-service/app/services/llm_tool_call_loop.py`：核心循环
- `apps/orchestrator-service/app/services/tool_schema_adapter.py`：ToolDefinition → OpenAI tools 格式转换
- `apps/orchestrator-service/app/services/agent_runtime.py`：双路径执行（LLM / keyword）
- `apps/orchestrator-service/app/services/router.py`：Agent 路由
- `apps/orchestrator-service/app/prompts/agents/*/system.v1.0.md`：Agent 系统提示词

## CI/CD 自动化部署

### 流水线配置

GitHub Actions 流水线定义在 `.github/workflows/ci-cd.yml`，自动执行：

```
push to main
  │
  ▼
Job 1: Test
  ├── checkout 代码
  ├── 安装 Python 3.11
  ├── 安装 orchestrator + business-tools 依赖
  └── 运行 pytest（排除 test_saga/test_api/test_runtime）
  │
  ▼ （测试通过）
Job 2: Deploy
  └── SSH 到生产服务器
       ├── git pull origin main
       └── docker compose up --build -d
```

**触发条件：**
- `push` 到 `main` 分支：测试 + 自动部署
- `pull_request` 到 `main` 分支：仅测试

**GitHub Secrets 配置（已设置）：**

| Secret | 用途 |
|--------|------|
| DEPLOY_HOST | 部署服务器 IP |
| DEPLOY_USER | SSH 用户名 |
| DEPLOY_SSH_KEY | 部署专用 SSH 私钥 |
| DEPLOY_SSH_PORT | SSH 端口 |
| DEPLOY_PATH | 项目在服务器上的路径 |

**部署流程：**
1. 代码推送到 main → GitHub Actions 自动触发
2. 在 GitHub Runner 上运行测试
3. 测试通过后，通过 SSH 连接服务器
4. 执行 `git pull origin main` 拉取最新代码
5. 执行 `docker compose up --build -d` 重建并启动服务
6. 完成后输出时间戳

**验证部署状态：**
```bash
# 查看 GitHub Actions 运行状态
gh run list --repo llhhrr66/SmartCloud-X

# 查看具体运行详情
gh run view <run-id> --repo llhhrr66/SmartCloud-X

# 在服务器上检查服务状态
docker compose -f deploy/docker-compose/docker-compose.yml ps
```

### 如何修改代码并自动部署

1. 在本地修改代码
2. `git add <修改的文件>`
3. `git commit -m "描述修改内容"`
4. `git push origin main`
5. 等待 GitHub Actions 自动完成测试和部署

## 编码规范摘要
- Python：文件、函数、变量使用 `snake_case`；类使用 `PascalCase`；常量使用 `UPPER_SNAKE_CASE`
- API：外部路径以 `/api/v1/...` 为主，内部路径以 `/internal/v1/...` 为主
- 健康检查：`/healthz` 表示存活/退化诊断；`/readyz` 表示流量门禁
- 错误响应：多数服务采用 canonical error envelope，核心错误码包括 `4001001`、`4010002`、`4030001`
- Header 约定：`X-Request-Id`、`X-Trace-Id`、`X-Tenant-Id`、`X-Caller-Service`、`X-Operator-Reason` 等
- 环境变量：共享运行时统一 `SMARTCLOUD_*`，前端构建期统一 `VITE_*`
- Git：不提交 `.env`、密钥、数据库文件；`.gitignore` 已排除敏感内容
- 详细规范见：`specs/tech-spec.md`

## 部署方式
- 标准本地启动：
  ```bash
  cp deploy/docker-compose/.env.example deploy/docker-compose/.env
  docker compose -f deploy/docker-compose/docker-compose.yml up --build
  ```
- 标准验证入口：
  ```bash
  source scripts/qa/qa_env.sh
  smartcloud_qa_init
  export SMARTCLOUD_QA_USER_PASSWORD='<qa-user-password>'
  export SMARTCLOUD_QA_ADMIN_PASSWORD='<qa-admin-password>'
  python3 deploy/docker-compose/smoke-test.py
  "${QA_PYTHON[@]}" scripts/qa/gateway_acceptance_probe.py
  scripts/qa/run_full_stack_validation.sh
  python3 scripts/qa/release_readiness.py --strict
  ```
- 默认关键端口：gateway 8000、auth 8001、marketing 8002、research 8003、orchestrator 8010、tool-hub 8020、business-tools 8030、knowledge 8031、rag 8040、web-admin 8050、web-user 3100
- 发布判定不以文档或单测为准，必须以 readiness、smoke、acceptance、strict gate 与 known-issues 状态共同判定

## 关键配置项

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| TOOL_CALL_ENABLED | true | 启用 LLM 工具调用（关闭则走关键词路径） |
| MAX_TOOL_CALL_ROUNDS | 5 | LLM 工具调用最大轮次 |
| SMARTCLOUD_LLM_API_KEY | - | LLM API 密钥 |
| SMARTCLOUD_LLM_BASE_URL | - | LLM API 地址 |
| SMARTCLOUD_LLM_MODEL | - | LLM 模型名称 |
| SMARTCLOUD_LLM_TIMEOUT_SECONDS | 20 | LLM 调用超时 |

## 仓库地址
- GitHub：https://github.com/llhhrr66/SmartCloud-X
