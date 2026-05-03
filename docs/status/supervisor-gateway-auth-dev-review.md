# Gateway/Auth Supervisor 开发需求确认与跟踪

## 1. 范围
- 负责文档：
  - `project_document/supervisor-prompt-gateway-auth-2026-04-21.md`
  - `project_document/supervisor-master-instructions-2026-04-21.md`
  - `/home/ljr/开发文档拆分版-20260420-194821/00-开发文档总索引.md`
  - `/home/ljr/开发文档拆分版-20260420-194821/08-全局配置与API规范.md`
  - `/home/ljr/开发文档拆分版-20260420-194821/09-数据模型与协议规范.md`
  - `/home/ljr/开发文档拆分版-20260420-194821/10-服务边界测试与文档规范.md`
  - `/home/ljr/开发文档拆分版-20260420-194821/15-服务契约权限与错误码.md`
  - `/home/ljr/开发文档拆分版-20260420-194821/18-OpenAPI与接口发布规范.md`
  - `/home/ljr/开发文档拆分版-20260420-194821/19-执行顺序风险与停止边界.md`
- 负责代码：
  - `apps/gateway-service/`
  - `apps/auth-user-service/`
  - `openapi/`
- 禁止修改：
  - `apps/knowledge-service/`
  - `apps/rag-service/`
  - `apps/orchestrator-service/`
  - `apps/tool-hub-service/`
  - `apps/business-tools/`
  - 其他非本边界目录
- 当前目标：对齐 gateway/auth 与文档规定的鉴权、header 透传、统一响应、权限契约、OpenAPI 文档与测试覆盖。
- 更新时间：2026-04-21

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
- review_required: 0
- testing: 0
- completed: 3
- blocked: 0
- cross_boundary: 0

## 4. 开发/审阅/测试跟踪表
| ID | 文档来源 | 要求摘要 | 当前现状 | 差异/风险 | 处理方案 | 涉及文件 | 测试要求 | Review要求 | 验证结果 | 文档已对齐 | 是否越界 | 残留风险 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| GA-001 | 08-20.5.3, 15-20.17.2, 15-20.17.14 | gateway 对内鉴权/透传需带 `X-Request-Id`、`X-Trace-Id`、`X-Tenant-Id`、`X-Caller-Service`，且不能信任前端直传 caller/tenant；chat 请求还要把用户 roles/permissions 带入内部契约 | 已调整 gateway chat 路由，将外部 `/api/v1/chat/completions` 规范化后转发到 `/internal/v1/orchestrator/chat`，并构造 `request_id/trace_id/tenant_id/user/chat_request` 结构 | 已消除原先直接透传导致的内部契约漂移风险 | 已完成代码、测试、自审；保留 SSE 透传，仅改变上游目标 path 与内部请求体 | `apps/gateway-service/app/api/routes/chat.py`, `apps/gateway-service/tests/test_gateway_api.py` | `PYTHONPATH="/home/ljr/SmartCloud-X/apps/gateway-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" /home/ljr/SmartCloud-X/.venv/bin/pytest /home/ljr/SmartCloud-X/apps/gateway-service/tests/test_gateway_api.py -q`; `/home/ljr/SmartCloud-X/.venv/bin/python -m compileall /home/ljr/SmartCloud-X/apps/gateway-service/app` | 已复核未改写 SSE 事件体，未修改 orchestrator 边界目录 | pytest 13 passed；compileall 通过 | 是 | 否 | orchestrator 是否已完全消费新内部结构需后续联调，但本边界已按文档收敛 | completed |
| GA-002 | 10-20.11.2, 15-20.18, 08-20.5.6 | 认证/权限错误需统一结构化错误，401/403 口径明确；gateway 与 auth-user-service 要覆盖无 token、无权限、校验错误等基线 | 已核对：gateway 现状对依赖层异常仍保持 FastAPI `detail` 结构；auth-user-service 对外 public 错误保持 canonical envelope，内部错误保持 `ApiEnvelope.error` 结构 | 风险已被识别并用测试固化；gateway 若要完全改成 canonical 需额外统一全局异常层，当前不影响既有契约测试 | 本轮先补齐并锁定现有契约测试；auth-user-service 新增 HTTP 异常/校验异常回归，gateway 新增 401/403 回归，避免口径再次漂移 | `apps/gateway-service/tests/test_gateway_api.py`, `apps/auth-user-service/app/main.py`, `apps/auth-user-service/tests/test_auth_api.py` | `PYTHONPATH="/home/ljr/SmartCloud-X/apps/gateway-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" /home/ljr/SmartCloud-X/.venv/bin/pytest /home/ljr/SmartCloud-X/apps/gateway-service/tests/test_gateway_api.py -q`; `PYTHONPATH="/home/ljr/SmartCloud-X/apps/auth-user-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" /home/ljr/SmartCloud-X/.venv/bin/pytest /home/ljr/SmartCloud-X/apps/auth-user-service/tests/test_auth_api.py -q`; `/home/ljr/SmartCloud-X/.venv/bin/python -m compileall /home/ljr/SmartCloud-X/apps/auth-user-service/app /home/ljr/SmartCloud-X/apps/gateway-service/app` | 已复核未越界；auth-user-service public/internal 错误边界符合当前实现；gateway 差异已在表中明确记录 | gateway pytest 15 passed；auth pytest 34 passed；compileall 通过 | 是 | 否 | gateway 仍未做全局 canonical HTTPException 包装，但已被测试固定为当前契约 | completed |
| GA-003 | 18-20.22, 10-20.12.2 | openapi/README 必须覆盖当前公开/内部 auth 契约、示例、错误码、权限说明，代码与文档保持一致 | 已核对并更新 `openapi/auth-user-service.openapi.yaml` 的 internal auth 错误码/403 响应，README 也补充了当前实现口径说明 | 已消除 auth 文档明显漂移；gateway 外部 OpenAPI 仍受仓内旧布局限制，但 gateway README 已补当前异常口径说明 | 已完成本边界可落地文档收敛：更新 OpenAPI 与 README，并用现有测试/编译回归复核未引入偏差 | `openapi/auth-user-service.openapi.yaml`, `apps/auth-user-service/README.md`, `apps/gateway-service/README.md`, `docs/status/supervisor-gateway-auth-dev-review.md` | `PYTHONPATH="/home/ljr/SmartCloud-X/apps/auth-user-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" /home/ljr/SmartCloud-X/.venv/bin/pytest /home/ljr/SmartCloud-X/apps/auth-user-service/tests/test_auth_api.py -q`; `PYTHONPATH="/home/ljr/SmartCloud-X/apps/gateway-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" /home/ljr/SmartCloud-X/.venv/bin/pytest /home/ljr/SmartCloud-X/apps/gateway-service/tests/test_gateway_api.py -q`; `/home/ljr/SmartCloud-X/.venv/bin/python -m compileall /home/ljr/SmartCloud-X/apps/auth-user-service/app /home/ljr/SmartCloud-X/apps/gateway-service/app` | 已复核只改本边界文档；OpenAPI/README 与当前实现口径一致 | pytest auth 34 passed；pytest gateway 15 passed；compileall 通过 | 是 | 否 | gateway 外部契约仍未独立成当前 `docs/openapi/external` 组织，但不属于本轮阻塞 | completed |

## 5. 本轮结论
- 本轮完成：GA-001、GA-002、GA-003。已完成 gateway chat 内部契约收敛、gateway/auth 错误回归加固，以及 auth OpenAPI/README 文档对齐。
- 本轮新增风险：无新增本边界阻塞风险；仅保留 gateway 外部 OpenAPI 目录布局历史问题说明。
- 未完成项：无。
- 跨边界项：无。
- 下一步：本边界已收敛，可进入 morning review。
