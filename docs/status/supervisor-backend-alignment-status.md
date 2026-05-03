# Supervisor Backend Alignment Status

- 日期：2026-04-18
- 更新时间：2026-04-21T12:33:00+00:00
- 负责人：SmartCloud-X 开发文档对齐总收口执行
- 当前阶段：以真实代码现状、最新测试证据与运行证据复核 backend alignment；不再把目标式文档或 placeholder 合同直接视为实现证明

## 判定口径

本文件统一使用以下状态语义：

- **已实现**：有真实代码路径、测试路径或运行证据。
- **占位合同**：OpenAPI / shared schema / 目标式 prompt 中存在，但当前代码或测试未证明。
- **外部环境阻塞**：需要真实凭证、真实服务、compose/live smoke 才能关闭的项。
- **目标态未达成**：当前已有部分代码或局部能力，但尚未达到开发文档目标架构。

## 总体结论

- 当前仓库不是空骨架；多项服务内能力已真实实现。
- 但 backend alignment 不能再按“开发文档写了什么”判断，而必须按代码现状和最新测试证据判断。
- 尤其是 orchestrator / rag / gateway 的关键用户链路，当前应以已落地测试为准，而不是以 placeholder OpenAPI 或理想架构叙述为准。

## 关键对证更新

### 1. gateway 现状
- 状态：**已实现（服务内） + 外部环境阻塞（系统联调）**
- 代码路径：`apps/gateway-service/app/main.py`、`apps/gateway-service/app/api/routes/chat.py`、`apps/gateway-service/app/api/routes/health.py`
- 测试证据：`apps/gateway-service/tests/test_gateway_api.py`
  - `test_chat_stream_passthrough_preserves_event_stream_and_stores_citation`
  - `test_chat_completions_rejects_non_object_body_with_canonical_4001001`
  - `test_stream_logging_emits_lifecycle_events_without_payload_leak`
  - `test_gateway_missing_bearer_token_returns_canonical_401`
  - `test_upstream_error_passthrough_preserves_status_and_logs_classification`
- 运行证据：gateway acceptance probe 失败原因是 upstream 不可达，而不是 gateway 路由缺失。
- 判定：不能把“gateway 自身完成”误写成“系统整体交付完成”。

### 2. orchestrator 现状
- 状态：**已实现（真实 retrieval/citation 主链路） + 目标态未达成（仍非完整 LangGraph 编排）**
- 代码路径：
  - `apps/orchestrator-service/app/api/routes/orchestration.py`
  - `apps/orchestrator-service/app/services/agent_runtime.py`
  - `apps/orchestrator-service/app/services/streaming.py`
  - `apps/orchestrator-service/app/services/router.py`
- 测试证据：`apps/orchestrator-service/tests/test_api.py`
  - `test_internal_orchestrator_chat_uses_real_rag_citations_on_success`
  - `test_internal_orchestrator_chat_marks_degraded_retrieval_without_baseline_placeholder`
  - `test_internal_orchestrator_chat_returns_failed_when_rag_hard_failure_occurs`
  - `test_internal_orchestrator_chat_rejects_missing_user_context_for_retrieval`
  - `test_orchestrate_message_stream_emits_spec_like_events`
- 关键判定：
  - success：真实 retrieval citation 生效；
  - degraded：显式 degraded，citation 不伪造；
  - hard failure：failed 语义，不伪装成功；
  - missing user context：直接拒绝 retrieval；
  - stream：包含 `retrieval` 事件。

### 3. `baseline://router-retrieval` 的统一口径
- 状态：**占位来源，不能视为成功 citation**
- 说明：
  - 当前 backend alignment 文档必须明确：`baseline://router-retrieval` 不再是成功检索证据；
  - 若未来响应或 SSE 中再次出现并被当作成功 citation，应视为**回归风险**；
  - 该结论由 orchestrator 指定测试显式证明，尤其是 success/degraded/hard-failure 三条路径都断言不得再把它当成功引用。

### 4. rag 现状
- 状态：**已实现（服务内 retrieval owner 能力）**
- 代码路径：`apps/rag-service/app/api/routes/rag.py`、`apps/rag-service/app/services/retrieval.py`、`apps/rag-service/app/services/answer.py`
- 测试证据：`apps/rag-service/tests/test_retrieval.py`
  - `test_degraded_response_marks_backend_and_citation_contract`
  - `test_retrieve_route_degrades_on_protocol_errors`
  - `test_answer_route_degrades_on_upstream_timeout`
  - `test_answer_falls_back_when_no_citations`
- 判定：rag 已证明 degraded/no-citation/timeout/protocol-error 路径真实存在，且不会捏造 citation；系统 gap 不再是“rag 服务根本没有能力”，而是更高层链路收口与目标态差距。

### 5. knowledge 现状
- 状态：**已实现（摄入/搜索/worker baseline） + 目标态未达成（per-domain index 未完全落地）**
- 代码路径：`apps/knowledge-service/app/services/indexing_worker.py`、`apps/knowledge-service/app/services/search.py`
- 运行/测试证据：knowledge/rag 联合 pytest 与 compileall 已通过。
- 判定：单 collection/index baseline 仍是当前真实状态，不能因为开发文档目标态而改写为“域级索引治理已完成”。

## 对原 10 项 alignment 的重新分层

### 已实现
1. A2A 最小协议层：以 orchestrator 现有路由与 owner 测试为准
2. gateway canonical/error/SSE/logging/health 聚合：以 gateway 代码与测试为准
3. rag 内部检索、degraded、answer fallback：以 rag 代码与测试为准
4. knowledge 摄入/搜索 baseline：以 knowledge 代码与联合测试为准

### 外部环境阻塞
1. LangSmith live trace：缺真实 `LANGSMITH_API_KEY`
2. Dify final live shape：缺真实 Dify endpoint/key/dataset
3. compose/live smoke 未执行完的 Mongo/Celery 环境验证
4. gateway live acceptance：upstream 未启动/不可连通

### 目标态未达成
1. orchestrator 仍非完整 LangGraph 编排内核
2. knowledge per-domain collection/index 未完全落地
3. 五个重点服务 readiness 合同仍未全部统一到同一成熟度

### 占位合同
1. placeholder OpenAPI 与 shared schema 中的 draft/downstream-owned 字段
2. 任何没有代码和测试背书的“已完成”描述

## 当前机械度量（修正口径）

- 指标：`backend_alignment_unresolved_count`
- 新口径：只有当目标项达到“代码已实现 + 对应测试/运行证据已存在 + 非外部环境阻塞”时才关闭
- 说明：不能因为开发文档已有目标描述、或旧状态文档曾写 completed，就机械判定 resolved

## 风险与约束

1. **代码是唯一事实来源**：目标文档只用于判定目标态，不用于证明当前实现。
2. **禁止把 placeholder 合同当实现证明**：OpenAPI/contract 可领先代码，但不能替代代码。
3. **必须持续追踪回归风险**：`baseline://router-retrieval` 若再次进入成功 citation，应立即视为回归。
4. **外部环境阻塞单列**：避免把凭证/环境问题错误回写成服务内功能缺失，或反向把环境未打通误写为已交付。

## 最新对证引用清单

### gateway
- `apps/gateway-service/tests/test_gateway_api.py::test_chat_stream_passthrough_preserves_event_stream_and_stores_citation`
- `apps/gateway-service/tests/test_gateway_api.py::test_chat_completions_rejects_non_object_body_with_canonical_4001001`
- `apps/gateway-service/tests/test_gateway_api.py::test_stream_logging_emits_lifecycle_events_without_payload_leak`
- `apps/gateway-service/tests/test_gateway_api.py::test_gateway_missing_bearer_token_returns_canonical_401`
- `apps/gateway-service/tests/test_gateway_api.py::test_upstream_error_passthrough_preserves_status_and_logs_classification`

### orchestrator
- `apps/orchestrator-service/tests/test_api.py::test_internal_orchestrator_chat_uses_real_rag_citations_on_success`
- `apps/orchestrator-service/tests/test_api.py::test_internal_orchestrator_chat_marks_degraded_retrieval_without_baseline_placeholder`
- `apps/orchestrator-service/tests/test_api.py::test_internal_orchestrator_chat_returns_failed_when_rag_hard_failure_occurs`
- `apps/orchestrator-service/tests/test_api.py::test_internal_orchestrator_chat_rejects_missing_user_context_for_retrieval`
- `apps/orchestrator-service/tests/test_api.py::test_orchestrate_message_stream_emits_spec_like_events`

### rag
- `apps/rag-service/tests/test_retrieval.py::test_degraded_response_marks_backend_and_citation_contract`
- `apps/rag-service/tests/test_retrieval.py::test_retrieve_route_degrades_on_protocol_errors`
- `apps/rag-service/tests/test_retrieval.py::test_answer_route_degrades_on_upstream_timeout`
- `apps/rag-service/tests/test_retrieval.py::test_answer_falls_back_when_no_citations`

## 严格口径结论

- 当前阶段判断：**以代码现状和最新测试证据为准**。
- placeholder OpenAPI / 目标式文档：**不能当实现证明**。
- gateway/orchestrator/knowledge/rag：**已有真实代码基线，但成熟度不同，且仍有目标态差距**。
- `baseline://router-retrieval`：**占位来源，不得再视为成功 citation；再次出现属于回归风险**。
