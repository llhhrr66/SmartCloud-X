# Supervisor Frontend SDK Status

## Status
- phase: done
- updated at: 2026-04-16T15:24:27+08:00
- owned scope: `packages/frontend-sdk/`

## Completed
- tightened `packages/frontend-sdk/` further with:
  - a shared `consumeSseStreamWithReconnect(...)` helper in `packages/frontend-sdk/src/core/sse.ts` so frontend stream consumers share reconnect gating, backoff calculation, graceful-close reconnect handling, and structured final disconnect errors
  - stronger shared validation for stream retry behavior in `packages/frontend-sdk/tests/core-sse.test.js`, covering retryable network failures, graceful closes, structured `429` delay handling, and explicit no-retry unauthorized failures
  - stricter owned frontend typing aliases in `packages/frontend-sdk/src/web-user/business-types.ts` for billing/order/refund/ticket list surfaces (`BillingDetailPage`, `InvoiceRecordPage`, `OrderRecordPage`, `RefundRecordPage`, `TicketRecordPage`, plus `OrderListQuery` / `RefundListQuery` / `TicketListQuery`)
- minimal app adoption for this run:
  - `apps/web-user/src/pages/ChatPage.tsx` now consumes the shared SSE reconnect helper instead of owning the reconnect loop directly
  - `apps/web-user/src/types/domain.ts` now re-exports the stricter shared business page aliases

## Self-review
- completed on 2026-04-16
- fixes made during review:
  - removed an unused page-local reconnect variable left behind after the shared helper replaced the ChatPage-local retry loop
  - reran the shared/runtime/app validation set after the cleanup to confirm no regression in the web-user integration

## Validation
- `./apps/web-user/node_modules/typescript/bin/tsc -p packages/frontend-sdk/tsconfig.runtime.json`
- `./apps/web-user/node_modules/typescript/bin/tsc -p apps/web-user/tsconfig.json --noEmit`
- `./apps/web-admin/node_modules/typescript/bin/tsc -p apps/web-admin/tsconfig.json --noEmit`
- `node --test packages/frontend-sdk/tests/core-envelope.test.js packages/frontend-sdk/tests/core-http.test.js packages/frontend-sdk/tests/core-sse.test.js packages/frontend-sdk/tests/web-user-business-api.test.js packages/frontend-sdk/tests/web-admin-api.test.js packages/frontend-sdk/tests/web-user-session.test.js packages/frontend-sdk/tests/web-user-mappers.test.js`
- `npm run build` in `apps/web-user`
- `npm run build` in `apps/web-admin`

## Blockers / Risks
- no active blocker remains in owned paths
- billing/order/ticket/ICP/file/citation-detail still live in an owned frontend-sdk contract outlet; frozen shared frontend contract promotion remains tracked in `docs/contracts/change-requests/2026-04-16-frontend-sdk-user-business-contract-promotion.md`
- `packages/common-schemas/src/index.ts` still exports an incomplete frozen error-code list versus `packages/common-schemas/errors/error_codes.yaml`; frontend-sdk keeps an owned supplement until `docs/contracts/change-requests/2026-04-16-frontend-sdk-foundation-error-code-export-alignment.md` is processed
- apps still consume the SDK through thin local shims; that is usable now, but a formal workspace package-consumption convention remains a later cleanup item

## Integration Points
- `packages/frontend-sdk/src/core/sse.ts` is now the shared reconnect/control-flow layer for frontend async stream consumers
- `apps/web-user/src/pages/ChatPage.tsx` plugs store updates and telemetry into that shared reconnect helper through a minimal callback adapter
- `packages/frontend-sdk/src/web-user/business-types.ts` now publishes surface-specific billing/order/refund/ticket page aliases for stricter shared reuse
- `apps/web-user/src/types/domain.ts` re-exports those stricter shared page aliases alongside the rest of the shared SDK surface
