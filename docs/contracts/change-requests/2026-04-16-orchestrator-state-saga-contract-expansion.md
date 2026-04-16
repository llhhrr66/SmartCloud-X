# 变更申请：补齐会话状态快照与 Saga 补偿元数据冻结契约

## 背景
`supervisor-orchestrator` 本轮在 owned 目录内继续推进了 practical baseline：
- `orchestrator-service` 新增 `GET /api/v1/sessions/{conversation_id}/state` 会话状态快照接口
- `orchestrator-service` 响应中新增 checkpoint/event/compensation state snapshot
- `business-tools` 为已确认写工具新增 `compensation` 与 `idempotency_key` 元数据
- `tool-hub-service` / `orchestrator-service` 透传上述补偿元数据，供后续 Saga 编排使用

这些实现均未直接修改冻结区。

## 当前缺口
冻结区当前仍缺少以下契约：
1. `orchestrator-service` session state snapshot 路由与 schema
2. `OrchestratorResponse` / internal chat response 中的 `state_snapshot` schema
3. `ToolExecutionResult` / `ToolCallResponse` / business-tools execute response 中的 `compensation`、`idempotency_key` 字段
4. `SagaCompensationStep`、`ExecutionEvent`、`SessionStateSnapshot` 的共享 schema

## 建议变更
由 foundation 在冻结区补齐：
- `openapi/orchestrator-service.openapi.yaml` 中新增 `GET /api/v1/sessions/{conversation_id}/state`
- `packages/common-schemas` 中新增或扩展：
  - `orchestrator/session-state-snapshot.schema.json`
  - `orchestrator/execution-event.schema.json`
  - `orchestrator/saga-compensation-step.schema.json`
  - `tooling/tool-compensation-action.schema.json`
- 同步扩展内部 tool / execute / orchestrator response schemas，纳入：
  - `compensation`
  - `idempotency_key`
  - `state_snapshot`

## 兼容性说明
- 本次变更为 additive，不要求移除现有字段
- `state_snapshot` 可先作为 optional 字段冻结，避免阻塞其他 supervisor
- `compensation` 元数据仅对写工具生效，查询类工具保持 `null`

## 影响范围
- `apps/orchestrator-service`
- `apps/tool-hub-service`
- `apps/business-tools`
- 未来 `gateway-service` SSE/status 面板与审计链路

## 是否阻塞当前工作流
否。
当前基线已可继续开发和测试，但冻结区若不跟进，后续跨服务集成时会缺少统一的状态/补偿结构定义。

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - 在 `packages/common-schemas` 中新增 `ExecutionEvent`、`SagaCompensationStep`、`SessionStateSnapshot` 与 `ToolCompensationAction` 相关 schema
  - 扩展 orchestrator/tool-hub/business-tools 共享 schema，补齐 `state_snapshot`、`compensation`、`idempotency_key` 字段
  - 在 `openapi/orchestrator-service.openapi.yaml` 中新增 `GET /api/v1/sessions/{conversation_id}/state` 基线，并补充 `ORCH_SESSION_STATE_NOT_FOUND` 错误码文档
