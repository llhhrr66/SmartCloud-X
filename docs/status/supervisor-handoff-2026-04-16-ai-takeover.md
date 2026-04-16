# Supervisor 工作交接文档（供其他 AI 接手）

> 2026-04-16 22:45 +0800 补充：后续 AI 已完成 knowledge/rag live shared-connector proof 收口。
>
> 已确认修复：
> - SmartCloud compose 的 MinIO host 端口与宿主机现有 rustfs 发生冲突，现已改为 `19000/19001` 默认映射。
> - `scripts/qa/qa_env.sh` 已同步使用新的 SmartCloud MinIO host 端口默认值。
> - `scripts/qa/project_smoke.py` 已补齐 `knowledge-service` 的 `SMARTCLOUD_MINIO_ENDPOINT` 注入。
> - `scripts/qa/project_smoke.py` 的 `knowledge-rag-admin` 场景已在 live mode 下显式执行 `python -m app.worker --once`，确保 reindex 事件真正落到 MinIO/MySQL/Qdrant/OpenSearch/Redis。
>
> 最新确认结果：
> - `SMARTCLOUD_QA_USE_LIVE_INFRA=1 ... project_smoke.py --scenario knowledge-rag-admin` 已通过。
> - `knowledge-rag-admin` 的 backendEvidence 已显示：`minio/mysql/qdrant/opensearch/redis-list-primary`。
>
> 因此，本文件中关于 `knowledge-rag live connector proof` 的 pending 描述已过时；后续接手优先级可从“打通 live connector”下调为“继续拔除 knowledge documents/chunks 本地 runtime JSON 依赖与完善 admin/object-storage 流程”。

---

- 生成时间：2026-04-16 21:45:26 +0800
- 目的：在当前 supervisor 全部停止前，给后续 AI 一份可直接接手的硬口径交接文档
- 当前操作决定：**停止 manager 轮询与当前运行中的 supervisors，后续改由其他 AI 接手**

---

## 1. 当前运行态

截至文档生成时，进程状态如下：

- manager 轮询：运行中
  - `/usr/bin/bash -lic while true; do bash /home/ljr/SmartCloud-X/scripts/supervisor_manager.sh; sleep 900; done`
- 当前仍在跑的 supervisor：
  - `scripts/run_supervisor_integration_qa.sh`
  - `scripts/run_supervisor_orchestrator.sh`
  - `scripts/run_supervisor_frontend_sdk.sh`
- 已不再常驻、按状态更像本轮已完成退出的 supervisor：
  - `foundation`
  - `knowledge-rag`
  - `web-user`
  - `auth-marketing-research`

说明：`manager pass complete` 只代表 manager 轮询正常，不代表所有 supervisor 都还在跑，也不代表所有迁移都已完全验收封口。

---

## 2. 总体老板口径

### 已成为主链路并拿到 live QA 证明

- `auth-user-service`
- `research-service`
- `marketing-service`
- `orchestrator-service`
- `tool-hub-service`
- `business-tools-service`

已被 QA 记录证明的真实后端包括：
- **MySQL**
- **Redis**

### 已迁移明显推进，但还没完全验收封口

- `knowledge-service`
- `rag-service`

原因不是这条线没动，而是**live connector proof 还没闭环**：
- MinIO host-side bucket bootstrap 报 `UnauthorizedAccess`
- Qdrant / OpenSearch 拉起与 bootstrap 太重，上一轮未等到可用
- `knowledge-service` 的 `documents/chunks` 仍主要保留在本地 runtime JSON

### 没在这轮里变成正式实链路的项

- MongoDB：没装/没接成当前主链路
- Celery：没装/没接成当前主链路
- Gateway-service：无实际服务目录/compose service
- LangSmith：只有 placeholder，不是完整接入

---

## 3. 各 supervisor 交接摘要

### A. supervisor-integration-qa

**最新状态口径**
- release readiness：`106/106`
- infra persistence：`26/26`
- recorded runtime evidence checklist：`6/6`
- repo-root Playwright：`9/9`

**已完成**
- `scripts/qa/run_smoke.sh` 已作为默认 targeted baseline
- `scripts/qa/project_smoke.py --scenario orchestrator-billing` 已能证明真实 `orchestrator -> tool-hub -> business-tools` timeout chain
- `SMARTCLOUD_QA_USE_LIVE_INFRA=1` 下，以下服务已拿到 live shared backend 证明：
  - auth-user-service
  - marketing-service
  - research-service
  - business-tools-service
  - tool-hub-service
  - orchestrator-service
- MySQL/Redis 落地证明已记录在 `logs/supervisor-integration-qa/state.json`

**仍未封口**
- `knowledge-rag-admin` 的 live shared-connector rerun 仍 pending

**阻塞点**
- MinIO bootstrap：`UnauthorizedAccess`
- Qdrant / OpenSearch：镜像拉取/启动/bootstrap 过重

**建议后续接手动作**
1. 修 MinIO 权限/桶 bootstrap。
2. 单独把 Qdrant / OpenSearch 拉起到可用，再跑 knowledge/rag live 验证。
3. 将 knowledge-rag live connector proof 写入 `logs/supervisor-integration-qa/state.json` 并刷新 status 文档。

关键文件：
- `docs/status/supervisor-integration-qa-status.md`
- `logs/supervisor-integration-qa/state.json`
- `scripts/qa/project_smoke.py`
- `scripts/qa/check_release_readiness.py`
- `scripts/qa/infra_persistence_matrix.py`

---

### B. supervisor-orchestrator

**最新状态口径**
- phase: `completed-recovery-authority-hardening`
- owned scope：
  - `apps/orchestrator-service`
  - `apps/tool-hub-service`
  - `apps/business-tools`

**本轮已完成**
- 启动恢复时更偏向 **MySQL/Redis 权威状态**，不再无脑拿本地 degraded spool 覆盖后端真值
- `tool-hub-service` audit recovery 不再让旧 degraded 文件覆盖 MySQL 新行
- `business-tools` 的 Redis idempotency / query-cache 恢复逻辑已改为 Redis 优先权威
- 补了 stale-spool restart regression coverage

**验证结果**
- orchestrator tests：`147 passed`
- tool-hub tests：`78 passed`
- business-tools tests：`79 passed`
- compileall：通过

**当前剩余风险**
- 本地/开发/测试仍允许 degraded connect-failure fallback
- 多写者冲突场景仍需人工判断，未做自动语义 merge
- MySQL/Redis 可用性、命名空间清理、degraded spool 运维策略仍在 owner 外部

**建议后续接手动作**
1. 若要继续收口，把 fallback 监控面和清理策略落到 runbook。
2. 如果要进一步强硬化，可继续限制 local/dev/test 中 fallback 的触发边界。
3. 接手 AI 重点看 `/healthz` transport metadata 与 `degraded-http-connect-fallback` audit 标签。

关键文件：
- `docs/status/supervisor-orchestrator-status.md`
- `logs/supervisor-orchestrator/state.json`
- `apps/orchestrator-service/app/...`
- `apps/tool-hub-service/app/...`
- `apps/business-tools/src/...`

---

### C. supervisor-frontend-sdk

**最新状态口径**
- phase: `shared-request-id-fidelity-self-reviewed`
- owned scope：`packages/frontend-sdk/`

**本轮已完成**
- `envelope.ts` / `http.ts` / `session.ts` 已保证：当后端 envelope 缺失 `request_id` 时，前端仍保留 caller-generated request id
- 补了 HTTP / JSON-envelope SSE / auth/session 节点的 request-id fallback 覆盖
- README 已更新说明 shared request-id fallback 行为

**验证结果**
- frontend-sdk runtime tsc：通过
- node tests：通过
- `apps/web-user` typecheck：通过

**剩余风险**
- billing/order/ticket/ICP/file/citation-detail 仍在 frontend-sdk 自有 contract outlet
- `GET /api/v1/icp/applications` 还没有 frozen canonical contract
- `CHAT_STREAM_EVENTS_NOT_FOUND` 对应的 route/error 还没冻到共享规范里
- app 仍通过 local shim 消费 SDK，workspace package import convention 还没统一

**建议后续接手动作**
1. 推进 frozen contract promotion，尤其 ICP list 与 chat stream replay。
2. 视情况把 app 对 SDK 的消费从 local shim 收敛到正式 workspace import。

关键文件：
- `docs/status/supervisor-frontend-sdk-status.md`
- `logs/supervisor-frontend-sdk/state.json`
- `packages/frontend-sdk/src/core/http.ts`
- `packages/frontend-sdk/src/core/envelope.ts`
- `packages/frontend-sdk/src/web-user/session.ts`

---

### D. supervisor-auth-marketing-research

**状态**
- phase: `done-real-infra-migration`
- runtime stance：**MySQL-first**，未配 DATABASE_URL 时保留 SQLite fallback 仅供 local/test

**已完成**
- auth / research / marketing 已从本地 JSON 主存储迁到数据库表
- 旧 `*_DATA_PATH` 已退化为 bootstrap/migration fixture，不再是运行期主存储
- poster 结果支持 MinIO-friendly 路径

**接手时要注意**
- 生产要真正算“完全实链路”，仍取决于 MySQL 和可选 MinIO 环境配置
- 若环境没配 MySQL，会走 SQLite fallback；这不能算生产主链路完成

关键文件：
- `docs/status/supervisor-auth-marketing-research-status.md`

---

### E. supervisor-knowledge-rag

**状态**
- phase: `done`
- 但这里只能解释为：**已完成这一轮迁移推进，不等于整条链路彻底封口**

**已完成**
- metadata/admin async jobs 更偏 MySQL
- indexing queue 活动路径转向 Redis list
- search 转向 OpenSearch + Qdrant 优先
- snapshot/export trace QA 已增强

**残留风险（最重要）**
- `documents/chunks` 仍主要存在本地 runtime JSON
- admin document creation 仍偏 file-backed import root
- auth/RBAC 仍是 local-baseline 级别
- live connector proof 还没闭环

**接手时优先级**
1. 先修 MinIO auth 与 Qdrant/OpenSearch bootstrap 问题。
2. 再做 knowledge/rag live connector proof。
3. 最后继续处理 `documents/chunks` 从 runtime JSON 彻底拔走。

关键文件：
- `docs/status/supervisor-knowledge-rag-status.md`
- `apps/knowledge-service/app/services/store.py`
- `apps/knowledge-service/app/services/runtime_sync.py`
- `apps/knowledge-service/app/services/indexing_worker.py`

---

### F. supervisor-foundation

**状态**
- phase: `completed-solid-baseline`

**已完成**
- shared error catalog / trace nullability / auth continuation / admin-agent config 共享契约已补齐
- `scripts/validate_foundation.py` 已加强

**接手价值**
- 其他 AI 接手时，可以直接依赖它已经补齐的 shared schema / OpenAPI / validator 基线

关键文件：
- `docs/status/supervisor-foundation-status.md`
- `scripts/validate_foundation.py`
- `packages/common-schemas/`
- `openapi/`

---

### G. supervisor-web-user

**当前已知状态（上一轮）**
- phase: `live-history-adopted-browser-validated`

**已完成**
- 默认走 live API，不再 mock-first
- research / marketing history 优先真实 list endpoint
- 浏览器侧 17 条主线/异常恢复流已验证

**仍有残留**
- ICP application history 仍缺 canonical list endpoint
- 一些 live attachment staging 依赖后端 file upload/complete 语义

关键文件：
- `docs/status/supervisor-web-user-status.md`

---

## 4. 后续 AI 接手顺序建议

### P0：优先补最后的验收短板
1. 处理 MinIO `UnauthorizedAccess`
2. 拉起并稳定 Qdrant / OpenSearch
3. 跑通 `knowledge-rag-admin` live shared-connector proof
4. 更新 QA state/status，让 knowledge-rag 也进入“已验死”口径

### P1：继续拔残留本地存储
1. `knowledge-service documents/chunks` 从 runtime JSON 拔走
2. admin document creation 从 file-backed import root 往对象存储/共享上传契约推进

### P2：合同/共享层收尾
1. ICP list frozen contract promotion
2. chat stream replay / `CHAT_STREAM_EVENTS_NOT_FOUND` frozen promotion
3. app -> SDK workspace import 统一化

---

## 5. 停机前的明确信息

本次交接不是因为自动任务失败，而是**主动停机交接给其他 AI**。

停机前的硬状态：
- manager：正常
- integration-qa：正常推进，且结果最好
- orchestrator：正常推进
- frontend-sdk：正常推进
- 其他 supervisor：大概率已完成当前轮次并退出

---

## 6. 交接后接手人最先该看什么

建议按这个顺序看：
1. `docs/status/supervisor-handoff-2026-04-16-ai-takeover.md`（本文）
2. `logs/supervisor-integration-qa/state.json`
3. `docs/status/supervisor-integration-qa-status.md`
4. `docs/status/supervisor-knowledge-rag-status.md`
5. `docs/status/supervisor-orchestrator-status.md`
6. `docs/status/supervisor-frontend-sdk-status.md`
7. `docs/status/supervisor-auth-marketing-research-status.md`
8. `docs/status/supervisor-foundation-status.md`
9. `docs/status/supervisor-web-user-status.md`

---

## 7. 一句话交接结论

**除了 knowledge-rag 这条线还没彻底验死，其它关键主链路已经基本进入“真实后端主路径 + QA 有证据”的状态。当前停机只是为了换别的 AI 接着干，不是因为 supervisor 体系挂了。**
