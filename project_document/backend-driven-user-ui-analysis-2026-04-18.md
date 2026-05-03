# 后端驱动的用户端界面分析

- 更新时间：2026-04-18 16:57:12 +08:00
- 更新原因：按用户要求，忽略现有前端实现，仅根据后端服务、网关 BFF、OpenAPI 与 compose 运行边界推导用户端应该具备哪些界面。
- 影响范围：`apps/gateway-service`、`apps/auth-user-service`、`apps/orchestrator-service`、`apps/marketing-service`、`apps/research-service`、`openapi/`

## 核心结论

仅从后端能力出发，用户端至少应有 10 个一级主界面：

1. 登录 / 认证入口
2. 账户资料 / 安全设置
3. 聊天工作区
4. 会话历史 / 会话管理
5. 账单 / 发票
6. 订单 / 退款
7. 工单支持
8. ICP 备案
9. 营销中心
10. 研究中心

## 不是后端直接要求、但可由前端聚合出的界面

1. 首页 / 工作台总览
2. 服务台综合工作区
3. 通用设置页

这些界面不是后端直接提供单一资源面，而是前端可把多个接口族组合成一个工作台。

## 后端证据

### 1. 登录 / 认证入口

来源：
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/send-code`
- `POST /api/v1/auth/password/forgot`
- `POST /api/v1/auth/password/reset`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`

结论：
- 必须有登录界面
- 必须支持验证码与找回密码流程

### 2. 账户资料 / 安全设置

来源：
- `GET /api/v1/auth/me`
- `GET /api/v1/auth/profile`
- `PATCH /api/v1/users/me`
- `POST /api/v1/users/me/change-password`

结论：
- 必须有账户资料界面
- 必须有密码修改 / 安全设置界面
- 但后端没有“通知设置 / 通用偏好设置”证据，因此广义设置页不是强制项

### 3. 聊天工作区

来源：
- `POST /api/v1/chat/completions`
- `POST /api/v1/chat/sessions/{conversation_id}/continue`
- `POST /api/v1/chat/sessions/{conversation_id}/retry`
- `POST /api/v1/chat/sessions/{conversation_id}/cancel`

结论：
- 必须有聊天主界面
- 必须支持继续、重试、取消等会话内动作

### 4. 会话历史 / 会话管理

来源：
- `GET /api/v1/chat/sessions`
- `GET /api/v1/chat/sessions/{conversation_id}`
- `GET /api/v1/chat/sessions/{conversation_id}/messages`
- `POST /api/v1/chat/sessions/{conversation_id}/archive`
- `POST /api/v1/chat/sessions/{conversation_id}/restore`
- `DELETE /api/v1/chat/sessions/{conversation_id}`

结论：
- 必须有会话历史界面
- 必须有会话详情 / 消息记录查看能力

### 5. 账单 / 发票

来源：
- `GET /api/v1/billing/summary`
- `GET /api/v1/billing/details`
- `GET /api/v1/billing/invoices`

结论：
- 必须有账单界面
- 发票不一定单独成页，但必须是账单域的重要子界面

### 6. 订单 / 退款

来源：
- `GET /api/v1/orders`
- `GET /api/v1/orders/{order_no}`
- `POST /api/v1/orders/{order_no}/refunds`
- `GET /api/v1/refunds`
- `GET /api/v1/refunds/{refund_no}`

结论：
- 必须有订单界面
- 必须有退款相关界面
- 可做成一个“订单 / 退款”一体页，也可拆成两页

### 7. 工单支持

来源：
- `GET /api/v1/tickets`
- `POST /api/v1/tickets`
- `GET /api/v1/tickets/{ticket_no}`
- `POST /api/v1/tickets/{ticket_no}/replies`

结论：
- 必须有工单列表界面
- 必须有工单详情 / 回复界面

### 8. ICP 备案

来源：
- `POST /api/v1/icp/materials/check`
- `GET /api/v1/icp/applications`
- `POST /api/v1/icp/applications`
- `GET /api/v1/icp/applications/{application_no}`

结论：
- 必须有 ICP 备案界面
- 至少要支持材料检查、申请创建、申请详情

### 9. 营销中心

来源：
- `GET /api/v1/marketing/campaigns`
- `POST /api/v1/marketing/copy/generate`
- `GET /api/v1/marketing/copies`
- `GET /api/v1/marketing/copies/{copy_id}`
- `POST /api/v1/marketing/promotion-links/generate`
- `GET /api/v1/marketing/promotion-links`
- `GET /api/v1/marketing/promotion-links/{link_id}`
- `GET /api/v1/marketing/posters`
- `POST /api/v1/marketing/posters`
- `GET /api/v1/marketing/posters/{task_id}`
- `GET /api/v1/marketing/posters/{task_id}/result`

结论：
- 必须有营销中心
- 并且它不是单一列表页，而是“活动 + 文案 + 推广链接 + 海报任务结果”的复合界面

### 10. 研究中心

来源：
- `GET /api/v1/research/tasks`
- `POST /api/v1/research/tasks`
- `GET /api/v1/research/tasks/{task_id}`
- `GET /api/v1/research/tasks/{task_id}/status`
- `GET /api/v1/research/tasks/{task_id}/result`

结论：
- 必须有研究中心
- 必须有任务列表、任务状态、任务结果 / 报告结果界面

## 只适合作为页内能力，不建议直接做一级页面

1. 文件上传 / 文件详情
   - `/api/v1/files/upload-policy`
   - `/api/v1/files/complete`
   - `/api/v1/files/{file_id}`

2. 引用详情
   - `/api/v1/citations/{citation_id}`

这些更像聊天、工单、ICP、研究等页面里的子能力或抽屉，而不是一级导航页面。
