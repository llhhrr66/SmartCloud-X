# Supervisor Orchestrator/Tooling 开发需求确认与跟踪

## 1. 范围
- 负责文档：
  - `/home/ljr/SmartCloud-X/project_document/supervisor-master-instructions-2026-04-21.md`
  - `/home/ljr/SmartCloud-X/project_document/supervisor-prompt-orchestrator-tooling-2026-04-21.md`
  - `/home/ljr/SmartCloud-X/project_document/supervisor-prompt-orchestrator-tooling-reaudit-2026-04-21.md`
  - `/home/ljr/SmartCloud-X/project_document/supervisor-prompt-orchestrator-tooling-loopfix-2026-04-21.md`
  - `/home/ljr/开发文档拆分版-20260420-194821/00-开发文档总索引.md`
  - `/home/ljr/开发文档拆分版-20260420-194821/02-系统架构与核心业务设计.md`
  - `/home/ljr/开发文档拆分版-20260420-194821/03-RAG编排与事务补偿设计.md`（仅编排/Saga/MCP/A2A/Orchestrator 相关）
  - `/home/ljr/开发文档拆分版-20260420-194821/06-可观测安全与目录规划.md`
  - `/home/ljr/开发文档拆分版-20260420-194821/16-Prompt与评测规范.md`
  - `/home/ljr/开发文档拆分版-20260420-194821/17-并行开发拆分规范.md`
  - `/home/ljr/开发文档拆分版-20260420-194821/19-执行顺序风险与停止边界.md`
- 负责代码：
  - `/home/ljr/SmartCloud-X/apps/orchestrator-service/`
  - `/home/ljr/SmartCloud-X/apps/tool-hub-service/`
  - `/home/ljr/SmartCloud-X/apps/business-tools/`
- 禁止修改：
  - `/home/ljr/SmartCloud-X/apps/gateway-service/`
  - `/home/ljr/SmartCloud-X/apps/auth-user-service/`
  - `/home/ljr/SmartCloud-X/apps/knowledge-service/`
  - `/home/ljr/SmartCloud-X/apps/rag-service/`
  - 其他非授权目录
- 当前目标：按 loopfix/重审口径，只依据真实代码、真实验证、真实 review 收敛 OT-001~OT-004；先纠正文档误判，再逐项给出完成/风险/残留结论。
- 更新时间：2026-04-21 01:22 UTC

## 2. 执行准则
- 以瞎猜接口为耻，以认真查询为荣。
- 以创造接口为耻，以复用现有为荣。
- 以跳过验证为耻，以主动测试为荣。
- 以破坏架构为耻，以遵循规范为荣。
- 以假装理解为耻，以诚实无知为荣。
- 以盲目修改为耻，以谨慎重构为荣。
- completed 只能由真实代码 + 我亲自运行的真实验证 + review 结论共同支撑。
- 跨边界缺口只能记为 `cross_boundary`，不得直接改未授权目录。
- 上轮问题已纠正：不是缺 pytest 环境，而是误用解释器导致误判阻塞；本轮统一使用项目内 `.venv` 命令验证。

## 3. 差异总览
- pending: 0
- in_progress: 0
- review_required: 1
- testing: 0
- completed: 3
- blocked: 0
- cross_boundary: 0

## 4. 开发/审阅/测试跟踪表
| ID | 文档来源 | 要求摘要 | 当前现状 | 差异/风险 | 处理方案 | 涉及文件 | 测试要求 | Review要求 | 验证结果 | 文档已对齐 | 是否越界 | 残留风险 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| OT-001 | 02/03/17/19 | orchestrator 需具备路由、handoff、checkpoint、状态流转、失败停止边界、Saga rollback、SSE 与会话连续性 | `app/api/routes/orchestration.py` 暴露 chat/session/SSE/rollback/cancel/continue 路由；`app/services/agent_runtime.py` 实现多 agent handoff、同轮 tool hydration、session_context patch 复用、超时停止；`app/services/run_control.py` 实现 run lease/cancel/strict backend；README 与接口口径基本一致 | 文档级能力大体落地，但“完整可运行降级版本”仍依赖外部 RAG/gateway/tool-hub/biz tools 联调；本边界内单测证明了编排基线，不等于全项目最终停止边界已满足 | 维持 orchestrator 代码不改；将旧 blocker 纠正为真实 `.venv` 验证，明确当前结论只代表本边界基线完成，不夸大为全链路项目完成 | `apps/orchestrator-service/README.md`; `apps/orchestrator-service/app/api/routes/orchestration.py`; `apps/orchestrator-service/app/services/agent_runtime.py`; `apps/orchestrator-service/app/services/run_control.py`; `apps/orchestrator-service/app/core/config.py`; `apps/orchestrator-service/tests/test_api.py`; `apps/orchestrator-service/tests/test_runtime.py`; `apps/orchestrator-service/tests/test_mongo_runtime.py` | `PYTHONPATH="/home/ljr/SmartCloud-X/apps/orchestrator-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" /home/ljr/SmartCloud-X/.venv/bin/pytest /home/ljr/SmartCloud-X/apps/orchestrator-service/tests -q`; `/home/ljr/SmartCloud-X/.venv/bin/python -m compileall /home/ljr/SmartCloud-X/apps/orchestrator-service` | 复核是否真有 cancel/continue/rollback/SSE/handoff/run-control 代码与测试支撑，而非 README 口径 | 2026-04-21 实跑：`194 passed in 67.34s`；compileall 通过；代码证据覆盖 chat/session、SSE replay、rollback、handoff、run control、Mongo execution document scoping | 是 | 否 | 仍缺跨服务 dev/staging 联调证据；项目级“全部服务可运行”不在本 worker 单边界内闭合 | completed |
| OT-002 | 03/06/17/19 | tool-hub 需承担 MCP/tool gateway：注册、参数校验、权限校验、调用转发、结果统一封装、audit、idempotency、preflight、补偿、trace/metrics | `app/api/routes/tools.py` 提供 public/internal/MCP list/describe/call/preflight/invoke/compensation；`app/services/dispatcher.py` 校验 operation/payload/auth；`app/services/audit_store.py` 记录 MySQL/spool audit；`app/services/idempotency.py` 提供 replay/conflict；`app/core/observability.py` 提供 metrics/tracing | 代码与测试已证明注册、校验、转发、audit、idempotency、metrics 基线；但补偿排序仍是单级，README 已注明 known limitation，不能夸大成图级补偿引擎 | 纠正文档误判并确认本项按本边界基线完成；保留 README 已知限制，不再追加越界改动 | `apps/tool-hub-service/README.md`; `apps/tool-hub-service/app/api/routes/tools.py`; `apps/tool-hub-service/app/services/dispatcher.py`; `apps/tool-hub-service/app/services/idempotency.py`; `apps/tool-hub-service/app/services/audit_store.py`; `apps/tool-hub-service/app/core/observability.py`; `apps/tool-hub-service/app/core/config.py`; `apps/tool-hub-service/tests/test_api.py`; `apps/tool-hub-service/tests/test_observability_and_idempotency.py` | `PYTHONPATH="/home/ljr/SmartCloud-X/apps/tool-hub-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" /home/ljr/SmartCloud-X/.venv/bin/pytest /home/ljr/SmartCloud-X/apps/tool-hub-service/tests -q`; `/home/ljr/SmartCloud-X/.venv/bin/python -m compileall /home/ljr/SmartCloud-X/apps/tool-hub-service` | 检查 dispatcher/audit/idempotency/observability 是否被真实测试覆盖，并核对 README 对限制的表述是否诚实 | 2026-04-21 实跑：`106 passed in 13.73s`；compileall 通过；测试覆盖 public/internal tool call、discovery unavailable 503、metrics、idempotency replay/conflict、readiness、多工具执行 | 是 | 否 | 单级 compensation 仍是已知限制，但 README 已如实披露，未违反当前基线口径 | completed |
| OT-003 | 03/06/17/19 | business-tools 需实现业务工具执行、缓存、幂等、补偿、错误传播、session context patch，并与 tool-hub/orchestrator 契约一致 | `src/business_tools/catalog.py` 实现 invalid-payload/auth/confirmation/query-cache/idempotency/session_context_patch/compensation；`src/business_tools_service/api/routes/tools.py` 提供 provider-backed execute/preflight/descriptor/compensation；README 与测试覆盖 billing/order/ticket/icp/marketing/research/product/support 工具 | 代码与测试已证明工具目录、执行、缓存、幂等、补偿、session context patch、内部路由与契约对齐；但仍是 starter/baseline 数据，不代表真实后端业务系统已接入 | 维持代码不改；在状态文档中把完成口径限定为本边界 starter baseline 完成，不夸大为真实业务系统集成完成 | `apps/business-tools/README.md`; `apps/business-tools/src/business_tools/catalog.py`; `apps/business-tools/src/business_tools/query_cache.py`; `apps/business-tools/src/business_tools/idempotency.py`; `apps/business-tools/src/business_tools/compensations.py`; `apps/business-tools/src/business_tools_service/api/routes/tools.py`; `apps/business-tools/tests/test_service_app.py`; `apps/business-tools/tests/test_catalog.py` | `PYTHONPATH="/home/ljr/SmartCloud-X/apps/business-tools/src:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" /home/ljr/SmartCloud-X/.venv/bin/pytest /home/ljr/SmartCloud-X/apps/business-tools/tests -q`; `/home/ljr/SmartCloud-X/.venv/bin/python -m compileall /home/ljr/SmartCloud-X/apps/business-tools` | 检查执行/缓存/幂等/补偿/session_context patch 是否真的由 catalog/service/tests 支撑 | 2026-04-21 实跑：`85 passed in 1.60s`；compileall 通过；测试覆盖 catalog 元数据、auth-required、payload 校验、session_context_bindings、internal execute/preflight/compensation 等 | 是 | 否 | 当前为 provider-backed baseline/starter 数据，不是对接真实外部账单/工单系统的最终版本 | completed |
| OT-004 | 16/17/19 | prompt/agent 配置、版本化 prompt 目录、变量白名单、评测约束、README/实现/测试一致性需在本边界内对齐 | `apps/orchestrator-service/app/prompts/agents/*` 目录含 `system.v1.0.md`、`fewshot.v1.0.json`、`variables.v1.0.yaml`、`manifest.v1.0.yaml`、`eval_tags.yaml`；`app/core/config.py` 明确只允许注入开发文档要求的白名单变量；README 声称 prompt/version/eval 规范已对齐 | 版本文件和变量白名单代码存在，但本边界内未见 `tests/evals/**` 回归数据集与执行产物；按 16 章要求，Prompt 发布应绑定 smoke/core/full/full run 证据与 run_id。当前代码/测试无法证明评测门禁真实闭环 | 不越界补造全局评测资产；将 OT-004 明确降级为 `review_required`，把缺口记为 residual risk，等待评测/发布门禁侧补齐后再闭环 | `apps/orchestrator-service/app/prompts/**`; `apps/orchestrator-service/app/core/config.py`; `apps/orchestrator-service/README.md`; `apps/orchestrator-service/tests/test_config.py` | `PYTHONPATH="/home/ljr/SmartCloud-X/apps/orchestrator-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" /home/ljr/SmartCloud-X/.venv/bin/pytest /home/ljr/SmartCloud-X/apps/orchestrator-service/tests -q`; `/home/ljr/SmartCloud-X/.venv/bin/python -m compileall /home/ljr/SmartCloud-X/apps/orchestrator-service` | 检查 prompt 目录、manifest/variables、config 白名单是否与文档一致；同时核对是否真有评测门禁证据支撑“可发布”口径 | 目录与配置代码已审读；orchestrator 测试全集 `194 passed`、compileall 通过，可证明目录/配置解析基线；但未在本边界内找到并实跑 16 章要求的 smoke/core/full 评测数据集与发布 run_id 绑定证据 | 否 | 否 | Prompt 目录/变量白名单已落地，但评测运行、发布门禁、人工复核档案证据不足；不能按严格口径标记 completed | review_required |

## 5. 风险分级
- P0 风险：当前本边界未发现已由代码/测试证实的 P0 安全、越权、伪引用问题。
- P1 风险：OT-004 仍缺 Prompt 评测 run_id、数据集分层执行与发布门禁证据；若直接按 README 口径宣称“可发布”，会违反 16 章并可能把 Prompt 回归退化带到上线流程。
- P2 风险：OT-001/OT-002/OT-003 虽已完成本边界单测和 compileall，但仍主要是 baseline/starter 实现；缺少本 worker 边界内可独立提供的跨服务 dev/staging 联调记录，项目级停止边界尚未闭合。
- P3 风险：README 对能力点罗列较多，后续若继续扩展而不同步状态文档，容易再次出现“README 口径 > 已验证证据”的管理偏差。

## 6. 本轮结论
- 本轮完成：
  - 已完整重读任务文档、拆分开发文档、边界 README/核心代码/关键测试。
  - 已先重写跟踪文档并纠正“缺 pytest 环境”的误判，明确上轮问题是误用解释器导致误判阻塞。
  - 已使用项目内 `.venv` 实跑三套测试并通过：orchestrator `194 passed`、tool-hub `106 passed`、business-tools `85 passed`。
  - 已重新判定 OT-001~OT-004：OT-001/002/003 为 completed，OT-004 为 review_required。
- 本轮新增风险：OT-004 的 Prompt 评测/发布门禁证据仍不足，不能按严格口径宣称完成。
- 未完成项：OT-004。
- 跨边界项：无。
- 下一步：若继续本边界工作，下一轮先补查/补齐 prompt eval 数据集、run_id 绑定、人工复核档案是否已在授权目录内存在；若仍不存在，应保持 OT-004 为 review_required，不得夸大完成。
