# Supervisor Orchestrator Status

- 更新时间：2026-04-21 12:33:00 UTC
- 当前阶段：以真实代码与最新测试证据复核 orchestrator 编排状态；会话/SSE/A2A/健康检查已实现，真实 retrieval/citation 主链路已有代码与指定测试证明，但更高阶“完整 LangGraph 编排核心”目标态仍未达成

## 判定口径

本文件只以当前仓库真实实现、真实测试函数、真实运行证据为准。

- **已实现**：代码路径 + 测试路径/函数名可直接证明。
- **占位合同**：OpenAPI、目标式开发文档、设计稿中的理想能力，若缺代码与测试，不计入已完成。
- **外部环境阻塞**：如 Mongo/LangSmith/Dify 等外部资源、上游服务、凭证未就绪；与 orchestrator 本身代码能力分开判定。
- **目标态未达成**：当前规则路由、会话与事件能力已存在，但仍不能把 orchestrator 描述成完整 LangGraph/多 Agent 智能编排平台。

## 总结结论

### 已实现
1. internal chat 编排入口、会话/消息/SSE 回放
2. `/healthz` 与 `/readyz`
3. A2A 最小协议层
4. 基于 rag-service 的真实 retrieval/citation 主链路
5. retrieval 的 success / degraded / hard failure / missing user context / spec-like stream 五类关键路径

### 占位合同 / 不能直接视为完成
1. “完整 LangGraph 状态机”或“成熟智能体编排平台”描述
2. 任何仅存在于目标式 prompt、架构文档、placeholder OpenAPI 的能力
3. 把 `baseline://router-retrieval` 视为成功 citation 来源的叙述 —— 这在当前代码和测试口径下属于**错误结论**

### 外部环境阻塞
1. LangSmith、部分 Mongo/环境级运行能力仍可能受外部环境影响
2. 这些阻塞不影响本文件对 orchestrator retrieval/citation 主链路代码状态的判定

### 目标态未达成
1. `apps/orchestrator-service/app/services/router.py` 仍是规则路由 baseline，而非 LangGraph 状态机
2. orchestrator 当前已打通真实 retrieval/citation，但仍不能上推为“完整最终编排内核已完成”

## 必须明确：`baseline://router-retrieval` 的当前语义

`baseline://router-retrieval` **不能再被视为成功 citation 来源**。

- 旧语义风险：它曾代表“看起来像检索来源”的占位引用。
- 当前正确口径：成功 citation 必须来自 rag-service 返回的真实 `sources[].uri` / citation 投影。
- 回归风险：如果未来响应或流式事件中再次把 `baseline://router-retrieval` 当作成功 citation 输出，应视为**严重回归**。

测试侧已把该风险写成显式断言：
- `apps/orchestrator-service/tests/test_api.py::test_internal_orchestrator_chat_uses_real_rag_citations_on_success`
- `apps/orchestrator-service/tests/test_api.py::test_internal_orchestrator_chat_marks_degraded_retrieval_without_baseline_placeholder`
- `apps/orchestrator-service/tests/test_api.py::test_internal_orchestrator_chat_returns_failed_when_rag_hard_failure_occurs`

这些测试都明确断言返回体中**不得再出现** `baseline://router-retrieval`。

## 代码+测试已证明的 orchestrator 结论

### 1. success 路径：真实 retrieval citation 生效
- 结论：**已实现**
- 代码路径：
  - `apps/orchestrator-service/app/api/routes/orchestration.py`
  - `apps/orchestrator-service/app/services/agent_runtime.py`
  - `apps/orchestrator-service/app/services/streaming.py`
- 测试路径：`apps/orchestrator-service/tests/test_api.py`
- 测试函数：`test_internal_orchestrator_chat_uses_real_rag_citations_on_success`
- 已证明行为：
  - internal chat 会调用 rag 检索；
  - 返回 `payload["citations"] == ["kb://billing/doc_001#chunk_003"]`；
  - `execution["retrieval_result"]["backend_used"] == "knowledge-service-search"`；
  - 明确断言 `baseline://router-retrieval` 不在成功结果中。

### 2. degraded 路径：明确 degraded，citation 不伪造
- 结论：**已实现**
- 代码路径：
  - `apps/orchestrator-service/app/services/agent_runtime.py`
  - `apps/orchestrator-service/app/services/streaming.py`
- 测试路径：`apps/orchestrator-service/tests/test_api.py`
- 测试函数：`test_internal_orchestrator_chat_marks_degraded_retrieval_without_baseline_placeholder`
- 已证明行为：
  - 检索链路降级时，`payload["status"]` 仍可为成功回答流程；
  - `execution["retrieval_result"]["degraded"] is True`；
  - `payload["citations"] == []`；
  - `risk_flags == ["retrieval_degraded"]`；
  - 明确断言没有 `baseline://router-retrieval` 伪造 citation。

### 3. hard failure：failed 语义，不伪装成功
- 结论：**已实现**
- 代码路径：`apps/orchestrator-service/app/services/agent_runtime.py`
- 测试路径：`apps/orchestrator-service/tests/test_api.py`
- 测试函数：`test_internal_orchestrator_chat_returns_failed_when_rag_hard_failure_occurs`
- 已证明行为：
  - rag-client 抛出 `RagClientUnavailableError` 时，整体返回 `payload["status"] == "failed"`；
  - `execution["status"] == "failed"`；
  - `execution["retrieval_result"] is None`；
  - `risk_flags == ["retrieval_failed"]`；
  - 最终答复为稍后重试提示，而不是伪装成成功引用。

### 4. missing user context：直接拒绝 retrieval
- 结论：**已实现**
- 代码路径：`apps/orchestrator-service/app/services/agent_runtime.py`
- 测试路径：`apps/orchestrator-service/tests/test_api.py`
- 测试函数：`test_internal_orchestrator_chat_rejects_missing_user_context_for_retrieval`
- 已证明行为：
  - 缺少 `user_id` 时不进入成功检索；
  - 返回 `payload["status"] == "failed"`；
  - `execution["risk_flags"] == ["missing_user_context"]`；
  - `payload["citations"] == []`。

### 5. spec-like stream：包含 `retrieval` 事件
- 结论：**已实现**
- 代码路径：`apps/orchestrator-service/app/services/streaming.py`
- 测试路径：`apps/orchestrator-service/tests/test_api.py`
- 测试函数：`test_orchestrate_message_stream_emits_spec_like_events`
- 已证明行为：
  - SSE content-type 为 `text/event-stream`；
  - 事件序列包含 `meta`、`reasoning`、`retrieval`、`tool_call`、`tool_result`、`citation`、`done`；
  - 说明 retrieval 已进入流式事件语义，而不是只停留在同步返回体。

## 其他已实现能力

### 会话管理与事件回放
- 结论：**已实现**
- 代码路径：
  - `apps/orchestrator-service/app/api/routes/orchestration.py`
  - `apps/orchestrator-service/app/services/conversation_store.py`
- 测试证据：`apps/orchestrator-service/tests/test_api.py` 中会话/消息/事件回放相关测试；当前文件保留的 stream replay 断言可证明该能力仍在。

### 健康检查 / readiness
- 结论：**已实现**
- 代码路径：`apps/orchestrator-service/app/api/routes/health.py`
- 测试证据：`apps/orchestrator-service/tests/test_api.py`
  - `test_healthz_reports_run_control_backend`
  - `test_readyz_reports_ready_when_runtime_is_healthy`
  - `test_readyz_reports_not_ready_when_tool_hub_dependency_is_unavailable`
  - `test_readyz_reports_not_ready_when_required_document_store_is_inactive`
  - `test_readyz_keeps_optional_document_store_failure_out_of_readiness_gate`
- 说明：orchestrator 已是五个重点服务中 readiness 合同较完整的一侧。

### A2A 最小协议层
- 结论：**已实现**
- 代码路径：`apps/orchestrator-service/app/api/routes/a2a.py`
- 说明：本文件不再用目标文档推断 A2A，而以现有路由和 owner 测试记录为准；当前可确认其最小协议层已存在。

## 与 rag-service 的对证关系

orchestrator 的真实 retrieval/citation 结论不仅有 orchestrator 自身测试，还可由 rag 侧检索降级与回答测试互证：

- `apps/rag-service/tests/test_retrieval.py::test_degraded_response_marks_backend_and_citation_contract`
  - 证明 degraded 检索响应会显式标记 `backend_used`，且 citation 可为空。
- `apps/rag-service/tests/test_retrieval.py::test_retrieve_route_degrades_on_protocol_errors`
  - 证明 `/api/rag/v1/retrieve` 遇到 knowledge protocol error 时走 degraded，而不是伪装成功来源。
- `apps/rag-service/tests/test_retrieval.py::test_answer_route_degrades_on_upstream_timeout`
  - 证明回答路径在上游超时时返回 degraded 与 coverageNotes。
- `apps/rag-service/tests/test_retrieval.py::test_answer_falls_back_when_no_citations`
  - 证明无 citation 时回答会走 fallback 文案，不会捏造引用。

这些测试与 orchestrator 的 success / degraded / failed 判定是一致的：**真实检索结果才产生 citation；降级或失败不会伪装成 baseline 成功。**

## 运行与验证证据

### 全量与定向测试
- `apps/orchestrator-service`: `PYTHONPATH=. uv run --with-requirements requirements.txt pytest tests -q` -> `192 passed`
- `apps/orchestrator-service`: `PYTHONPATH=. uv run --with-requirements requirements.txt pytest tests/test_tool_hub_client.py -q` -> `15 passed`
- compile: `python3 -m compileall app` -> passed

## Blockers / Risks

### 外部环境阻塞
- 当前无会阻止本文件结论成立的 owner-scope 硬阻塞。
- 但 LangSmith、Mongo 等环境/部署依赖仍可能影响更高层交付验证；这些不应回写成 retrieval/citation 主链路未实现。

### 目标态未达成
1. `apps/orchestrator-service/app/services/router.py` 仍是关键词/规则路由 baseline。
2. 多 agent durable runtime boundary 仍非独立调度体系。
3. 因此当前状态应描述为：**真实 retrieval/citation 主链路已实现并有测试证明；完整智能编排目标态未达成。**

## 严格口径结论
- internal chat + retrieval/citation 关键路径：**已实现并有代码+测试证明**
- `baseline://router-retrieval`：**不得再视为成功 citation 来源；再次出现应视为回归风险**
- readiness / health：**已实现**
- A2A 最小协议层：**已实现**
- 完整 LangGraph/目标式编排平台：**未实现，属于目标态未达成**
- 当前阶段判断依据：**代码现状 + 最新测试证据**，**不把目标式文档或 placeholder OpenAPI 当作实现证明**
