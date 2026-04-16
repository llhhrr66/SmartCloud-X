# Supervisor Ownership

## 目标
明确 SmartCloud-X 多 supervisor 并行开发时的目录边界、冻结区、变更申请机制与停止标准。

## 冻结区（默认仅 foundation 可修改）
- `packages/common/`
- `packages/common-schemas/`
- `packages/common-auth/`
- `docs/contracts/`（除 `change-requests/`）
- `openapi/`
- `.env.example`

## 工作流边界

### 1. supervisor-foundation
负责目录：
- `packages/common/`
- `packages/common-schemas/`
- `packages/common-auth/`
- `docs/contracts/`
- `openapi/`
- 根目录基础骨架文件

禁止修改：
- `apps/web-user/`
- `apps/web-admin/`
- `apps/rag-service/`
- `apps/knowledge-service/`
- `apps/orchestrator-service/` 业务细节

### 2. supervisor-web-user
负责目录：
- `apps/web-user/`

禁止修改：
- 冻结区
- 任意后端服务目录

### 3. supervisor-orchestrator
负责目录：
- `apps/orchestrator-service/`
- `apps/tool-hub-service/`
- `apps/business-tools/`

禁止修改：
- 冻结区
- 前端目录
- `apps/rag-service/`
- `apps/knowledge-service/`

### 4. supervisor-knowledge-rag
负责目录：
- `apps/knowledge-service/`
- `apps/rag-service/`
- `apps/web-admin/`
- `deploy/`
- `observability/`

禁止修改：
- 冻结区
- `apps/web-user/`
- `apps/orchestrator-service/`

### 5. supervisor-auth-marketing-research
负责目录：
- `apps/auth-user-service/`
- `apps/research-service/`
- `apps/marketing-service/`

禁止修改：
- 冻结区
- `apps/web-user/`
- `apps/web-admin/`
- `apps/orchestrator-service/`
- `apps/rag-service/`
- `apps/knowledge-service/`

### 6. supervisor-frontend-sdk
负责目录：
- `packages/frontend-sdk/`

禁止修改：
- 冻结区（除明确分配的 `packages/frontend-sdk/` 外）
- `apps/orchestrator-service/`
- `apps/tool-hub-service/`
- `apps/business-tools/`
- `apps/knowledge-service/`
- `apps/rag-service/`
- `apps/auth-user-service/`
- `apps/research-service/`
- `apps/marketing-service/`

说明：
- 允许在 `apps/web-user/`、`apps/web-admin/` 中做最小接入适配，但应以替换 app-local adapter/DTO 为目标，避免越权改业务页面逻辑

### 7. supervisor-integration-qa
负责目录：
- `tests/`
- `scripts/qa/`
- `docs/runbooks/`
- `docs/reviews/`

禁止修改：
- 不直接修改业务实现目录
- 若发现 contract 不足，走 `docs/contracts/change-requests/`
- 若需要补充测试支撑代码，应限制在测试/QA/评审目录内

## 当前未分配的共享包占位
- 无

## 变更申请机制
如果 supervisor 发现 contract 或 schema 不足：
1. 不直接修改冻结区
2. 在 `docs/contracts/change-requests/` 下新增 markdown 申请
3. 由 foundation 工作流统一裁决并实施修改

## 统一日志要求
每个 supervisor 必须维护：
- `progress.log`
- `blockers.log`
- `decisions.log`
- `state.json`

## 通用停止标准
每个 supervisor 只有在以下条件同时满足时才允许停止：
1. 负责目录内目标能力完成
2. 最小验证通过
3. 进度、阻塞、决策日志已更新
4. 已输出对应 status 文档
