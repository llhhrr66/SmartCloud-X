# User 端 PC 登录页高保真原型记录

- 更新时间：2026-04-18 23:10:20 +08:00
- 更新原因：基于后端真实认证能力，为 `user` 端补充仅限 PC 桌面端的登录页高保真 HTML 原型，并记录设计边界与产物位置。
- 影响范围：`apps/auth-user-service`、`apps/gateway-service`、`openapi/`、`deploy/docker-compose/`、`apps/web-user/prototype-user-pc/login/index.html`

## 后端证据来源

1. `apps/auth-user-service/README.md`
2. `openapi/auth-user-service.openapi.yaml`
3. `apps/auth-user-service/app/routes.py`
4. `apps/auth-user-service/tests/test_auth_api.py`
5. `apps/gateway-service/README.md`
6. `apps/gateway-service/app/api/routes/auth.py`
7. `deploy/docker-compose/docker-compose.yml`
8. `docs/contracts/shared/auth-contract.md`
9. `docs/contracts/shared/api-conventions.md`

## 固定结论

1. 用户端登录页只允许展示这些认证动作：
   - 密码登录
   - 短信验证码登录
   - 邮箱验证码登录
   - 找回密码
   - 重置密码
2. 不允许出现这些常见元素：
   - 注册
   - 微信 / GitHub / 钉钉等第三方登录
   - 企业 SSO
   - 图形验证码
   - 记住我
   - 租户选择器
3. 用户端真实外部入口是 `web-user(:3100) -> gateway-service(:8000) -> auth-user-service(:8001)`。
4. 找回密码不是单步改密：
   - 第一步调用 `/api/v1/auth/send-code` + `/api/v1/auth/forgot-password`
   - 第二步调用 `/api/v1/auth/reset-password`
   - 第二步仍依赖 `challenge_id`、原账号、原验证码、新密码、确认密码

## 原型设计取向

1. 采用 PC 双栏布局，不做居中单卡片模板。
2. 左侧承载可信与运行边界信息：
   - 产品名称
   - 认证入口定位
   - 登录后可达能力
   - 网关 / 认证服务 / 端口边界
3. 右侧承载真实认证动作与状态：
   - 三种登录方式切换
   - 发码动作
   - 倒计时 / 发送中 / 失败提示
   - 找回密码两步流程
   - 网关异常态
   - 未登录进入态
4. 视觉关键词：
   - 专业
   - 可信
   - 服务型
   - 企业级
   - 克制

## 产物位置

- 原型文件：`apps/web-user/prototype-user-pc/login/index.html`

## 本地验证

1. 已通过本地 HTTP 静态服务预览原型。
2. 已使用 Playwright 打开页面并验证：
   - 默认登录态
   - 登录失败态
   - 找回密码第一步
   - 找回密码第二步
   - 网关异常态
3. 已按桌面端 UI / UX / 可访问性要点补充：
   - skip link
   - `focus-visible` 焦点环
   - `aria-live` 提示区
   - 表单 `label / name / autocomplete`
   - 错误信息就近展示
   - `prefers-reduced-motion` 兜底

## 当前保留说明

1. 原型使用 Tailwind CDN，适合单文件高保真演示，不作为生产构建方案。
2. 该原型未接入现有 `src/pages/LoginPage.tsx`，目的是在不扰动当前业务实现的前提下，单独输出登录页方案。
