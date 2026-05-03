# Gateway Supervisor Status

- 更新时间：2026-04-21 12:45:00 UTC
- 负责人：Hermes / gateway-service supervisor worker
- 当前阶段：按真实代码与最新测试证据复核；gateway 服务内职责已实现，且当前仓库已具备 Round 9 gateway acceptance `23/23` 与 Round 11 strict release gate 通过证据，文档口径必须跟随真实脚本结果

## 判定口径

本文件只以当前仓库真实代码、真实测试、真实运行探针结果为准。

- **已实现**：必须能绑定到代码路径 + 测试路径/函数名。
- **占位合同**：OpenAPI、目标式设计、状态文档中的预留描述，若缺代码/测试证明，不计为已完成。
- **外部环境阻塞**：上游服务未启动、凭证未提供、联调环境不可达；单独标注，不误判为 gateway 代码未完成。
- **目标态未达成**：系统整体交付目标尚未闭环，即使 gateway 自身代码已完成也不能上推为“全链路完成”。
- **发布门禁口径**：只要 gateway acceptance、focused/full-stack readiness、或 strict release gate 任一失败，就不得写成 release-ready。

## 本轮 strict rerun 执行结论

本轮不是复述旧状态，而是重新执行：
1. 阅读 gateway 关键实现与测试；
2. 对照实际路由、鉴权、SSE、日志、限流、health/readiness 代码；
3. 复核指定测试函数与 acceptance probe 结果；
4. 将 completed / partial / blocked 结论逐项绑定到代码路径、测试路径与运行证据。

结论：**gateway-service 自身 in-scope 代码能力已实现并有测试证明；Round 9 `gateway_acceptance_probe.py` 已通过 `23/23`，且 Round 11 `release_readiness.py --strict` 已通过，因此当前仓库已具备 gateway 主链路验收与 strict release gate 的通过证据。**

## 状态分层总览

### 已实现
1. 统一外部入口 / BFF 代理
2. Bearer 用户/管理员鉴权透传
3. `/api/v1/chat/completions` 的 SSE 透传与 citation 缓存
4. 结构化请求日志与 stream lifecycle 日志
5. 单实例基线限流
6. `/healthz` 与 `/readyz` 聚合探针
7. 关键 happy/error path 的 canonical 响应与上游错误透传

### 占位合同 / 不能直接视为完成
1. 任何仅存在于 placeholder OpenAPI 或目标式文档中的能力
2. 任何“上游未来会提供的字段/事件”但 gateway 当前代码未消费、测试未覆盖的行为
3. 系统级“聊天即最终可交付智能链路”叙述 —— 该结论必须依赖 orchestrator / rag / knowledge 实测，不可由 gateway 单独证明

### 外部环境阻塞
1. live acceptance probe 依赖的 upstream 全部不可连通时，`/readyz` 会转为 `503`
2. `/api/v1/auth/login` 等 BFF 路径在 upstream 不可达时返回 5xx/502，属于联调环境阻塞，不是 gateway 自身路由缺失

### 目标态未达成
1. gateway 虽已具备 chat stream proxy，但系统整体是否为“真实 RAG 聊天交付态”仍取决于 orchestrator 与 rag/knowledge 的真实闭环
2. 五个以上重点服务 readiness 合同若仍出现 `healthz-fallback` 或未全部 ready，则 gateway 聚合 readiness 不能视为最终流量门禁完成

## 逐项核查结果

### 1. unified entry
- 结论：**已实现**
- 代码路径：`apps/gateway-service/app/main.py`、`apps/gateway-service/app/api/routes/auth.py`、`chat.py`、`marketing.py`、`business.py`、`admin.py`、`owner_local.py`
- 测试证据：`apps/gateway-service/tests/test_gateway_api.py`
  - `test_auth_login_is_proxied_and_request_headers_are_forwarded`
  - `test_orders_and_refunds_bff_read_through_and_cache_business_tool_results`
- 说明：已证明 gateway 继续承担 BFF/代理边界，而不是在网关层实现业务编排。

### 2. authentication
- 结论：**已实现**
- 代码路径：`apps/gateway-service/app/services/auth.py`
- 测试证据：`apps/gateway-service/tests/test_gateway_api.py`
  - `test_gateway_missing_bearer_token_returns_canonical_401`
  - `test_gateway_missing_admin_permission_returns_canonical_403`
- 说明：用户/管理员主体绑定走 auth-user-service；缺 Bearer Token 时直接拒绝，不进入下游。

### 3. SSE output / citation cache
- 结论：**已实现**
- 代码路径：`apps/gateway-service/app/api/routes/chat.py`、`apps/gateway-service/app/services/http.py`、`apps/gateway-service/app/services/streaming.py`
- 测试证据：`apps/gateway-service/tests/test_gateway_api.py`
  - `test_chat_stream_passthrough_preserves_event_stream_and_stores_citation`
  - `test_stream_logging_emits_lifecycle_events_without_payload_leak`
- 说明：已证明 event-stream 透传与 citation 旁路缓存真实存在；日志不会泄露 citation snippet 原文。

### 4. request logging
- 结论：**已实现**
- 代码路径：
  - `apps/gateway-service/app/main.py`
  - `apps/gateway-service/app/services/http.py`
  - `apps/gateway-service/app/api/routes/chat.py`
  - `apps/gateway-service/app/services/logging.py`
- 测试证据：`apps/gateway-service/tests/test_gateway_api.py`
  - `test_stream_logging_emits_lifecycle_events_without_payload_leak`
  - `test_upstream_error_passthrough_preserves_status_and_logs_classification`
- 说明：日志是结构化事件，不是只有响应头；同时覆盖 upstream 错误分类和 stream 生命周期。

### 5. rate limiting
- 结论：**已实现（基线实现）**
- 代码路径：`apps/gateway-service/app/main.py`、`apps/gateway-service/app/middleware/rate_limit.py`
- 测试证据：`apps/gateway-service/tests/test_gateway_api.py`
  - `test_rate_limit_and_cors_headers_are_applied`
  - `test_rate_limit_exempts_health_routes`
- 说明：当前是内存固定窗口限流，满足当前基线要求；不应被描述为分布式全局限流目标态。

### 6. chat happy/error path
- 结论：**已实现**
- 代码路径：`apps/gateway-service/app/api/routes/chat.py`
- 测试证据：`apps/gateway-service/tests/test_gateway_api.py`
  - `test_chat_completions_rejects_non_object_body_with_canonical_4001001`
  - `test_gateway_missing_bearer_token_returns_canonical_401`
  - `test_upstream_error_passthrough_preserves_status_and_logs_classification`
- 说明：
  - body 非 object 时返回 canonical `4001001`，且不进入 orchestrator；
  - 缺 Bearer Token 时返回 `401`；
  - upstream 401/5xx 状态会被保留并写入错误分类日志。

### 7. health / readiness aggregation
- 结论：**已实现，但系统级门禁仍需以 acceptance 与 strict gate 结果为准**
- 代码路径：`apps/gateway-service/app/api/routes/health.py`
- 测试证据：`apps/gateway-service/tests/test_gateway_api.py`
  - `test_healthz_and_readyz_summarize_upstreams`
- 说明：gateway 已优先读取可用 upstream 的 `/readyz`；系统是否真正 ready 仍取决于各 upstream 运行状态与 probe 结果。

## 必须明确的非完成项

### 1. placeholder / 文档目标态不等于实现
- 结论：**目标态未达成**
- 说明：gateway 只能证明自身代理、鉴权、SSE、日志与健康探针行为；不能用目标式文档或 placeholder OpenAPI 推导“全链路用户聊天已完全可交付”。

### 2. 系统级交付已有通过证据
- 结论：**当前仓库已具备 gateway acceptance 与 strict gate 通过证据**
- 运行证据：Round 9 acceptance probe
```bash
cd /home/ljr/SmartCloud-X && /home/ljr/SmartCloud-X/.venv/bin/python scripts/qa/gateway_acceptance_probe.py --base-url http://127.0.0.1:8000 --timeout 10
```
- 结果：通过，`score 23/23`
- 关键现象：
  - `/healthz` 通过
  - `/readyz` 通过
  - `/api/v1/auth/login` 通过
  - `chat_stream` 为 `text/event-stream`
  - `marketing_campaigns`、`orders_list`、`refund_create`、`file_complete`、`admin_login`、`admin_dashboard` 均通过
- 发布门禁证据：Round 11 strict rerun
```bash
cd /home/ljr/SmartCloud-X && /home/ljr/SmartCloud-X/.venv/bin/python scripts/qa/release_readiness.py --strict
```
- 结果：通过，`ok=true`
- 判定：gateway 相关主链路与仓库级 strict gate 已有真实通过证据；后续发布声明仍应绑定候选环境当次脚本输出。

### 3. full-stack / strict gate 当前口径
- 代码证据：`scripts/qa/run_full_stack_validation.sh`、`scripts/qa/release_readiness.py`
- 说明：
  - `run_full_stack_validation.sh` 仍明确串联 gateway acceptance probe 与 `release_readiness.py --strict`；
  - Round 11 已证明 `release_readiness.py --strict` 当前返回通过；
  - 因此 gateway 相关状态不应再写成“仓库级 release gate blocked”，而应写成“已有通过证据，后续以候选环境当次脚本结果为准”。

## 本轮确认的真实代码状态

### 关键修复仍在代码中
1. `apps/gateway-service/app/api/routes/admin.py`
   - admin dashboard summary 路由可正常工作
2. `apps/gateway-service/app/middleware/rate_limit.py`
   - `Retry-After` 已按 fixed-window 语义向上取整
3. `apps/gateway-service/app/services/http.py`
   - 写请求 fallback 幂等键对 body 做 digest
4. `apps/gateway-service/app/api/routes/marketing.py`
   - `POST /api/v1/research/tasks` 先缓存 body 再代理，保证重试 key 稳定

## 运行与测试证据

### 单测
```bash
PYTHONPATH="/home/ljr/SmartCloud-X/apps/gateway-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" /home/ljr/SmartCloud-X/.venv/bin/pytest /home/ljr/SmartCloud-X/apps/gateway-service/tests/test_gateway_api.py
```
- 结果：`21 passed in 5.54s`

### 编译检查
```bash
cd /home/ljr/SmartCloud-X && /home/ljr/SmartCloud-X/.venv/bin/python -m compileall apps/gateway-service/app
```
- 结果：通过

## 严格口径结论
- gateway-service 编码：**已实现**
- gateway-service 服务内测试：**已实现并通过**
- placeholder 合同是否可视为完成：**否**
- 系统整体 live acceptance：**已具备通过证据（Round 9 `23/23`）**
- 仓库级 strict release gate：**已通过（Round 11）**
- 当前阶段判断依据：**代码现状 + 最新测试证据 + acceptance 实跑结果 + strict gate 规则**，**不以目标式文档或 placeholder OpenAPI 作为实现证明**

## 下一步建议
- gateway 本身暂不需要新增代码循环；
- 后续候选发布仍应先重跑 acceptance probe 与 strict gate，确保环境未回归；
- 若 future strict gate 再次被 known issues 或 readiness 阻塞，应按当次脚本输出回写文档，而不是沿用历史通过结论；
- 若上游 readiness 合同后续再次缺失，应在对应服务侧补 `/readyz`，而不是在 gateway 状态文档中误报“已全部 ready”。
