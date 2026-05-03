# SmartCloud-X 架构盘点

- 更新时间：2026-04-18 14:52:22 +08:00
- 更新原因：基于 `SmartCloud/kaifawendang.md` 与 `SmartCloud-X` 真实代码做当前架构核对，避免仅依赖 AI 生成文档。
- 影响范围：`apps/*`、`packages/*`、`deploy/docker-compose/docker-compose.yml`

## 当前判断

1. 当前仓库已经不是“纯文档方案”，而是一个可运行的 monorepo 基线：
   - 后端服务：`auth-user-service`、`gateway-service`、`orchestrator-service`、`tool-hub-service`、`business-tools-service`、`knowledge-service`、`rag-service`、`marketing-service`、`research-service`
   - 前端：`web-user`、`web-admin`
   - 契约层：`packages/common-schemas`、`packages/frontend-sdk`

2. 代码真实架构与最初开发文档有明显差异：
   - `orchestrator-service` 目前仍是“规则路由 + 模板化回答”的 baseline，不是文档里描述的 LangGraph 主编排。
   - `knowledge-service` + `rag-service` 已经做出了可运行的知识检索链路，但整体是“本地/关系型存储 + 异步同步到 Qdrant/OpenSearch”的混合实现。
   - `tool-hub-service` / `business-tools-service` 已经拆分，但 `orchestrator-service` 仍保留本地 fallback，服务边界尚未完全收紧。

## 主要问题

### 1. Orchestrator 还是 baseline，不是真正的智能编排核心

- 证据：
  - `apps/orchestrator-service/app/services/router.py:34` 明确写了 `Keyword-based supervisor baseline router`
  - `apps/orchestrator-service/app/services/router.py:36` 写的是 `later LangGraph state machine`
  - `apps/orchestrator-service/app/services/router.py:158` 开始直接按关键词和 scene 决策主 Agent
  - `apps/orchestrator-service/app/services/agent_runtime.py:379` 的 reasoning summary 是固定模板
  - `apps/orchestrator-service/app/services/agent_runtime.py:383` 之后的 final answer 基本是大量 if/else 模板拼装

- 影响：
  - 现在更像“多业务规则引擎 + 工具编排器”，不是“多 Agent 智能编排平台”。
  - 如果继续堆业务，编排复杂度会直接压到 `router.py` / `agent_runtime.py`。

### 2. Chat 主链路里的 retrieval 目前偏“标记化”，还没真正接入 RAG 执行闭环

- 证据：
  - `apps/orchestrator-service/app/services/agent_runtime.py:79`、`189` 在 `requires_retrieval` 时直接补 `baseline://router-retrieval`
  - `apps/orchestrator-service/app/services/streaming.py:57` 只要路由标记需要检索就发 retrieval 事件
  - `apps/orchestrator-service/app/services/streaming.py:126` 没真实引用时也会用 `baseline://router-retrieval`
  - `apps/rag-service/app/services/knowledge_client.py:17` 到 `49` 说明真正检索是在 `rag-service -> knowledge-service`

- 影响：
  - `rag-service` 是真的，聊天里的 retrieval 展示却仍然是 baseline 占位风格。
  - 用户端如果把这个链路当“真实检索引用”，后面会出现可解释性和可信度问题。

### 3. 管理端访问路径不统一，存在绕过网关的边界问题

- 证据：
  - `apps/web-admin/src/lib/api.ts:5` 直接读 `VITE_KNOWLEDGE_SERVICE_BASE_URL`
  - `apps/web-admin/src/lib/api.ts:8` 直接读 `VITE_RAG_SERVICE_BASE_URL`
  - 但 `apps/gateway-service/app/api/routes/admin.py:39`、`45`、`51` 已经提供了带权限校验的 admin 代理路由

- 影响：
  - 前端和网关各走一套 admin 访问路径，权限、审计、错误格式、调用来源会逐渐漂移。
  - 后续如果要做统一鉴权、灰度、限流、审计，这个分叉会越来越难收口。

### 4. 数据与运行时回退策略太多，真实“权威数据源”不够清晰

- 证据：
  - `apps/knowledge-service/app/services/store.py:61` 开始使用本地 JSON store
  - `apps/knowledge-service/app/services/store.py:87` 之后再根据配置接 MySQL runtime backend
  - `apps/knowledge-service/app/services/indexing_worker.py:196` 之后再异步写 MinIO / MySQL / Qdrant / OpenSearch / Redis
  - `apps/orchestrator-service/app/core/config.py:302` 之后默认生成 degraded JSON fallback 文件
  - `apps/orchestrator-service/app/services/tool_hub_client.py:36`、`67`、`898` 表明 dev/test 允许本地 degraded fallback

- 影响：
  - 这套设计很适合开发期保活，但到了联调/预生产阶段会增加排障难度。
  - 出现数据不一致时，很难第一时间说清到底以 JSON、MySQL、Mongo、Redis、Qdrant、OpenSearch 中哪个为准。

### 5. Tool 领域边界还没彻底收紧，存在重复定义风险

- 证据：
  - `apps/orchestrator-service/app/services/tool_hub_client.py:67-69` 支持本地执行
  - `apps/orchestrator-service/app/services/router.py` 自己知道工具白名单和工具 payload 构造
  - `tool-hub-service` 和 `business-tools-service` 又各自维护工具元数据与执行协议

- 影响：
  - 现在是“服务化方向正确，但业务知识仍分散在 orchestrator / tool-hub / business-tools 三层”。
  - 再往前推进，最容易发生的是 tool contract 漂移和 payload 规则重复维护。

## 当前优先级建议

### P0：先统一“真实主链路”

1. 明确用户聊天主链路到底以谁为准：
   - 要么继续走 baseline，则文档和 UI 都不要再包装成“真实 RAG / LangGraph 已上线”
   - 要么把 `orchestrator -> rag-service -> tool-hub` 的真实闭环补齐，再对外说是多 Agent + RAG

2. 先把 admin 前端统一收口到 gateway：
   - `web-admin` 不再直连 `knowledge-service` / `rag-service`
   - 所有 admin 请求统一经过 `gateway-service`

### P1：给 Orchestrator 做一次“去伪基线化”

1. 保留当前 `RouteDecision / ToolPlan / SessionState` 数据结构
2. 把“关键词路由 + 模板回答”与“真实执行链路”拆开
3. 先补一个最小真实执行版本：
   - route 后真的调用 `rag-service`
   - citations 用真实检索结果
   - SSE retrieval 事件也从真实结果生成

### P2：收紧数据权威边界

建议尽快明确：

1. 会话权威源：
   - MySQL + Mongo 还是 fallback JSON
2. 知识库权威源：
   - `knowledge-store.json` 还是 MySQL runtime tables
3. 检索权威源：
   - 本地关键词基线、OpenSearch、Qdrant 三者怎样降级，谁是默认主路径

## 建议推进顺序

1. 先修 admin 调用边界
2. 再打通 orchestrator 的真实 retrieval
3. 再处理 tool fallback 收口
4. 最后再决定是否升级成真正 LangGraph 编排

## 补充说明

- 本次判断优先以真实代码为准，不以 `kaifawendang.md` 的目标式描述为准。
- 当前仓库的方向是对的，但阶段判断更接近“工业化基线正在成形”，还不是“最终架构已完全落地”。
