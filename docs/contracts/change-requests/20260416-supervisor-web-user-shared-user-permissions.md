# Change Request

## Summary
- requester: supervisor-web-user
- date: 2026-04-16
- affected frozen path: docs/contracts/shared/auth-contract.md
- blocking: no

## Background
用户端主规范 20.13 已明确会使用以下权限码：
- `user:chat.use`
- `user:billing.read`
- `user:order.read`
- `user:ticket.read`
- `user:ticket.write`
- `user:icp.read`
- `user:icp.write`
- `user:marketing.read`
- `user:marketing.write`
- `user:research.read`
- `user:research.write`

当前 `docs/contracts/shared/auth-contract.md` 仅包含极少量用户侧 starter permission，导致用户端基线与共享合同之间出现缺口。

## Current Gap
1. 用户端页面导航、mock 会话、业务服务层与主规范需要更多 end-user 权限码，但 shared auth contract 尚未登记。
2. ownership 规则要求不要在 app-local 代码中“静默扩展”共享权限命名，因此需要 foundation 冻结这些权限名称。

## Proposed Change
在 shared auth contract 中补充并冻结以下用户端 starter permission codes：
- `user:order.read`
- `user:ticket.read`
- `user:ticket.write`
- `user:icp.read`
- `user:icp.write`
- `user:marketing.read`
- `user:marketing.write`
- `user:research.read`
- `user:research.write`

如 foundation 认为需要拆分为更细粒度矩阵，也请至少先登记这些名称，确保前端、OpenAPI、RBAC 与自动化测试使用同一命名。

## Impacted Consumers
- supervisor(s): supervisor-web-user, supervisor-foundation, supervisor-orchestrator, supervisor-knowledge-rag
- service(s) or surface(s): apps/web-user, auth-user-service, gateway-service, OpenAPI/auth docs
- required follow-up work:
  - foundation 更新 shared auth contract
  - auth-user-service / gateway / SDK 对齐权限常量
  - downstream 移除本地“猜测式”权限名说明

## Compatibility
- breaking or non-breaking: non-breaking additive change
- fallback or migration plan: 当前 web-user 仅在 mock 用户会话中使用这些权限码，不修改 frozen contract 之前继续保持 app-local 显式声明
- temporary workaround already in use: `apps/web-user/src/api/mock.ts` 默认用户权限包含这些业务域能力

## Evidence
- code reference(s):
  - `apps/web-user/src/api/mock.ts`
  - `apps/web-user/src/components/AppShell.tsx`
  - `apps/web-user/src/pages/DashboardPage.tsx`
- spec reference(s):
  - `/home/ljr/SmartCloud/kaifawendang.md` section `20.13`
- log or status reference(s):
  - `logs/supervisor-web-user/blockers.log`
  - `docs/status/supervisor-web-user-status.md`

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - 在 `packages/common-auth` 中补充并冻结 `user:order.read`、`user:ticket.*`、`user:icp.*`、`user:marketing.*`、`user:research.*` starter permissions
  - 在 `docs/contracts/shared/auth-contract.md` 中同步 user-surface 权限基线说明
