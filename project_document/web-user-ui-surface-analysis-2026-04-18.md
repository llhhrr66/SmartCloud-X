# Web User 界面盘点

- 更新时间：2026-04-18 16:57:12 +08:00
- 更新原因：根据 `apps/web-user` 真实代码盘点当前用户端已有界面、路由与复用关系，为后续界面重构提供基线。
- 影响范围：`apps/web-user/src/App.tsx`、`apps/web-user/src/pages/*`、`apps/web-user/src/components/AppShell.tsx`、`apps/web-user/src/lib/permissions.ts`

## 当前真实路由界面

1. `/login`
   - 组件：`LoginPage`
   - 作用：登录、验证码登录、找回密码、重置密码

2. `/`
   - 组件：`DashboardPage`
   - 作用：用户工作台总览

3. `/profile`
   - 组件：`AccountPage`
   - 作用：个人中心、资料更新、密码修改、权限展示

4. `/account`
   - 作用：重定向到 `/profile`

5. `/chat`
   - 组件：`ChatPage`
   - 作用：聊天主链路

6. `/chat/:conversationId`
   - 组件：`ChatPage`
   - 作用：指定会话详情

7. `/sessions`
   - 组件：`SessionsPage`
   - 作用：会话历史

8. `/billing`
   - 组件：`BillingPage`
   - 作用：账单页

9. `/orders`
   - 组件：`OrdersPage`
   - 作用：订单中心、退款详情与申请

10. `/tickets`
    - 组件：`TicketsPage`
    - 实际实现：`ServiceDeskPage mode="tickets"`
    - 作用：工单中心

11. `/icp`
    - 组件：`IcpPage`
    - 实际实现：`ServiceDeskPage mode="icp"`
    - 作用：ICP备案页

12. `/service-desk`
    - 组件：`ServiceDeskPage`
    - 模式：`workspace`
    - 作用：订单 / 退款 / 工单 / ICP 综合服务台

13. `/research`
    - 组件：`ResearchPage`
    - 作用：研究任务与报告

14. `/marketing`
    - 组件：`MarketingPage`
    - 作用：营销活动、文案、海报任务

15. `*`
    - 组件：`NotFoundPage`
    - 作用：404

## 非独立路由但真实存在的界面状态

1. 登录恢复态
   - `ProtectedLayout` 中的 “正在恢复登录状态”

2. 无权限态
   - `FeatureRoute` 命中时展示 `AccessDeniedCard`

3. 应用公共壳
   - `AppShell`
   - 包含顶部状态区、主导航、右侧诊断区、最近埋点

## 页面复用关系

1. `TicketsPage` 和 `IcpPage` 不是完全独立页面
   - 它们都只是 `ServiceDeskPage` 的不同 `mode`

2. 当前很多页面在视觉结构上相似
   - 共用 `AppShell`
   - 大量页面共用 `PageHeader`
   - 大量页面采用相近的 `card + 表格/列表 + 右侧说明` 结构

3. 当前真正差异化最强的页面
   - `LoginPage`
   - `ChatPage`
   - `ServiceDeskPage`
   - `OrdersPage`

## 当前不存在的独立页面

1. 没有单独的 `SettingsPage`
2. 没有单独的“账单详情页”“退款详情页”“工单详情页”独立路由
3. 一些详情能力目前是页内面板、抽屉或模式切换，不是独立路由页面
