# Change Request

## Summary
- requester: supervisor-frontend-sdk
- date: 2026-04-16
- affected frozen path: `packages/common-schemas/`, `docs/contracts/shared/schema-catalog.md`, `docs/contracts/foundation-baseline.md`, `openapi/`
- blocking: no

## Background
当前 `packages/frontend-sdk/` 已开始作为共享前端 SDK 被 `apps/web-user/` 和 `apps/web-admin/` 薄适配复用，但冻结 shared schema / OpenAPI 仍未覆盖用户端以下业务面：

1. billing
2. order / refund
3. ticket
4. ICP
5. file
6. citation detail

为了避免这些前端面继续长期停留在 app-local DTO / adapter，当前实现已在 owned 路径 `packages/frontend-sdk/src/web-user/business-contracts.ts` 中补出最小前端 contract typing outlet，并把对应 mapper / adapter 迁移到共享 SDK。
本轮已进一步把分页 list alias、page query/result typing、enum-safe normalizer、file / citation-detail adapter 与共享错误 / SSE reconnect helper 测试补齐到 `packages/frontend-sdk/`，从而让 web-user 继续以 thin shim 方式消费共享 SDK，而不是回退到 app-local DTO。

## Current Gap
1. `packages/common-schemas/` 没有冻结的 user-facing DTO/schema 覆盖 billing/order/refund/ticket/ICP/file/citation-detail。
2. `openapi/` 当前没有与 web-user 直接消费一致的这些业务面 canonical response/request 定义。
3. 没有被冻结的 shared frontend contract 时，前端只能在 SDK 内维护 owned typing outlet，foundation 无法校验这些字段是否应正式晋升为 shared canonical frontend contracts。

## Proposed Change
1. 在 frozen shared schema 空间中增加最小 user-business frontend contract baseline，建议位置：
   - `packages/common-schemas/frontend/user-business/*.schema.json`
   - 或 foundation 认可的等价 frozen frontend DTO 目录
2. 首批晋升字段建议与当前共享 SDK owned outlet 对齐：
   - 账单汇总 / 明细 / 发票
   - 订单 / 退款
   - 工单 / 回复
   - ICP 材料检查 / 申请详情
   - 文件上传策略 / 文件详情
   - citation detail
3. 在 `docs/contracts/shared/schema-catalog.md` 与 `docs/contracts/foundation-baseline.md` 中说明：
   - 这些 surfaces 已有共享前端消费方
   - 当前 `packages/frontend-sdk/src/web-user/business-contracts.ts` 是临时 owned typing outlet
   - 后续 foundation 应将其晋升为 frozen shared contract source of truth
4. 如相关服务 OpenAPI 已成熟，请同步补齐 `openapi/` 中对应 request/response 说明，避免前端长期依赖 owner-local typing。

## Impacted Consumers
- supervisor(s): `supervisor-frontend-sdk`, `supervisor-web-user`, `supervisor-foundation`
- service(s) or surface(s): `packages/frontend-sdk/`, `apps/web-user/`, future public/gateway user-facing frontend consumers
- required follow-up work:
  - foundation 评估并冻结 user-business frontend contract baseline
  - frontend-sdk 在 contract promotion 后将 owned typing outlet 收敛到 frozen shared exports
  - web-user 后续继续删除剩余 page-local payload assumptions

## Compatibility
- breaking or non-breaking: non-breaking additive change
- fallback or migration plan: 当前继续由 `packages/frontend-sdk/src/web-user/business-contracts.ts` 作为 owned frontend typing outlet，foundation promotion 完成后再切回 frozen shared contracts
- temporary workaround already in use:
  - `packages/frontend-sdk/src/web-user/business-contracts.ts`
  - `packages/frontend-sdk/src/web-user/business-types.ts`
  - `packages/frontend-sdk/src/web-user/business-mappers.ts`
  - `packages/frontend-sdk/src/web-user/business-api.ts`
  - `packages/frontend-sdk/src/core/envelope.ts`

## Evidence
- code reference(s):
  - `packages/frontend-sdk/src/web-user/business-contracts.ts`
  - `packages/frontend-sdk/src/web-user/business-mappers.ts`
  - `packages/frontend-sdk/src/web-user/business-api.ts`
  - `apps/web-user/src/api/services/billing.ts`
  - `apps/web-user/src/api/services/serviceDesk.ts`
  - `apps/web-user/src/api/services/files.ts`
  - `apps/web-user/src/api/services/citations.ts`
- mock/example/stub reference(s):
  - `apps/web-user/tests/mocks/user/billing/summary-success.json`
  - `apps/web-user/tests/mocks/user/orders/order-detail.json`
  - `apps/web-user/tests/mocks/user/tickets/detail-with-replies.json`
  - `apps/web-user/tests/mocks/user/icp/application-reviewing.json`
- log or validation reference(s):
  - `logs/supervisor-frontend-sdk/progress.log`
  - `docs/status/supervisor-frontend-sdk-status.md`

## Foundation Processing Result
- processed at: 2026-04-16
- decision: partially accepted; frontend-sdk may keep owned user-business typing outlets until the backing service contracts are promoted into frozen OpenAPI/common-schemas space
- implemented:
  - documented in `docs/contracts/foundation-baseline.md` and `docs/contracts/shared/schema-catalog.md` that foundation will not create `packages/common-schemas/frontend/**` while the underlying billing/order/refund/ticket/ICP/file/citation-detail contracts still live only in downstream-owned adapters or service-local payloads
  - recorded the request in foundation tracking artifacts and hardened validator checks so blank change-request result blocks fail readiness instead of silently passing
- deferred:
  - creation of `packages/common-schemas/frontend/user-business/*.schema.json`
  - publication of new frozen `openapi/` placeholders for billing, order/refund, ticket, ICP, file, and citation-detail flows before the owning service contracts are promoted through the normal frozen-space workflow
- rationale:
  - foundation freezes cross-service/backend contracts first; frontend-only mirrors of still owner-local business DTOs would duplicate unstable shapes and re-open drift in frozen space
  - `packages/frontend-sdk/` is the correct owned location for thin typed adapters during this phase, as long as those adapters continue aligning to the already-published frozen envelopes and service-level contracts
