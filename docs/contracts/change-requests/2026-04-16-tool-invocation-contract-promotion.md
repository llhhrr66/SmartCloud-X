# 变更申请：提升 Tool Invocation Contract 为共享冻结契约

## 背景
`supervisor-orchestrator` 已在以下两个 owned 服务之间形成统一工具调用协议：
- `apps/orchestrator-service/`
- `apps/tool-hub-service/`

当前协议实现暂放在 `apps/business-tools/src/business_tools/` 下，避免直接修改冻结区。

## 当前缺口
冻结区缺少以下跨服务共享 schema / contract：
- `ToolDefinition`
- `ToolExecutionContext`
- `ToolInvocationRequest`
- `ToolExecutionResult`

这导致 orchestrator 与 tool-hub 只能先依赖 owned 目录中的本地契约。

## 建议变更
由 foundation 在冻结区新增共享 schema / package 定义，用于承载：
1. tool descriptor / registry schema
2. invocation request schema（含 trace 与 auth context）
3. invocation result schema（含 status / summary / citations）

## 影响范围
- `apps/orchestrator-service`
- `apps/tool-hub-service`
- 后续可能接入的 gateway / marketing / research 服务

## 兼容性说明
- 当前实现已经在 owned 目录内稳定运行
- foundation 可先按“新增 schema”方式推广，不需要破坏现有服务
- downstream 服务后续可逐步从本地契约迁移到冻结共享包

## 是否阻塞当前工作流
否。当前 workflow 已通过本地契约继续推进实现，但该缺口值得尽快收敛为共享标准。

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - 在 `packages/common-schemas` 中新增共享 `ToolDefinition`、`ToolExecutionContext`、`ToolInvocationRequest`、`ToolExecutionResult` 及当前 HTTP 路由别名 schema
  - 在 `packages/common-schemas/errors/error_codes.yaml` 中补充工具调用相关错误码
  - 在 `openapi/tool-hub-service.openapi.yaml` 与 `openapi/components.openapi.yaml` 中升级对应 OpenAPI 基线
  - 在 `packages/common-schemas` 与 `packages/common` 文档中同步当前 canonical path 与共享契约说明
