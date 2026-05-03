# AGENTS.md

## 项目概述
- 名称：SmartCloud-X
- 定位：面向业务工具、知识检索与多服务编排的 Python monorepo
- 一句话描述：一个以 gateway、auth、orchestrator、tool-hub、business-tools、knowledge、rag 为核心，配套 web-user、web-admin、OpenAPI、shared schemas、QA 门禁与本地 compose 基线的可运行多服务仓库。

## 技术栈
- 后端：Python 3、FastAPI、Pydantic、部分 dataclass 配置
- 前端：Vite、TypeScript、React 风格前端应用（`apps/web-admin`、`apps/web-user`）
- 数据与运行时：MySQL、Redis、MongoDB、MinIO、Qdrant、OpenSearch、JSON/SQLite fallback
- 服务间通信：HTTP/JSON、SSE
- 观测性：Prometheus `/metrics`、OTLP tracing、Phoenix、Grafana、cAdvisor
- 契约与共享：OpenAPI 3.x、`packages/common-schemas`、`packages/frontend-sdk`
- 部署：Docker Compose 本地基线，Kubernetes 迁移说明在 `deploy/k8s/README.md`

## 目录结构
- `apps/`
  - `gateway-service/`：统一入口、BFF、代理、SSE 透传、聚合 readiness
  - `auth-user-service/`：用户登录、刷新、管理员认证、内部鉴权
  - `marketing-service/`：营销任务与 worker 路径
  - `research-service/`：研究任务路径
  - `orchestrator-service/`：会话、chat、SSE、tool-hub 协作、RAG 协作
  - `tool-hub-service/`：工具发现、preflight、invoke 中间层
  - `business-tools/`：订单/退款/工单/ICP 等业务工具服务
  - `knowledge-service/`：知识库、文档、导入、索引、admin、Dify external
  - `rag-service/`：检索、诊断、回答、admin diagnostics
  - `web-admin/`：管理台，当前直连 knowledge/rag
  - `web-user/`：用户前端，真实联调应走 gateway
- `deploy/`
  - `docker-compose/docker-compose.yml`：本地整栈部署基线
  - `docker-compose/.env.example`：环境变量模板
  - `docker-compose/smoke-test.py`：compose smoke 验证
  - `docker-compose/trace-smoke.py`：OTLP tracing 验证
  - `k8s/README.md`：Kubernetes 映射说明
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
- `specs/`：需求与技术规范文档

## 现有模块
- Gateway：统一 API 入口、健康聚合、认证前置、聊天流式代理、citation 缓存
- Auth：登录、refresh、profile、admin login、internal validate-token
- Orchestrator：会话管理、SSE、tool-hub 协同、RAG 引用链路
- Tool Hub / Business Tools：工具发现、预检、调用、幂等、查询缓存
- Knowledge：知识库/文档/admin/import/runtime sync/index target/对象存储链路
- RAG：knowledge readiness 探测、检索缓存、诊断、回答预览
- Marketing / Research：业务侧异步与任务链路
- Web Admin / Web User：分别承担管理侧与用户侧联调入口
- QA / Release：OpenAPI 校验、smoke、gateway acceptance、strict readiness

## 编码规范摘要
- Python：文件、函数、变量使用 `snake_case`；类使用 `PascalCase`；常量使用 `UPPER_SNAKE_CASE`
- API：外部路径以 `/api/v1/...` 为主，内部路径以 `/internal/v1/...` 为主
- 健康检查：`/healthz` 表示存活/退化诊断；`/readyz` 表示流量门禁
- 错误响应：多数服务采用 canonical error envelope，核心错误码包括 `4001001`、`4010002`、`4030001`
- Header 约定：`X-Request-Id`、`X-Trace-Id`、`X-Tenant-Id`、`X-Caller-Service`、`X-Operator-Reason` 等
- 环境变量：共享运行时统一 `SMARTCLOUD_*`，前端构建期统一 `VITE_*`
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
  # optional identity overrides:
  # export SMARTCLOUD_QA_USER_ACCOUNT='<qa-user-account>'
  # export SMARTCLOUD_QA_ADMIN_USERNAME='<qa-admin-username>'
  python3 deploy/docker-compose/smoke-test.py
  "${QA_PYTHON[@]}" scripts/qa/gateway_acceptance_probe.py
  scripts/qa/run_full_stack_validation.sh
  python3 scripts/qa/release_readiness.py --strict
  ```
- 默认关键端口：gateway 8000、auth 8001、marketing 8002、research 8003、orchestrator 8010、tool-hub 8020、business-tools 8030、knowledge 8031、rag 8040、web-admin 8050、web-user 3100
- 发布判定不以文档或单测为准，必须以 readiness、smoke、acceptance、strict gate 与 known-issues 状态共同判定

## 本次文档更新记录
- `docs/runbooks/local-validation.md`（更新）：补齐 gateway acceptance 与 full-stack validation 的 QA 双密码前置条件，明确需先 `source scripts/qa/qa_env.sh && smartcloud_qa_init`，并说明 `SMARTCLOUD_QA_USER_PASSWORD`、`SMARTCLOUD_QA_ADMIN_PASSWORD` 以及可选账号覆盖变量。
- `docs/runbooks/release-readiness.md`（更新）：补齐 release-style / full-stack 执行示例中的 QA 双密码前置条件，保持 runbook 与 `qa_env.sh`、`run_full_stack_validation.sh` 当前实现一致。
- `AGENTS.md`（更新）：补齐标准验证入口的 QA 环境初始化、双密码前置条件与可选账号覆盖变量说明。
- `docs/runbooks/release-readiness.md`（更新）：移除对工作区 `tasks/*.md` 的正式运行证据引用，改为引用 `docs/status/supervisor-siliconflow-embedding-status.md` 作为稳定仓库内证据路径，并保持 SiliconFlow live 切换边界表述准确。
- `docs/runbooks/local-validation.md`（更新）：移除对工作区 `tasks/*.md` 的正式运行证据引用，改为引用 `docs/status/supervisor-siliconflow-embedding-status.md`，并保留“代码路径存在 ≠ 当前 running live 已切换”的验证口径。
- `docs/status/supervisor-integration-qa-status.md`（更新）：将 SiliconFlow 补充验证锚点切换为仓库内稳定状态文档，不再直接引用工作区 `tasks/*.md` 作为正式运行证据。
- `docs/reviews/known-issues.md`（更新）：按 Round 9 运行/验收证据收口 strict blockers，调整 `QA-001`、`QA-005`、`QA-006` 的严重级别/状态，使文档与当前 gate 事实对齐。
- `docs/status/supervisor-integration-qa-status.md`（更新）：按 `logs/supervisor-integration-qa/state.json` 与最新脚本结果对齐 QA 状态摘要，明确 live knowledge/rag connector proof 为 green；Round 10 中仅剩的 `qa-reporting-consistent` 文档一致性阻塞已在 Round 11 strict rerun 中被验证为清除，当前仓库级 strict gate 证据为 green，并补充 SiliconFlow live 切换未真实完成但不影响当前已通过门禁的说明。
- `docs/runbooks/release-readiness.md`（更新）：补充当前仓库级门禁已具备通过证据的说明，明确 Round 9 gateway acceptance `23/23` 与 Round 11 strict gate `ok=true` 为当前有效运行/发布证据；新增 external embedding/provider 口径，说明 OpenAI-compatible 代码路径已存在，但 running knowledge-service 未被独立复核为已切换到 SiliconFlow `BAAI/bge-m3`。
- `docs/runbooks/local-validation.md`（更新）：补充当前正式门禁已通过的仓库基线说明，增加 `knowledge-service` `/api/knowledge/v1/embedding:test` 的本地核查方式，并明确当前 live SiliconFlow 切换未真实完成，不得把 `hash-baseline` 运行态误写成外部 embedding 已落地。
- `docs/status/supervisor-gateway-status.md`（更新）：把 gateway 状态从“acceptance/strict gate blocked”改为“已有 Round 9 acceptance 与 Round 11 strict gate 通过证据”，同步更新结论、运行证据与后续建议。
- `docs/status/supervisor-knowledge-rag-status.md`（更新）：把 knowledge/rag 文档中的 strict-gate blocked 口径改为已有通过证据，并补充 OpenAI-compatible embedding 代码基础与 SiliconFlow live 切换独立复核未通过的边界说明。
- `docs/status/supervisor-web-admin-status.md`（更新）：把 web-admin 文档中的 release-blocked 口径改为已有 strict gate 通过证据，同时继续强调 admin 后端链路必须以 runtime readiness 与接口验收为准。
