# Supervisor Knowledge RAG Status

- 更新时间：2026-04-24T12:45:00+00:00
- owned scope：`apps/knowledge-service/`、`apps/rag-service/`、`docs/status/supervisor-knowledge-rag-status.md`
- 当前阶段：以真实代码、真实测试与编译/pytest 证据复核 knowledge/rag；服务内能力已实现较多，且当前仓库已具备 Round 9 gateway acceptance 与 Round 11 strict release gate 通过证据，因此文档口径不再写成 strict-gate blocked。同时必须明确：当前 running knowledge-service 的 SiliconFlow `BAAI/bge-m3` live 切换未被独立复核证实，不能写成已完成 live 切换。

## 判定口径

本文件只认当前代码与测试：

- **已实现**：代码路径 + 测试路径/函数名 + 运行证据可直接证明。
- **占位合同**：OpenAPI placeholder、shared schema 预留、目标式 prompt 描述，不等于已实现。
- **外部环境阻塞**：真实上游/凭证/服务不可用时的 degraded 或 blocked-external。
- **目标态未达成**：当前 baseline 可运行，但还未达到开发文档中的最终架构目标。
- **发布门禁口径**：knowledge/rag 服务内测试通过，不等于 `run_full_stack_validation.sh` 或 `release_readiness.py --strict` 已通过。

## 总结结论

### 已实现
1. knowledge-service 的摄入、搜索、embedding provider 抽象、文本处理增强、质量指标
2. rag-service 的 rewrite / retrieve / context / answer / diagnose / cache / admin diagnostics
3. rag degraded 路径的明确标记、fallback answer、citation 为空时不伪造引用
4. knowledge/rag 相关编译与 pytest 运行证据
5. `knowledge-service` 代码已具备 OpenAI-compatible embedding provider 接入基础

### 占位合同 / 不能直接视为完成
1. placeholder OpenAPI 中 owner-defined/downstream-owned 的 DTO 细节
2. “最终按域完全治理的知识索引架构”若未有当前代码证明，不可视为完成
3. 系统级“聊天主链路最终交付”不能仅由 rag/knowledge 自身服务内路由推出
4. 代码具备 OpenAI-compatible embedding 接入基础，不等于 running live 服务已经切换到 SiliconFlow `BAAI/bge-m3`

### 外部环境阻塞
1. 真实 knowledge 上游不可达、协议错误、超时，会触发 rag degraded 路径
2. Dify、外部 embedding provider、真实索引后端等能力若需外部配置，需单独标记，不可误写为代码未实现
3. 若 gateway acceptance 或 full-stack validation 需要 knowledge/rag live ready，而环境中 connectors 未完全就绪，则系统级验收仍会 blocked
4. 当前 SiliconFlow live 切换复核显示运行中的 knowledge-service 仍是 `hash-baseline`；这属于外部运行配置/切换未完成，而不是代码路径不存在

### 目标态未达成
1. Qdrant collection 与 OpenSearch index 仍未按 domain 完整拆分
2. 当前仍保留单 `knowledge_chunks` baseline / mixed baseline 现实
3. 因此知识治理能力尚未达到文档目标态

## Knowledge 侧状态

### embedding / text processing / ingestion / search
- 结论：**已实现**
- 代码路径：
  - `apps/knowledge-service/app/services/embeddings.py`
  - `apps/knowledge-service/app/services/text_processing.py`
  - `apps/knowledge-service/app/services/ingestion.py`
  - `apps/knowledge-service/app/services/search.py`
  - `apps/knowledge-service/app/api/routes/knowledge.py`
- 测试路径：`apps/knowledge-service/tests/test_ingestion.py`
- 运行证据：
  - `python -m compileall apps/knowledge-service/app` 通过
  - 联合测试命令 `uv run ... pytest apps/knowledge-service/tests apps/rag-service/tests -q` -> `44 passed in 4.69s`

### OpenAI-compatible embedding provider 基础
- 结论：**代码已实现，live SiliconFlow 切换未证实**
- 代码路径：
  - `apps/knowledge-service/app/services/embeddings.py`
  - `apps/knowledge-service/app/api/routes/knowledge.py`
  - `apps/knowledge-service/app/core/config.py`
- 代码事实：
  - `build_embedding_provider(settings)` 在 `SMARTCLOUD_EMBEDDING_PROVIDER=openai-compatible` 时返回 `FallbackEmbeddingProvider(OpenAICompatibleEmbeddingProvider(settings), fallback)`
  - `OpenAICompatibleEmbeddingProvider` 会校验 `SMARTCLOUD_EMBEDDING_API_URL`、`SMARTCLOUD_EMBEDDING_API_KEY`、`SMARTCLOUD_EMBEDDING_MODEL`
  - `/api/knowledge/v1/embedding:test` 会调用真实 provider，并在 fallback 场景返回 `provider`、`configuredProvider`、`fallbackActive`、`providerError` 等信息
- 补充复核证据：
  - `tasks/embedding-siliconflow-validation.md`：确认代码层面具备 OpenAI-compatible embedding 接入基础
  - `tasks/embedding-siliconflow-live-rerun.md`：确认当前 running knowledge-service live 环境并未真实切换到 SiliconFlow `BAAI/bge-m3`
- 当前 live 复核结论：
  - running 容器内 `SMARTCLOUD_EMBEDDING_PROVIDER/API_URL/API_KEY/MODEL` 均未注入
  - live `/api/knowledge/v1/embedding:test` 返回 `provider=HashEmbeddingProvider`、`configuredProvider=hash-baseline`、`dimensions=32`
  - 因此当前不得把 SiliconFlow `BAAI/bge-m3` 写成已落地的 live 事实

### per-domain index 治理
- 结论：**目标态未达成**
- 代码现状：当前状态文档保留 `knowledge_chunks` 单 collection/index 基线事实。
- 说明：这不是“缺文档”，而是当前代码层真实拓扑尚未完全达到开发文档目标。
- 判定：必须继续标记为未完成，不能因设计稿或目标 prompt 存在而改写成 completed。

## RAG 侧代码+测试已证明的结论

### 1. degraded 响应会标记 backend 与 citation 合同
- 结论：**已实现**
- 代码路径：`apps/rag-service/app/services/retrieval.py`
- 测试路径：`apps/rag-service/tests/test_retrieval.py`
- 测试函数：`test_degraded_response_marks_backend_and_citation_contract`
- 已证明行为：
  - `response.backend_used == "knowledge-service-unavailable"`
  - `response.citations == []`
  - `response.degraded is True`
  - `coverage_notes` 明确记录 degraded 原因

### 2. `/api/rag/v1/retrieve` 遇到协议错误时走 degraded，不伪装成功上游
- 结论：**已实现**
- 代码路径：`apps/rag-service/app/api/routes/rag.py`、`apps/rag-service/app/services/retrieval.py`
- 测试路径：`apps/rag-service/tests/test_retrieval.py`
- 测试函数：`test_retrieve_route_degrades_on_protocol_errors`
- 已证明行为：
  - knowledge-service 返回非法 payload 时，retrieve 仍返回 200 in-band 响应；
  - `payload["data"]["degraded"] is True`；
  - `coverageNotes` 写明 `invalid search payload`。

### 3. `/api/rag/v1/answer` 在上游超时时显式 degraded
- 结论：**已实现**
- 代码路径：`apps/rag-service/app/api/routes/rag.py`、`apps/rag-service/app/services/answer.py`
- 测试路径：`apps/rag-service/tests/test_retrieval.py`
- 测试函数：`test_answer_route_degrades_on_upstream_timeout`
- 已证明行为：
  - `payload["degraded"] is True`
  - answer 文案明确说明“没有检索到可引用知识”
  - `coverageNotes[0] == "knowledge-service unavailable: ReadTimeout"`

### 4. 无 citation 时回答走 fallback，而不是伪造引用
- 结论：**已实现**
- 代码路径：`apps/rag-service/app/services/answer.py`、`apps/rag-service/app/services/retrieval.py`
- 测试路径：`apps/rag-service/tests/test_retrieval.py`
- 测试函数：`test_answer_falls_back_when_no_citations`
- 已证明行为：
  - `answer.degraded is True`
  - 回答文本包含“没有检索到可引用知识”
  - 指标 `EMPTY_RETRIEVALS_TOTAL` 与 `DEGRADED_RETRIEVALS_TOTAL` 增长

## 与 orchestrator 主链路的对证关系

knowledge/rag 本体测试与 orchestrator 侧的 retrieval/citation 测试互相印证：

- rag 已证明 degraded / no-citation / timeout / protocol-error 都不会伪造 citation；
- orchestrator 已证明 success / degraded / hard failure / missing user context / spec-like stream 五条路径；
- 因此系统当前正确口径应为：**rag 具备真实 retrieval owner 能力；orchestrator 已按真实结果生成 citation 或显式失败/降级；不能再把占位来源当成成功证据。**

## 必须明确：`baseline://router-retrieval`

虽然该占位串主要出现在 orchestrator 风险语境中，但 knowledge/rag 状态文档也必须同步说明：

- `baseline://router-retrieval` **不是 rag-service 成功检索来源**；
- 真正有效的 citation 来源必须能回溯到 rag 返回的 `sources[]` / citation 投影；
- 如果后续联调再次把该占位串显示为成功 citation，应视为 orchestrator ↔ rag 主链路的**回归风险**。

## 运行与验证证据

### 编译与测试
```bash
PYTHONPATH="/home/ljr/SmartCloud-X/apps/knowledge-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" /home/ljr/SmartCloud-X/.venv/bin/python -m compileall apps/knowledge-service/app
```
- 结果：通过

```bash
PYTHONPATH="/home/ljr/SmartCloud-X/apps/rag-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" /home/ljr/SmartCloud-X/.venv/bin/pytest /home/ljr/SmartCloud-X/apps/rag-service/tests/test_retrieval.py -q
```
- 结果：`31 passed in 2.19s`

```bash
uv run --with-requirements apps/rag-service/requirements.txt --with httpx --with pytest python -m pytest apps/knowledge-service/tests apps/rag-service/tests -q
```
- 结果：`44 passed in 4.69s`

### SiliconFlow 补充复核
```bash
curl -sS --max-time 15 'http://127.0.0.1:8031/api/knowledge/v1/embedding:test?text=SiliconFlow%20probe'
```
- 独立复核记录：`tasks/embedding-siliconflow-live-rerun.md`
- 当前 live 返回关键信息：
  - `provider=HashEmbeddingProvider`
  - `configuredProvider=hash-baseline`
  - `dimensions=32`
- 判定：**当前 running knowledge-service 未真实切换到 SiliconFlow `BAAI/bge-m3`**

## Release-gate mapping

- service-level compile/pytest evidence: **green**
- knowledge/rag live readiness across a full environment: **not proven here as globally green**
- `scripts/qa/run_full_stack_validation.sh`: **脚本定义不变，仍需按候选环境当次结果判定**
- `scripts/qa/release_readiness.py --strict`: **Round 11 已通过，当前仓库已有 strict gate 通过证据**
- SiliconFlow `BAAI/bge-m3` live cutover: **not proven / not completed in the current running live environment**

## Residual risks

### 外部环境阻塞
- 外部上游超时、协议错误、服务不可达仍会触发 degraded；这是代码显式支持的运行现实，不应误写成“未实现”。
- 外部 embedding provider 若未完成运行时变量注入，`knowledge-service` 会继续停留在 baseline provider；这不等于代码不支持外部 provider，只表示 live 切换没有完成。

### 目标态未达成
1. per-domain collection/index 仍未完全落地；
2. 规模化知识域治理仍未达到开发文档目标态；
3. readiness 合同在本文件当前范围内未单独证明为统一完成，不应越权写成 completed。

## 严格口径结论
- knowledge/rag 服务内能力：**已实现较多，且有编译与 pytest 证据**
- rag degraded / fallback / no-citation 语义：**已由指定测试证明**
- placeholder 合同是否等于完成：**否**
- OpenAI-compatible embedding 代码基础是否存在：**是**
- 当前 running live knowledge-service 是否已切换到 SiliconFlow `BAAI/bge-m3`：**否，独立复核未证实且当前证据显示未切换**
- per-domain index 目标：**未完成，属于目标态未达成**
- 仓库级 release-ready 证据：**是，当前已有 Round 9 gateway acceptance 与 Round 11 strict gate 通过证据；后续仍需以候选环境当次脚本输出为准**
- 当前阶段判断依据：**代码现状 + 最新测试证据 + 发布门禁脚本规则 + SiliconFlow 独立复核记录**，**不把目标式文档、placeholder OpenAPI、或未完成的 live provider 切换当作实现证明**
