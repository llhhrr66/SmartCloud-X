# SmartCloud-X

基于 `/home/ljr/SmartCloud/kaifawendang.md` 的执行级开发规范建立的项目骨架。

当前状态：
- 已完成项目目录初始化
- 已建立 supervisor 并行开发的目录边界与治理文件
- 已创建 7 个 supervisor 启动脚本模板与对应检查脚本
- 已完成 foundation-owned baseline（公共包占位、共享 schema/auth、contract 文档、OpenAPI 基线、根配置与状态工件）
- 已补齐当前 orchestrator / tool-hub / business-tools 内部契约与 OpenAPI 对齐面
- 已补齐 orchestrator 会话管理 / chat completion 冻结合同，包括共享 DTO、错误码与 OpenAPI 占位
- 已补齐用户侧 canonical envelope、研究/营销任务历史占位契约，以及状态快照 / Saga 补偿共享 schema 基线
- 已补齐 orchestrator SSE、tool-call audit 读取、以及写工具幂等重放/冲突语义的冻结共享合同
- 已补齐 admin `/api/v1/admin/**` 知识库/诊断占位合同，以及 orchestrator/tool-hub/business-tools 回滚补偿冻结合同
- 已补齐 `auth-user-service` 的用户登录/账户、管理员认证引导、以及内部鉴权校验 OpenAPI 占位与共享 schema 基线
- 已补齐 admin 文档详情 / 异步任务查询占位合同，以及 agent/tool 元数据共享 schema 基线
- 已补齐 tool session-context 绑定 / 依赖元数据，以及 orchestrator tool-plan/handoff 依赖就绪度共享 schema 基线
- 已对齐 7 supervisor ownership model 与共享 service registry，补全 `supervisor-auth-marketing-research` / `supervisor-frontend-sdk` / `supervisor-integration-qa` 的根级校验一致性
- 已补齐 marketing copy / promotion-link 用户合同、orchestrator continue / cancel 共享合同，以及 business-tools provider-backed discovery / preflight 冻结合同
- 已补齐共享持久化/运行态基线，包括 `SMARTCLOUD_MYSQL_DSN` / `SMARTCLOUD_REDIS_URL` / `SMARTCLOUD_MINIO_*` 根级约定、服务级 persistence matrix、runtime-health/readiness 文档、以及 orchestrator/tool-hub/business-tools `/readyz` 合同

## 开发规范来源
- `/home/ljr/SmartCloud/kaifawendang.md`

## 并行开发工作流
1. foundation / common / contracts
2. web-user
3. orchestrator + agents + tool-hub + business-tools
4. knowledge + rag + admin + deploy
5. auth + marketing + research
6. frontend-sdk
7. integration + qa

## 冻结区
默认只有 foundation 工作流可以修改：
- `packages/common/`
- `packages/common-schemas/`
- `packages/common-auth/`
- `docs/contracts/`（除 `change-requests/` 外）
- `openapi/`
- `.env.example`

## 变更申请
其他工作流如果发现 contract 不足：
- 只允许在 `docs/contracts/change-requests/` 下提交变更申请
- 不允许直接修改冻结区

## Foundation baseline handoff
- 状态文档：`docs/status/supervisor-foundation-status.md`
- 运行日志：`logs/supervisor-foundation/`
- OpenAPI 基线：`openapi/`
