# Change Request: MongoDB mainline promotion for conversation and document stores

- **Date**: 2026-04-18
- **Requester**: backend-alignment closeout
- **Owned services impacted**:
  - `apps/orchestrator-service`
  - `apps/research-service`
  - `apps/marketing-service`
  - `deploy/docker-compose`
- **Frozen areas requiring follow-up**:
  - `docs/contracts/shared/persistence-backends.md`
  - `openapi/*`

## Background

SmartCloud 开发文档将 MongoDB 定义为正式数据层的一部分，用于承接：

- `conversation_messages`
- `agent_reasoning_logs`
- `research_reports`
- `marketing_assets`
- `raw_tool_payloads`
- `session_snapshots`

此前仓库 reality 中，MongoDB 只存在于开发文档目标架构，没有进入 repo-owned runtime mainline。

## 本次 owner 实现

### `apps/orchestrator-service`

- 新增 Mongo conversation document runtime。
- 在 `ConversationStore` 的 MySQL 主线外，正式持久化：
  - `conversation_messages`
  - `agent_reasoning_logs`
  - `raw_tool_payloads`
  - `session_snapshots`
- 当 Mongo document store 已配置且写入失败时，会阻断主链而不是静默退回 JSON fallback。
- `list_messages` / retry request snapshot 读取优先走 Mongo document store。

### `apps/research-service`

- 新增 Mongo `research_reports` document runtime。
- 研究结果路由在 Mongo 已配置时通过 Mongo document runtime 物化并返回报告文档结果。
- MySQL 仍保留任务索引、状态、幂等等结构化主数据。

### `apps/marketing-service`

- 新增 Mongo `marketing_assets` document runtime。
- 海报结果路由在 Mongo 已配置时通过 Mongo document runtime 物化并返回资产文档结果。
- MySQL 仍保留任务索引、状态、幂等等结构化主数据。

## 建议冻结的职责边界

### 仍由 MySQL 负责

- 会话索引 / 任务索引 / 结构化状态 / 幂等键 / 配置等事务型或强结构化主数据

### 由 MongoDB 负责

- 长消息正文
- Agent 推理摘要与 handoff 过程记录
- 原始工具 payload
- 会话快照文档
- 研究报告文档结果
- 营销素材文档结果

## 兼容性说明

- 当前变更是 additive，不回滚现有 MySQL/Redis/MinIO/Qdrant/OpenSearch 主路径。
- local/test fallback 仍存在，但当 `SMARTCLOUD_MONGODB_URI` 已配置时，Mongo 相关读写不再视为纯可选占位。
- 当前共享 frozen contract 和 OpenAPI 仍未完整描述这些 Mongo collection 的权威职责，需要 foundation 后续 promotion。

## 建议后续冻结项

1. 在 shared persistence matrix 中新增 MongoDB 权威职责说明
2. 明确 `SMARTCLOUD_MONGODB_URI` / `SMARTCLOUD_MONGODB_DATABASE` 为 shared connector key
3. 为 orchestrator 会话消息 / snapshot / tool payload 与 research / marketing 文档结果定义 shared runtime evidence
