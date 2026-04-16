# Change Request Template

## Summary
- requester: supervisor-web-user
- date: 2026-04-16
- affected frozen path: packages/common-schemas/, packages/frontend-sdk/, docs/contracts/foundation-baseline.md
- blocking: no

## Background
主规范 `20.15.3` 已明确要求：
1. 页面依赖的接口字段应固化在 `packages/common-schemas/frontend`
2. `apps/web-user` / `apps/web-admin` 只能通过 `packages/frontend-sdk` 访问后端

当前 workspace 的 frozen baseline 尚未提供这两个前端共享产物，因此用户端 baseline 只能在 `apps/web-user` 内维持 app-local DTO 与 API adapter。

## Current Gap
1. 仓库中不存在 `packages/common-schemas/frontend`，导致用户端页面只能依赖 `apps/web-user/src/types/domain.ts` 维护前端 DTO。
2. 仓库中不存在 `packages/frontend-sdk/user`，导致用户端只能通过 app-local `src/api/client.ts` + `src/api/services/*` 访问后端。
3. 没有冻结的前端 SDK 生成/版本化约定，后续 web-user / web-admin 会重复维护 URL、envelope 兼容与错误码映射。

## Proposed Change
1. 由 foundation 增加最小前端共享目录基线：
   - `packages/common-schemas/frontend/`
   - `packages/frontend-sdk/user/`
   - `packages/frontend-sdk/admin/`
2. 在 frozen contract 中明确首批前端共享内容：
   - canonical user/admin DTO 导出规则
   - OpenAPI 生成来源与版本命名约定
   - SDK 对 canonical external envelope 与当前 internal compatibility envelope 的兼容策略
3. 在 `docs/contracts/foundation-baseline.md` 中补充当前阶段允许的临时 app-local fallback 说明，便于 downstream 在共享 SDK 发布前保持一致。

## Impacted Consumers
- supervisor(s): supervisor-web-user, supervisor-knowledge-rag, supervisor-foundation
- service(s) or surface(s): apps/web-user, apps/web-admin, future packages/frontend-sdk/*, shared frontend DTO pipeline
- required follow-up work:
  - foundation 提供最小前端 DTO / SDK frozen baseline
  - web-user / web-admin 在后续迭代中从 app-local adapter 迁移到 shared SDK
  - OpenAPI 生成流程补充前端消费说明

## Compatibility
- breaking or non-breaking: non-breaking additive change
- fallback or migration plan: 当前继续保留 `apps/web-user/src/types/domain.ts` 与 `src/api/services/*` 作为临时 app-local fallback，待 shared SDK 发布后再迁移
- temporary workaround already in use: `apps/web-user/src/api/client.ts`, `apps/web-user/src/api/services/*`, `apps/web-user/src/types/domain.ts`

## Evidence
- code reference(s):
  - `apps/web-user/src/api/client.ts`
  - `apps/web-user/src/api/services/chat.ts`
  - `apps/web-user/src/types/domain.ts`
- mock/example/stub reference(s):
  - `apps/web-user/tests/mocks/user/auth/login-success.json`
  - `apps/web-user/tests/mocks/user/chat/error-stream.sse`
- log or failing validation reference(s):
  - `logs/supervisor-web-user/blockers.log`
  - `docs/status/supervisor-web-user-status.md`

## Foundation Processing Result
- processed at: 2026-04-16
- decision: partially accepted; contract guidance implemented, shared SDK package creation deferred
- implemented:
  - documented the current temporary app-local frontend DTO/API-adapter fallback in `docs/contracts/foundation-baseline.md`
  - clarified in `docs/contracts/supervisor-ownership.md` that `packages/frontend-sdk/` is currently an unassigned shared-package placeholder and needs explicit owner assignment before code lands there
  - kept the existing frozen source of truth in `openapi/` and `packages/common-schemas/` so downstream web surfaces can continue aligning to shared contracts without creating a premature SDK package
- deferred:
  - creation of `packages/frontend-sdk/user` and `packages/frontend-sdk/admin`
  - creation of a new `packages/common-schemas/frontend/` export surface
- rationale:
  - the current foundation ownership baseline covers the frozen contract/schema/OpenAPI space, but does not yet assign implementation ownership for a new cross-app frontend SDK package
  - publishing ownership and fallback rules now keeps downstream work unblocked without silently expanding the frozen write scope
