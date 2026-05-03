# Knowledge/RAG Supervisor 开发需求确认与跟踪

## 1. 范围
- 负责文档：
  - `/home/ljr/开发文档拆分版-20260420-194821/03-RAG编排与事务补偿设计.md`
  - `/home/ljr/开发文档拆分版-20260420-194821/04-数据存储与检索设计.md`
  - `/home/ljr/开发文档拆分版-20260420-194821/10-服务边界测试与文档规范.md`
  - `/home/ljr/开发文档拆分版-20260420-194821/16-Prompt与评测规范.md`（仅检索/评测/回归相关要求）
  - `/home/ljr/开发文档拆分版-20260420-194821/19-执行顺序风险与停止边界.md`
- 负责代码：
  - `apps/knowledge-service/`
  - `apps/rag-service/`
  - 与本边界直接相关的 README / tests / 局部 observability 文档
- 禁止修改：
  - `apps/gateway-service/`
  - `apps/auth-user-service/`
  - `apps/orchestrator-service/`
  - `apps/tool-hub-service/`
  - `apps/business-tools/`
  - 未授权共享目录
- 当前目标：按严格重审口径，只依据真实代码与本轮真实验证结果，重写并收敛 knowledge/rag 边界结论；证据不足的旧 completed 一律降级。
- 更新时间：2026-04-21 UTC

## 2. 执行准则
- 以瞎猜接口为耻，以认真查询为荣。
- 以创造接口为耻，以复用现有为荣。
- 以跳过验证为耻，以主动测试为荣。
- 以破坏架构为耻，以遵循规范为荣。
- 以假装理解为耻，以诚实无知为荣。
- 以盲目修改为耻，以谨慎重构为荣。

## 3. 差异总览
- pending: 0
- in_progress: 0
- review_required: 2
- testing: 0
- completed: 2
- blocked: 0
- cross_boundary: 2

## 4. 开发/审阅/测试跟踪表
| ID | 文档来源 | 要求摘要 | 当前现状 | 差异/风险 | 处理方案 | 涉及文件 | 测试要求 | Review要求 | 验证结果 | 文档已对齐 | 是否越界 | 残留风险 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| KR-001 | 03/19/22 | RAG 返回结构化引用，编排层不得伪造引用；返回口径要能说明 backend_used / score | 真实代码证据存在：`app/models/rag.py` 定义 `RetrievalCitation(citationId/backendUsed/score)`；`app/services/retrieval.py` 在 `build_response()` 中生成结构化 citation，`/answer` 复用 retrieval.citations 与 context；`app/api/routes/rag.py` 的 `/retrieve` `/diagnose` `/answer` 都回传 retrieval 结果 | 旧结论把“系统闭环”说得过满；本边界只能证明 rag-service 已产出结构化引用，不能证明 orchestrator 一定正确消费 | 维持本边界 completed，并把系统级消费问题单独列为 cross_boundary | `apps/rag-service/app/models/rag.py`, `apps/rag-service/app/services/retrieval.py`, `apps/rag-service/app/services/answer.py`, `apps/rag-service/app/api/routes/rag.py`, `apps/rag-service/tests/test_retrieval.py`, `apps/rag-service/README.md` | rag-service targeted tests + compileall | 核对 citation 字段是否真实由代码构造、answer 是否只复用 retrieval 输出而非自造引用 | `PYTHONPATH=... /home/ljr/SmartCloud-X/.venv/bin/pytest apps/rag-service/tests/test_retrieval.py -q` => `31 passed in 1.94s`; `/home/ljr/SmartCloud-X/.venv/bin/python -m compileall apps/rag-service/app` => 通过 | 是 | 否 | orchestrator 是否严格消费这些字段仍未知 | completed |
| KR-002 | 16/20.20 | 检索/Prompt 回归需要 smoke/core/full 数据集与场景 README；must_cite 样本缺引用必须失败 | 真实代码/资产仅证明最小 smoke 基线：`tests/evals/datasets/README.md`、`tests/evals/datasets/smoke/retrieval-smoke.jsonl`、`tests/evals/test_retrieval_eval_smoke.py`；其中测试明确断言当前 failures 仅为 `retrieval_smoke_001: must_cite case returned no citations` | 旧结论把“已完成边界内最小回归基线”标成 completed，但按重审口径，这更像“已建立 smoke 骨架，未满足文档要求的 core/full 分层与准入” | 降级为 review_required；保留 smoke 基线事实，但明确不能宣称文档级回归资产完成 | `apps/rag-service/tests/evals/datasets/README.md`, `apps/rag-service/tests/evals/datasets/smoke/retrieval-smoke.jsonl`, `apps/rag-service/tests/evals/test_retrieval_eval_smoke.py` | targeted eval test + compileall | 核对测试是否真正证明 must_cite 规则，以及是否达到了文档要求的 smoke/core/full 三档 | `PYTHONPATH=... /home/ljr/SmartCloud-X/.venv/bin/pytest apps/rag-service/tests/evals/test_retrieval_eval_smoke.py -q` => `1 passed in 0.63s`；但测试本身固定断言存在 1 个失败样本，因此只能证明“失败会被检测”，不能证明评测通过；compileall 通过 | 否 | 否 | 缺 core/full 数据集、缺 run_id/归档/门禁实现，距离文档要求仍远 | review_required |
| KR-003 | 04/10/22 | 知识库链路要覆盖 upload/clean/chunk/embed/index/snapshot；健康/metrics/runtime status 必须真实反映状态 | 真实代码证据存在：`app/services/ingestion.py` 实现 clean/metadata/chunk/embed/persist/checksum 去重/运行时同步；`app/services/text_processing.py` 支持 `fixed|paragraph` chunk；README 列出 upload/overview/search/snapshot/health/metrics/admin 路由与已知限制；`tests/test_ingestion.py` 为当前边界主验证文件 | 本轮未发现需要本边界再改的代码缺口；但 README 中 live backend/worker 能力仍依赖可选配置，不应外推为默认全后端已联通 | 维持本边界 completed，但口径仅限“service-local 实现+当前测试已通过” | `apps/knowledge-service/app/services/ingestion.py`, `apps/knowledge-service/app/services/text_processing.py`, `apps/knowledge-service/app/services/search.py`, `apps/knowledge-service/tests/test_ingestion.py`, `apps/knowledge-service/README.md` | knowledge-service targeted tests + compileall | 核对 upload/clean/chunk/embed/dedup/health/metrics/snapshot 相关能力是否由真实代码支撑，避免把可选后端说成默认已打通 | `PYTHONPATH=... /home/ljr/SmartCloud-X/.venv/bin/pytest apps/knowledge-service/tests/test_ingestion.py -q` => `12 passed in 3.57s`; `/home/ljr/SmartCloud-X/.venv/bin/python -m compileall apps/knowledge-service/app` => 通过 | 是 | 否 | 真实 Qdrant/OpenSearch/MinIO/MySQL 联调仍依赖外部环境，不在本轮验证内 | completed |
| KR-004 | 03/04/10 | 事务补偿、去重、回放与失败恢复需要完整落地 | 真实代码仅能证明 service-local 恢复骨架：README 明确“indexing outbox / retry path covers service-local ingestion recovery only; cross-service Saga compensation still requires orchestrator-side coordination”；`ingestion.py` 体现 checksum 去重与 runtime sync 调用，但本轮未看到完整跨服务 Saga 证据 | 旧结论把“已在 README 明确边界”当成 completed，不符合重审要求；文档要求的是能力落地，不是说明文字落地 | 降级为 review_required；保留“现有实现仅为 service-local outbox/去重/恢复骨架”的审计结论，不再宣称事务补偿完成 | `apps/knowledge-service/README.md`, `apps/knowledge-service/app/services/ingestion.py`, `docs/status/supervisor-knowledge-rag-dev-review.md` | 代码审阅 + targeted tests（现有 tests 只证明 service-local 行为） | 核对是否存在真实跨服务 Saga/补偿代码；若没有，必须降级 | 本轮现有验证仅证明 `tests/test_ingestion.py` 通过，不能证明跨服务事务补偿完成 | 否 | 否 | 跨服务补偿、失败回放编排仍未在本边界完整落地 | review_required |
| KR-X01 | 03/19/22 | 编排层不得伪造引用，需消费 RAG 结构化引用 | 当前仅能在 rag-service 看到结构化引用输出，无法在本边界证明 orchestrator 严格消费 `citationId/backendUsed/score` | 若 orchestrator 继续自行拼装，系统级引用一致性仍有风险 | 记录 cross_boundary，不越界修改 orchestrator | `apps/orchestrator-service/**`（只读） | N/A | N/A | 未执行（越界） | 否 | 是 | 需要 orchestrator 负责人处理 | cross_boundary |
| KR-X02 | 04/21/23 | 文档要求按域拆分 Qdrant/OpenSearch 集合/索引、冻结公共契约后再并行开发 | knowledge-service README 明确当前仍是单 collection/index；如要改，会触及 deploy/契约/调用方假设 | 该项不是 knowledge/rag 单边可安全完成的问题 | 记录 cross_boundary，保持现状透明 | `deploy/**`, 共享契约（只读） | N/A | N/A | 未执行（越界） | 否 | 是 | 需要总控/契约负责人统一处理 | cross_boundary |

## 5. 本轮结论
- 本轮完成：完成重审、重写跟踪文档，并用真实测试重新核验 KR-001、KR-003。
- 本轮新增风险：推翻旧结论 KR-002、KR-004 的 completed 口径，降级为 review_required。
- 未完成项：KR-002、KR-004。
- 跨边界项：KR-X01、KR-X02。
- 下一步：本边界当前只剩 `review_required` 与 `cross_boundary` 项；其中 KR-002、KR-004 在不越界前提下暂无更多真实代码可补，需晨会按严格口径审阅，不应宣称 fully ready。
