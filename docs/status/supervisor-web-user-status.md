# Supervisor Web User Status

## Status
- phase: runtime-config-browser-validated
- updated_at: 2026-04-16T22:44:02+08:00
- summary: `apps/web-user` now browser-validates runtime-config overrides, starts fresh Playwright servers by default, and passes 18 end-to-end tests on the normal owned test command

## Completed This Run
- added a Playwright runtime-config helper plus a new browser spec that proves `/runtime-config.js` overrides title, version, API base URL, and SSE heartbeat across login and the authenticated app shell
- changed `apps/web-user/playwright.config.ts` so fresh mock/API dev servers are the default for `npm run test:e2e`; explicit reuse now requires `PLAYWRIGHT_REUSE_SERVER=1`
- updated owned README and API integration notes so browser-validated versus baseline-only coverage now includes runtime-config consumption and documents the new Playwright runner behavior
- performed self-review on the new browser-validation pass, found false failures caused by stale reused Playwright servers, and fixed the harness instead of weakening the E2E assertions

## Browser-validated
- login -> dashboard
- forgot-password send-code -> challenge -> reset -> sign in
- chat send -> SSE disconnect once -> reconnect -> citation detail
- citation detail `403`
- chat retry -> assist-ticket prefill -> ticket creation
- billing `401` -> refresh -> retry recovery
- route permission denial UX
- structured `429` API error rendering
- marketing copy generation + poster creation
- poster/research history reload after clearing browser task registry
- runtime `/runtime-config.js` override rendering in login + shell
- research task creation
- research report preview via `/api/v1/files/{file_id}`
- research report file-missing error rendering
- `/orders` detail + refund creation/history refresh
- `/profile` profile update + password rotation + forced re-login
- focused `/tickets` creation
- composite `/service-desk` attachment separation + ticket + ICP flow
- focused `/icp` upload-policy -> complete -> precheck -> submit
- `/sessions` rename / archive / restore / delete lifecycle

## Validation
- `npm run test:e2e`
  - result: 18 tests passed
- `npm run build`
  - result: blocked by non-owned `packages/frontend-sdk/src/core/error-codes.ts` because `CHAT_STREAM_EVENTS_NOT_FOUND` is missing from the shared error-code record

## Remaining Gaps
- Docker / Nginx entrypoint generation of `runtime-config.js` is still smoke-validated rather than Playwright-validated
- ICP application history still lacks a canonical list endpoint, so live mode still falls back to browser-local tracked `application_no` values plus detail reads
- live attachment staging still depends on backend file upload + complete semantics outside `apps/web-user`
- repo-wide build/typecheck for `apps/web-user` is currently blocked by non-owned `packages/frontend-sdk` changes

## Integration Points
- `/runtime-config.js`
- auth/account: `/api/v1/auth/*`, `/api/v1/users/me`, `/api/v1/users/me/change-password`
- chat/session: `/api/v1/chat/sessions*`, `/api/v1/chat/completions`, `/api/v1/citations/{citation_id}`
- orders/refunds/tickets: `/api/v1/orders*`, `/api/v1/refunds*`, `/api/v1/tickets*`
- ICP/files: `/api/v1/icp/materials/check`, `/api/v1/icp/applications*`, `/api/v1/files/*`
- marketing: `/api/v1/marketing/campaigns`, `/api/v1/marketing/copy/generate`, `/api/v1/marketing/posters*`
- research: `/api/v1/research/tasks*`
