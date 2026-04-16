# 变更申请：补齐编排与 Tool Hub 的内部契约/路由冻结基线

## 背景
`supervisor-orchestrator` 已在 owned 目录内把基线能力推进到更接近主 spec 的内部调用链：
- `orchestrator-service`：新增内部 `POST /internal/v1/orchestrator/chat`
- `tool-hub-service`：新增内部 `POST /internal/v1/tools/call`
- `tool-hub-service`：新增 MCP 风格 `GET /tools/list`、`POST /tools/call`
- `business-tools`：新增统一执行入口 `POST /internal/v1/execute/{tool_name}`

这些实现均位于 owned 目录内，未直接修改冻结区。

## 当前缺口
冻结区当前缺少以下基线契约，导致静态 OpenAPI / shared schema 无法完整覆盖现有实现：
1. `orchestrator-service` 内部 chat 请求/响应 schema
2. `tool-hub-service` 内部 tool-call 请求/响应 schema
3. MCP `tools/list` / `tools/call` 路由基线
4. `business-tools` 统一执行接口 schema（operator / subject / payload / result）
5. richer `AgentDescriptor` 字段（display_name、allowed_tools、supported_scenes、fallback_agent、max_tool_calls）

## 建议变更
由 foundation 在冻结区补齐：
- `openapi/orchestrator-service.openapi.yaml` 的内部 chat 路由基线
- `openapi/tool-hub-service.openapi.yaml` 的内部 tool-call 与 MCP 路由基线
- `packages/common-schemas` 中新增：
  - `internal/orchestrator/internal-chat-request.schema.json`
  - `internal/orchestrator/internal-chat-response.schema.json`
  - `internal/tool-hub/tool-call-request.schema.json`
  - `internal/tool-hub/tool-call-response.schema.json`
  - `internal/business-tools/execute-request.schema.json`
  - `internal/business-tools/execute-response.schema.json`
- 如 foundation 认可，也可同步扩展 `agent-descriptor.schema.json`

## 兼容性说明
- 本次 owned 实现采用新增路由/新增字段方式，不破坏现有 `/api/orchestrator/v1/*` 与 `/api/tool-hub/v1/*` 基线
- foundation 可先以 additive 方式补齐冻结契约，再由各服务逐步切换到共享 schema

## 影响范围
- `apps/orchestrator-service`
- `apps/tool-hub-service`
- `apps/business-tools`
- 后续 `gateway-service` / admin 侧 / 集成测试 stub

## 是否阻塞当前工作流
否。
当前代码、测试与本地契约已可继续推进，但冻结区需要尽快追平实现现状，避免后续跨 supervisor 集成时出现契约漂移。

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - 在 `packages/common-schemas` 中补齐 orchestrator internal chat、tool-hub direct tool-call/MCP、business-tools execute bridge 的共享 schema
  - 在 `openapi/orchestrator-service.openapi.yaml`、`openapi/tool-hub-service.openapi.yaml`、`openapi/business-tools-service.openapi.yaml` 与 `openapi/components.openapi.yaml` 中补齐对应冻结基线
  - 在共享文档与 foundation 状态工件中同步当前 canonical/legacy/internal 路由说明
