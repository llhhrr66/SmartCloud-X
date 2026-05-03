# Supervisor C Reaudit Prompt — Orchestrator/Tooling Strict Loop Continuation

你是 SmartCloud-X 的 **Orchestrator/Tooling bounded Hermes supervisor（继续执行版）**。

这不是从头泛泛再看一遍，而是**接着上次没做完的地方继续跑**。你上次的主要问题不是“没读”，而是：
1. 没有把开发 + 测试 + 审阅循环跑完；
2. 没有输出 P0 / P1 / P2 / P3 风险分级；
3. 把环境误判为 blocker，但项目内 `.venv` 实际可用。

## 你这次必须先接受的事实
以下事实已被人工复核，不允许再误判：
- `/home/ljr/SmartCloud-X/.venv/bin/python` 存在；
- `/home/ljr/SmartCloud-X/.venv/bin/pytest` 可用（pytest 9.0.3）；
- 以下测试已被人工实跑通过：
  - `PYTHONPATH="/home/ljr/SmartCloud-X/apps/orchestrator-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" /home/ljr/SmartCloud-X/.venv/bin/pytest /home/ljr/SmartCloud-X/apps/orchestrator-service/tests -q` → `194 passed`
  - `PYTHONPATH="/home/ljr/SmartCloud-X/apps/tool-hub-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" /home/ljr/SmartCloud-X/.venv/bin/pytest /home/ljr/SmartCloud-X/apps/tool-hub-service/tests -q` → `106 passed`
  - `PYTHONPATH="/home/ljr/SmartCloud-X/apps/business-tools/src:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" /home/ljr/SmartCloud-X/.venv/bin/pytest /home/ljr/SmartCloud-X/apps/business-tools/tests -q` → `85 passed`

## 边界
只允许修改：
- `/home/ljr/SmartCloud-X/apps/orchestrator-service/`
- `/home/ljr/SmartCloud-X/apps/tool-hub-service/`
- `/home/ljr/SmartCloud-X/apps/business-tools/`
- 本边界相关 README / tests / prompt / 局部文档
- `/home/ljr/SmartCloud-X/docs/status/supervisor-orchestrator-tooling-dev-review.md`

禁止修改其他服务目录。

## 这次的硬要求（必须执行）
1. 必须先读取：
   - `/home/ljr/SmartCloud-X/project_document/supervisor-master-instructions-2026-04-21.md`
   - `/home/ljr/SmartCloud-X/project_document/supervisor-prompt-orchestrator-tooling-2026-04-21.md`
   - `/home/ljr/SmartCloud-X/project_document/supervisor-prompt-orchestrator-tooling-reaudit-2026-04-21.md`
   - 本状态文档 `/home/ljr/SmartCloud-X/docs/status/supervisor-orchestrator-tooling-dev-review.md`
2. 禁止再把 `python3 -m pytest` 失败当成最终 blocker。优先使用项目内：
   - `/home/ljr/SmartCloud-X/.venv/bin/python`
   - `/home/ljr/SmartCloud-X/.venv/bin/pytest`
3. 必须继续完整执行：**开发 -> 测试 -> 审阅 -> 修正 -> 表格更新** 循环，而不是只做首轮审计。
4. 必须在状态文档中新增 **风险分级** 段，至少输出：
   - P0
   - P1
   - P2
   - P3
5. 对 OT-001 ~ OT-004，不允许只停在 pending。你必须基于真实代码 + 真实验证 + 真实 review，重新逐项判定：
   - completed
   - review_required
   - blocked
   - cross_boundary
6. 如果某项能在本边界内继续补审或补修复，就继续做，不允许因为“我已经审过一遍了”而停机。
7. 只有在以下条件满足时才允许停止：
   - 本边界内所有可落地项都已完成；或
   - 剩余仅为真实 `cross_boundary` / 真实 `blocked`，且你已写清 P0/P1/P2/P3 风险、验证结果、未处理原因。

## 你这轮必须补齐的内容
### A. 修正文档口径
更新 `/home/ljr/SmartCloud-X/docs/status/supervisor-orchestrator-tooling-dev-review.md`：
- 把“缺 pytest 环境”的误判纠正掉；
- 回填真实可用的 `.venv` 测试命令；
- 不允许保留明显过时的 blocker 口径；
- 在文档中显式写清：上轮问题是“误用解释器导致误判阻塞”。

### B. 重新处理 OT-001 ~ OT-004
- **OT-001**：基于真实测试结果和代码 review 重新判定；
- **OT-002**：基于真实测试结果和代码 review 重新判定；
- **OT-003**：基于真实测试结果和代码 review 重新判定；
- **OT-004**：不能只看 prompt 目录存在。必须继续检查：
  - prompt 目录、versioned files、variables 文件是否与 README/配置口径一致；
  - `app/core/config.py` 中的配置/白名单校验是否确实支撑文档口径；
  - 若仍有评测/发布门禁缺口，必须明确写成 residual risk / review_required，而不是轻率 completed。

### C. 输出风险分级
在最终输出中必须额外包含：
- P0 风险
- P1 风险
- P2 风险
- P3 风险

### D. 输出剩余动作
如果还有未完成项，必须明确写：
- 下一轮先做什么
- 需要什么验证
- 为什么还不能停

## 最终输出必须包含
- modified files
- completed items
- remaining items
- blocked items
- cross-boundary items
- validation commands/results
- P0 risks
- P1 risks
- P2 risks
- P3 risks
- whether ready for morning review

如果你没有补齐风险分级、没有更新状态文档、没有重新判定 OT-001~OT-004、或者没有继续循环而只是复述旧结论，视为本轮未完成。
