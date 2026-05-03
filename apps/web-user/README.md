# SmartCloud-X Web User

用户端 Web 前台应用，采用 **React + Vite + TypeScript** 实现，覆盖登录、会话列表、流式聊天、账单、工单、ICP、营销与研究任务等真实用户面能力。

本轮已把 `apps/web-user` 从“功能基线页集合”直接重构为 **live-first 的真实业务用户前台 + 可测试工作台**：
- 顶部全局壳明确展示当前模式、网关连通性、运行时配置来源与当前用户身份
- 首页改成主工作区入口，不再只是指标拼盘
- mock 仅保留为显式测试开关，live 模式下不再允许静默退回 mock
- 诊断信息保留在次级说明层，不再压过聊天、订单、服务台等主流程

## 当前能力
- 登录页与本地会话鉴权上下文
- 登录页现在会明确显示 live/mock、当前网关连通性与“不会自动退回 mock”的运行语义
- 登录页补齐验证码发送、找回密码 challenge、重置密码流程
- 验证码登录在前端先校验账号类型与登录通道是否匹配，避免短信/邮箱模式误配
- live 模式静默刷新与启动时会话恢复
- 用户工作台总览已重构为中文化主入口工作台，支持部分失败降级展示与能力边界说明
- 会话列表与聊天页
- 会话归档 / 恢复 / 删除等生命周期操作
- 会话详情页支持“重试上一轮”，对齐 `POST /api/v1/chat/sessions/{id}/retry`
- 会话详情页直接打开时会显式拉取会话详情；若会话不存在，会展示 404 风格空态而不是误判为新草稿
- SSE 流式事件消费能力（支持 mock / live）
- 聊天流在非正常断开时会自动重连，最多 3 次，并在页面上明确显示当前重连状态
- 聊天页新增 starter prompt 模板，帮助用户直接进入账单、技术、ICP、营销等高频场景
- app-local `conversationStore / messageStore / sseStore` 分离聊天状态，减少首屏重复请求并降低路由重渲染对流式体验的影响
- app-local telemetry 基线，覆盖 `page_view`、`login_submit`、`api_error`、`permission_denied`、`chat_stream_*`，并在壳层诊断区保留最近 40 条事件
- 账单、研究、营销页面骨架
- 顶部全局壳新增 live runtime 健康探测，通过 `/api/v1/auth/me` 区分“网关可达 / 待登录 / 契约缺口 / 服务端异常 / 不可达”
- 订单中心 `/orders`，支持订单详情抽屉、退款申请与退款详情时间线
- 工单中心 `/tickets` 与 ICP 页面 `/icp`，支持与综合服务台共享数据/表单状态
- 工单中心补齐详情面板与补充回复区，对齐 `GET /api/v1/tickets/{ticket_no}` 与 `POST /api/v1/tickets/{ticket_no}/replies`
- 聊天页支持一键转人工协助，自动把会话/trace/最近用户诉求预填到 `/tickets`
- 营销文案生成器与海报任务工作台
- 营销中心在 live 模式下支持海报任务自动轮询，最长 10 分钟，超时后提示手动刷新
- 服务台页面，覆盖订单退款、工单提交、ICP备案与附件凭据占位流程
- 服务台上传区按用途区分通用附件与 ICP 材料，并支持移除已暂存文件，避免工单/退款附件误进入备案表单
- 类型化 API client 与服务层占位（auth/chat/billing/service-desk/research/marketing/user/files/citations）
- live 写接口统一补齐稳定 `X-Request-Id`，并为会话/聊天/任务/附件等重复点击风险路径生成确定性 `Idempotency-Key`
- 默认走 live API；mock 仅作为显式开发 / 测试开关保留
- 个人中心页面，覆盖资料更新、密码修改与权限展示
- 修改密码成功后会强制退出并回到登录页，且 mock 模式也会真实更新本地密码基线，符合 spec `20.15.1`
- 引用详情抽屉，可从聊天消息直接查看 citation 片段
- live 模式下优先读取研究/海报真实历史列表；本地任务跟踪仅在列表暂不可用或存在短暂一致性缺口时做补回
- 研究报告文件预览入口，可根据 `report_file_id` 拉取导出文件信息
- Docker + Nginx 容器化基线，可直接构建 SPA 发布镜像
- 容器启动时自动生成 `runtime-config.js`，支持在不重新构建镜像的情况下覆盖 API 地址、标题、版本、mock 开关与超时配置

## 本地运行
```bash
cd apps/web-user
npm install
npm run dev
```

默认端口：`3100`

## 浏览器验证
当前用户端基线已经接入 Playwright 浏览器回归：

```bash
cd apps/web-user
npm run test:e2e
```

默认每次都会重新拉起本地 mock API 和 Vite dev server，避免修改代码后误复用旧进程造成假失败；仅在你明确需要复用现有服务时再手动加上：

```bash
PLAYWRIGHT_REUSE_SERVER=1 npm run test:e2e
```

默认 runner 现在会为当前这轮 Playwright 运行共享一组临时端口，并等待 mock API / Vite 真正输出 ready 日志后再开始测试；即使历史默认端口 `38090` 已被别的本地进程占用，`npm run test:e2e` 也不会直接误撞旧端口。

当前已真实浏览器验证的主链路：
- 登录并进入用户工作台总览
- 找回密码 challenge + 重置密码，并使用新密码重新登录
- 聊天重试上一轮，并把会话上下文 / trace 预填到协助工单草稿
- 聊天发起、SSE 一次中断后的自动重连、引用详情打开
- 引用详情 `403` 权限错误展示
- 账单页一次性 `401` 后静默刷新恢复
- 营销页权限拒绝 UX 与 `429` 结构化 API 错误展示
- 营销文案生成、海报任务创建、研究任务创建，并在清空浏览器任务注册表后仍可从 live 历史列表重新读回
- `/runtime-config.js` 覆盖标题、版本、API 基址与 SSE 心跳后，登录页和应用壳会按运行时配置渲染
- `/orders` 订单详情抽屉、退款申请与刷新后的退款时间线可见性
- `/profile` 资料更新、密码修改、强制重新登录
- 研究任务完成、报告文件预览，以及报告文件 `404` 错误展示
- `/sessions` 重命名 / 归档 / 恢复 / 删除
- 工单创建
- `/service-desk` 综合工作台的附件分流、工单创建、ICP 预检与提交联动
- ICP 上传登记、材料预检查、提交备案申请，以及 canonical list endpoint 缺失时的“浏览器跟踪回填”来源提示

当前仍属 baseline-only、尚未进入 Playwright 覆盖的 owned 能力：
- Docker / Nginx entrypoint 生成 `runtime-config.js` 的容器内注入路径

## 容器构建
因为 `tsconfig.json` 依赖仓库根目录的 `tsconfig.base.json`，Docker 构建需要使用仓库根目录作为 build context。

在 `apps/web-user/` 下执行：

```bash
npm run docker:build
```

或在仓库根目录执行：

```bash
docker build -f apps/web-user/Dockerfile -t smartcloud-x-web-user:local .
```

可覆盖的构建参数（同时也是容器启动时可覆盖的运行参数）：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `VITE_APP_TITLE` | `SmartCloud-X User Console` | 构建时注入页面标题 |
| `VITE_APP_VERSION` | `0.1.0` | 构建时注入前端版本号，并透传到 `X-Client-Version` |
| `VITE_API_BASE_URL` | `http://localhost:8000` | 构建时注入网关地址 |
| `VITE_USE_MOCK_API` | `false` | 容器镜像默认关闭 mock，面向联调环境 |
| `VITE_REQUEST_TIMEOUT_MS` | `30000` | JSON API 超时 |
| `VITE_SSE_HEARTBEAT_SECONDS` | `15` | SSE 心跳间隔 |

运行镜像后，容器内由 Nginx 提供静态页面，并暴露 `GET /healthz` 作为基础健康检查。Nginx 官方 entrypoint 会先执行 `docker-entrypoint.d/40-runtime-config.sh`，把当前容器环境变量写入 `/usr/share/nginx/html/runtime-config.js`。

示例：在不重建镜像的情况下切换联调网关

```bash
docker run --rm -p 38080:80 \
  -e VITE_API_BASE_URL=http://host.docker.internal:8000 \
  -e VITE_APP_TITLE=SmartCloud-X\ User\ Console\ \(QA\) \
  smartcloud-x-web-user:local
```

## 环境变量
复制 `.env.example` 为 `.env.local`：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `VITE_APP_TITLE` | `SmartCloud-X User Console` | 页面标题与侧栏品牌 |
| `VITE_APP_VERSION` | `0.1.0` | 页面展示版本号，并透传到 `X-Client-Version` 请求头 |
| `VITE_API_BASE_URL` | `http://localhost:8000` | 网关地址 |
| `VITE_USE_MOCK_API` | `false` | 是否启用本地 mock 数据与流式模拟；默认关闭，需显式打开 |
| `VITE_REQUEST_TIMEOUT_MS` | `30000` | JSON API 超时 |
| `VITE_SSE_HEARTBEAT_SECONDS` | `15` | 与主规范一致的 SSE 心跳间隔 |

生产容器默认也会读取同名环境变量，并以 `runtime-config.js` 的方式覆盖构建期默认值。

## 页面结构
- `/login`：登录页
- `/`：工作台总览
- `/chat/:conversationId?`：流式聊天主界面
- `/sessions`：对话历史与筛选
- `/billing`：账单总览
- `/orders`：订单中心
- `/tickets`：工单中心
- `/icp`：ICP 材料预检与申请跟踪
- `/service-desk`：综合服务台（订单 / 退款 / 工单 / ICP / 附件凭据）
- `/research`：研究任务
- `/marketing`：营销活动与海报任务
- `/profile`：个人资料、密码与权限概览（兼容 `/account` 重定向）

## 目录说明
```text
src/
  api/           # HTTP client、mock 实现、业务服务层
  auth/          # 鉴权上下文
  components/    # 通用与聊天组件
  config/        # 环境配置
  lib/           # storage / format / utils
  pages/         # 页面级组件
  stores/        # 聊天 conversation/message/sse app-local store
  types/         # 前端领域模型
docs/
  api-integration.md  # 用户端联调说明与当前合同缺口
public/
  runtime-config.js   # 默认运行时配置占位，允许部署时覆盖
docker-entrypoint.d/
  40-runtime-config.sh # 容器启动时生成运行时前端配置
Dockerfile            # 基于仓库根上下文的容器构建基线
nginx.conf            # SPA 路由回退、runtime-config 与基础健康检查
tests/
  mocks/user/auth/*.json  # 登录成功 / 密码错误 / token 过期 / 验证码 / 密码找回样例
  mocks/user/chat/*.sse  # 可回放 SSE 事件样例
  mocks/user/**/*.json   # billing / orders / tickets / icp / marketing / research JSON fixture
```

## 联调说明
- 默认关闭 `VITE_USE_MOCK_API`，服务层会按主规范请求 `/api/v1/**` 接口。
- 验收模式必须保持 `VITE_USE_MOCK_API=false`，并让 `VITE_API_BASE_URL` 指向真实 gateway（compose 基线为 `http://localhost:8000`）。
- 需要纯前端演示或本地离线调试时，再显式设置 `VITE_USE_MOCK_API=true`。
- 登录页现在覆盖 `POST /api/v1/auth/send-code`、`POST /api/v1/auth/password/forgot`、`POST /api/v1/auth/password/reset` 的完整找回密码链路。
- 短信验证码登录仅接受手机号，邮箱验证码登录仅接受邮箱，前端会在调用 auth API 前先做约束校验。
- 聊天流式事件同时兼容 baseline/mock 事件与主规范 `message.started` / `agent.routed` / `tool.started` / `message.completed` 等 canonical 事件。
- `/chat` 现在会在 SSE 非正常断开后自动重连，最多 3 次；重连过程中会保留会话上下文、重置当前流快照并在右侧状态区提示当前重连次数。
- `/chat` 现在使用 app-local `conversationStore / messageStore / sseStore` 分离会话、消息和流式状态，避免首屏重复拉取同一会话数据，并减少页面重渲染对流式链路的干扰。
- `/chat/:conversationId` 现在支持直接重试上一轮消息；mock 模式会同步生成新的用户/助手 exchange，live 模式对齐会话级 retry 响应并刷新消息列表。
- `/chat/:conversationId` 现在会先拉取会话详情再加载消息；如果会话已删除或不存在，页面会展示空态并引导返回 `/sessions` 或重新发起对话。
- chat 页面支持点击引用卡片查看 `citations/{citation_id}` 详情。
- 无消息时会展示常用提问模板，可一键写入场景与问题草稿，提升 baseline 的开箱可用性。
- live 模式下，研究任务与海报任务列表优先读取 `/api/v1/research/tasks` 与 `/api/v1/marketing/posters`；若列表暂不可用或未及时返回最新任务，前端才回补当前浏览器最近跟踪的详情。
- live 模式下，账单工作区改为部分失败降级：若明细/发票/订单/工单中的某一分区暂不可用，页面仍会保留其余已成功分区并明确提示缺失域。
- live 模式下，营销海报任务会自动轮询 3 秒/次，最长 10 分钟；超过窗口后停止后台轮询并引导手动刷新，贴近 spec `20.15.1`。
- live 模式下，服务台中的 ICP 申请历史会优先展示当前浏览器已提交并跟踪过的 `application_no`，因为主规范当前只冻结了详情接口；页面会显式展示“浏览器跟踪回填”状态，并说明这不是 canonical list endpoint。
- `/orders` 页面优先读取 `GET /api/v1/orders/{order_no}` 与 `GET /api/v1/refunds/{refund_no}`；若 live 接口尚未完成，前端会回退到已加载的列表级数据，且不会丢失筛选状态。
- 营销中心支持 `POST /api/v1/marketing/copy/generate` 的文案生成占位，研究中心支持根据 `report_file_id` 拉取文件详情。
- 服务台支持 `POST /api/v1/files/upload-policy` 的附件凭据申请占位；上传区现区分通用附件（`chat_attachment`）与 ICP 材料（`icp_material`），mock 模式下可模拟 `files/complete`，并支持在提交前移除已暂存文件。
- API client 现在会自动补齐 `X-Client-Platform`、`X-Client-Version`、`X-Tenant-Id`、`X-User-Id`，更贴近主规范 `20.5.3` 的联调预期。
- 侧栏新增最近埋点面板，当前 app-local telemetry 会记录 `page_view`、`login_submit`、`api_error`、`permission_denied` 与 `chat_stream_start/end/error`，用于对齐 spec `20.15.4` 的最小事件集。
- `src/config/env.ts` 会优先读取页面加载时注入的 `/runtime-config.js`，因此容器部署时可直接通过环境变量切换 API 地址与 UI 标识，而无需重建镜像。
- API client 与前端写服务现在会统一补齐稳定 `X-Request-Id` / `Idempotency-Key`，避免随机 key 破坏聊天、退款、海报、研究、附件等重复提交幂等语义。
- 聊天页的“人工协助”卡片会把当前会话号、trace、当前 Agent、最近用户诉求和 action/error 信号预填到 `/tickets`，缩短从 AI 对话切到人工工单的路径。
- `/tickets` 与 `/icp` 是面向 spec 页面映射的聚焦入口，底层仍复用同一套 service desk API adapter 与 mock/live 数据层。
- `/tickets` 现在额外支持工单详情与补充回复闭环；mock 模式内置回复时间线，live 模式对齐 ticket detail / replies 接口。
- `tests/mocks/user/` 现提供 auth / billing / orders / tickets / icp / marketing / research JSON fixture，以及包含 error path 的 SSE 样例；auth 目录已补齐 send-code / forgot / reset 样例，方便后续接入 mock server、E2E 或截图回归。

## 当前集成注意事项
1. foundation 已明确：用户侧外部接口使用 canonical `code/message/data/request_id/timestamp` envelope，当前 app-local client 仍保留对 internal `ApiEnvelope<T>` 的兼容解析，便于网关迁移期联调。
2. 研究任务与营销海报历史已改为优先使用 live 列表接口；本地任务注册表现在只作为回补兜底，不再是默认来源。
3. ICP 申请历史在主规范中仍缺少列表接口，live 模式只能基于本地已跟踪的申请号回填详情。
4. 订单详情与退款详情页已接好 `/orders/{order_no}`、`/refunds/{refund_no}` 占位；若后端尚未落地，前端会降级回列表级信息。
5. 真实附件上传与 cancel 的高级 UX 仍保留客户端占位；聊天 retry 已按当前会话级合同接通，但更丰富的恢复/重放策略仍取决于后端后续能力。
6. 容器运行时配置现已在 `apps/web-user` 内自给自足；若后续 foundation 统一前端 runtime-config 契约，可再将该实现收敛到共享约定。
