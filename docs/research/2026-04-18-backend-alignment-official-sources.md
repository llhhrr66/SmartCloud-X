# SmartCloud-X 后端对齐开发文档官方资料包

- 日期：2026-04-18
- 更新时间：2026-04-18T02:35:30.8340472+08:00
- 目的：为尚未完全对齐 [SmartCloud 开发文档](D:/1HTML5/实习项目/SmartCloud/kaifawendang.md) 的后端能力补齐“官方资料入口 + 阅读重点 + 本项目落地产物建议”
- 当前参考现状：
  - 代码与状态文档：`docs/status/*.md`
  - QA 尾项：`docs/reviews/known-issues.md`
  - 当前系统已通过 repo 级 readiness：`scripts/qa/check_release_readiness.py`

## 使用方式

这份资料包不是“实现说明”，而是“开始实现前先读什么、实现后要交什么”。

每个主题都按下面结构整理：

1. 当前缺口
2. 官方文档入口
3. 建议先读的内容
4. 本项目应该产出的实现/文档/验证物

---

## 1. MongoDB 进入主链

### 当前缺口

开发文档把 MongoDB 定义为正式数据层的一部分，用于承接：

- `conversation_messages`
- `agent_reasoning_logs`
- `research_reports`
- `marketing_assets`
- `raw_tool_payloads`
- `session_snapshots`

但当前主链仍然是：

- MySQL
- Redis
- MinIO
- Qdrant
- OpenSearch

MongoDB 还没有进入当前核心运行路径。

### 当前仓库依据

- 当前 knowledge/rag 主链权威仍是 MySQL / Redis / MinIO / Qdrant / OpenSearch，见 `docs/status/supervisor-knowledge-rag-status.md`
- 当前 orchestrator / tool-hub / business-tools 主链没有 MongoDB 运行证据
- 当前仓库中尚未看到 `apps/*` 服务把 MongoDB 放进正式 runtime baseline 的状态文档

### 官方文档入口

- MongoDB Python Drivers 总入口  
  <https://www.mongodb.com/docs/drivers/python-drivers/>
- PyMongo + FastAPI 官方教程  
  <https://www.mongodb.com/docs/languages/python/pymongo-driver/current/integrations/fastapi-integration/>
- PyMongo Stable API / 连接选项  
  <https://www.mongodb.com/docs/languages/python/pymongo-driver/current/connect/connection-options/stable-api/>
- PyMongo GitHub（官方驱动）  
  <https://github.com/mongodb/mongo-python-driver>

### 建议先读的内容

- `AsyncMongoClient` 的初始化与应用生命周期绑定方式
- FastAPI 中如何在 lifespan 中创建并关闭 MongoDB 连接
- BSON / JSON 类型序列化注意事项
- schema 设计上如何区分：
  - 高吞吐原始消息
  - 审计日志
  - 推理过程
  - 快照

### 本项目应产出的内容

- `MongoDB` 在本项目中的权威职责划分文档
- 一份 `docs/contracts/change-requests/*.md`，说明 MongoDB 将接管哪些表意域
- `apps/*` 中对 Mongo 的真实接入代码
- 最低验证：
  - 单测
  - 重启后持久化验证
  - 与 MySQL / Redis 主路径不冲突的 smoke

---

## 2. Celery 正式异步体系

### 当前缺口

开发文档目标是 `Celery + Redis`。

现在虽然已经有：

- worker
- queue
- outbox

但不是 Celery 正式体系，当前更像 owner-local worker/queue 路线。

### 当前仓库依据

- 当前 owner 状态文档主要描述 worker / queue / outbox 与服务内任务路径，没有 Celery worker 作为正式 runtime 入口
- 当前 release readiness 与 QA 绿色不依赖 Celery，可反证 Celery 尚未进入主链

### 官方文档入口

- Celery First Steps  
  <https://docs.celeryq.dev/en/stable/getting-started/first-steps-with-celery.html>
- Celery User Guide  
  <https://docs.celeryq.dev/en/stable/userguide/>
- Celery Tasks  
  <https://docs.celeryq.dev/en/stable/userguide/tasks.html>
- Celery Configuration  
  <https://docs.celeryq.dev/en/stable/userguide/configuration.html>

### 建议先读的内容

- broker / result backend 的职责划分
- Redis 作为 broker / backend 的配置方式
- task retry、`acks_late`、`task_reject_on_worker_lost`
- task routing、queue 设计、time limits
- 为什么 Celery 文档强调 task 函数必须尽量 idempotent

### 本项目应产出的内容

- 一份 Celery 引入方案，明确：
  - 哪些异步动作迁入 Celery
  - 哪些保留当前 worker 模式
- `celery.py` / worker / task routing 配置
- Redis broker / result backend 配置方案
- 最低验证：
  - task enqueue
  - worker 消费
  - retry
  - result tracking

---

## 3. LangSmith 真接入

### 当前缺口

当前 active observability 还是：

- Phoenix
- Prometheus
- Grafana

LangSmith 现在仍然更接近 placeholder / deferred。

### 当前仓库依据

- `observability/langsmith/README.md` 明确把 LangSmith 标记为 placeholder / deferred
- 当前 active observability 路线仍是 Phoenix / Prometheus / Grafana

### 官方文档入口

- LangSmith 首页  
  <https://docs.langchain.com/langsmith/home>
- Observability Concepts  
  <https://docs.langchain.com/langsmith/observability-concepts>
- Tracing Quickstart  
  <https://docs.langchain.com/langsmith/observability-quickstart>
- Trace with OpenTelemetry  
  <https://docs.langchain.com/langsmith/trace-with-opentelemetry>

### 建议先读的内容

- LangSmith 中：
  - project
  - trace
  - run
  - thread
  的关系
- 自动 tracing 与 manual instrumentation 的边界
- OpenTelemetry 接入路径
- 什么时候应该走 LangChain/LangGraph 原生 tracing，什么时候直接走 OTel

### 本项目应产出的内容

- 一份 LangSmith 接入策略说明：
  - 当前哪些服务值得接
  - 哪些仍保持 Phoenix-only
- `LANGSMITH_*` 环境变量在本项目中的正式说明
- 一个真实可验证的 tracing path
- 最低验证：
  - traces 能进入 LangSmith
  - request / tool / retrieval / agent path 可见

---

## 4. A2A 独立协议层

### 当前缺口

当前系统已经有内部：

- supervisor
- handoff
- next_agent
- route plan

但还没有独立的 A2A 协议层。

### 当前仓库依据

- 当前多 Agent 仍是内部 supervisor / route plan / handoff 结构
- 当前仓库里没有独立的 A2A server、Agent Card、或 JSON-RPC 2.0 A2A 路由面

### 官方文档入口

- A2A 官方首页  
  <https://a2a-protocol.org/dev/>
- A2A 官方规范  
  <https://a2a-protocol.org/dev/specification/>
- A2A v1.0 说明  
  <https://a2a-protocol.org/latest/announcing-1.0/>
- A2A streaming / async  
  <https://a2a-protocol.org/latest/topics/streaming-and-async/>
- A2A 官方仓库  
  <https://github.com/google-a2a/A2A>

### 建议先读的内容

- `Agent Card`
- `JSON-RPC 2.0 over HTTP`
- `SSE` 流式任务更新
- async task / push notification
- agent discovery / capability advertisement
- A2A 与 MCP 的边界：
  - MCP 是 agent 调工具
  - A2A 是 agent 对 agent

### 本项目应产出的内容

- 一份 A2A 适配设计文档：
  - 先对外暴露哪个 agent
  - 用什么 Agent Card
  - 哪些内部 handoff 状态可映射到 A2A task lifecycle
- 至少一条 A2A 兼容 server 或 client path
- 最低验证：
  - discovery
  - basic request/response
  - streaming / async 至少一种

---

## 5. Dify 完整知识运营 / 同步体系

### 当前缺口

现在 Dify 已经不是空白：

- 已有 external knowledge adapter

但还不是开发文档里的完整目标：

- Dify 作为知识运营后台
- 数据集 API / 同步入口
- 非研发同学可配置的知识运营路径

### 当前仓库依据

- `docs/status/supervisor-knowledge-rag-status.md` 已明确当前阶段为 `dify-external-adapter-integration-ready`
- `docs/contracts/change-requests/2026-04-17-dify-external-knowledge-adapter-promotion.md` 说明当前 Dify adapter 仍是 owner-local，尚未 promoted 到 shared/openapi/frozen contract
- 当前 live 证据仍是 `blocked-external`，因为缺少真实 Dify 实例/凭证做 consumer proof

### 官方文档入口

- Dify Knowledge 总览  
  <https://docs.dify.ai/en/use-dify/knowledge/readme>
- 通过 API 维护 Dataset  
  <https://docs.dify.ai/en/use-dify/knowledge/manage-knowledge/maintain-dataset-via-api>
- Connect to External Knowledge Base  
  <https://docs.dify.ai/en/use-dify/knowledge/connect-external-knowledge-base>
- External Knowledge API  
  <https://docs.dify.ai/en/use-dify/knowledge/external-knowledge-api>

### 建议先读的内容

- dataset/document create-by-file
- 外部知识库接入方式
- Dify 侧如何传 `Authorization: Bearer {API_KEY}`
- `knowledge_id`、`retrieval_setting`、`metadata_condition` 的约定
- 什么时候应该 push dataset，什么时候应该 external knowledge adapter

### 本项目应产出的内容

- 一份 Dify 路线决策文档：
  - 继续 external adapter
  - 还是补 dataset push/sync
  - 或两者并存
- `blocked-external / configured / verified-live` 的状态定义
- 若走 dataset push：
  - dataset id / api key / 文档上传链
- 若走 external adapter：
  - 更完整的 live proof

---

## 6. QA-002：稳定 live 的 429 后端路由

### 当前缺口

当前 QA 里对 `429` 的覆盖主要来自受控 harness，不是稳定 live 路由。

### 官方文档入口

- FastAPI 错误处理  
  <https://fastapi.tiangolo.com/tutorial/handling-errors/>
- FastAPI Response Headers  
  <https://fastapi.tiangolo.com/advanced/response-headers/>
- MDN `429 Too Many Requests`  
  <https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Status/429>
- RFC 6585 Section 4 (`429 Too Many Requests`)  
  <https://datatracker.ietf.org/doc/html/rfc6585#section-4>

### 建议先读的内容

- 如何用 `HTTPException` 返回结构化错误
- 如何附加限流相关 header
- 哪个服务最适合暴露一个稳定 `429` 路由

### 本项目应产出的内容

- 至少一个 live-friendly `429` 路由
- 结构化错误体
- 相关 QA 断言

---

## 7. QA-003 / QA-004：repo-root Playwright 与 web-admin slice

### 当前缺口

- repo-root browser 现在主要覆盖 `web-user`
- `web-admin` 的同级 slice 还没有
- fresh runner 还要额外装依赖和浏览器

### 官方文档入口

- Playwright Projects  
  <https://playwright.dev/docs/test-projects>
- Playwright Web Server  
  <https://playwright.dev/docs/test-webserver>
- Playwright Running Tests  
  <https://playwright.dev/docs/running-tests>
- Playwright Auth  
  <https://playwright.dev/docs/auth>
- Playwright Browsers / 安装浏览器  
  <https://playwright.dev/docs/browsers>

### 建议先读的内容

- 如何按项目拆 browser slice
- 如何为 admin / user 建两套 project
- `webServer` 如何配置多服务
- 多角色认证如何管理

### 本项目应产出的内容

- repo-root `web-admin` browser slice
- fresh runner 启动说明进一步固化
- 必要时按 project 分组的 Playwright 配置

---

## 8. QA-007 / QA-010：冻结契约尾项

### 当前缺口

- persistence/backend matrix 仍然依赖 current frozen docs + change requests
- tool-hub response drift 仍是 frozen/reporting 尾项

### 当前仓库依据

- `docs/reviews/known-issues.md` 当前仍把 `QA-007` 与 `QA-010` 标记为 open
- `QA-007` 说明 shared frozen contracts 还没有一版更新后的 canonical cross-service persistence/backend matrix
- `QA-010` 说明 tool-hub response drift 仍停留在 frozen/reporting 尾项

### 官方文档入口

- OpenAPI Spec 总入口  
  <https://spec.openapis.org/oas/>
- OpenAPI 3.1 规范  
  <https://spec.openapis.org/oas/v3.1.0>

### 建议先读的内容

- 对外契约与内部实现的边界
- additive vs breaking change
- response schema 收口
- schema 与说明文档如何保持一致

### 本项目应产出的内容

- 更新版 shared persistence/backend matrix
- tool-hub response drift 的 frozen promotion 方案
- 对应 OpenAPI / change request / QA 同步

---

## 建议阅读顺序

如果目标是“尽快对齐开发文档”，建议按这个顺序读：

1. MongoDB
2. Celery
3. LangSmith
4. Dify
5. A2A
6. Playwright / OpenAPI 尾项

理由：

- 前 4 项直接决定后端主链对齐度
- A2A 决定多 Agent 协议层是否真正完成
- QA / contract 尾项决定最终验收口径

---

## 建议先写的项目内文档

建议下一步优先在项目里沉淀这些文档：

1. `docs/plans/2026-04-18-mongodb-mainline-alignment.md`
2. `docs/plans/2026-04-18-celery-async-alignment.md`
3. `docs/plans/2026-04-18-langsmith-integration-plan.md`
4. `docs/plans/2026-04-18-dify-final-shape.md`
5. `docs/plans/2026-04-18-a2a-protocol-adoption.md`

这样后面不管是你自己开窗口，还是继续让 AI 并行做，都不会再回到“先猜再做”的状态。
