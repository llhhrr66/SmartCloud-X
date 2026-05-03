# Supervisor Web User Status

## Status
- phase: live-first-product-front-rebuilt
- updated_at: 2026-04-17T20:09:55+08:00
- summary: `apps/web-user` has been rebuilt into a live-first Chinese user frontend with a new top shell, explicit runtime/live health signaling, a workspace-style dashboard, refreshed visual hierarchy across the user surfaces, updated browser assertions, and green `build` + 18 owned Playwright flows

## Completed This Run
- fixed `src/lib/runtime-health.ts` so the live gateway probe now reuses the stored auth session token; authenticated shells no longer downgrade to `待登录` just because `/api/v1/auth/me` is protected
- scoped Playwright port cache files to a single run id via `SC_PLAYWRIGHT_PORT_CACHE_ID`, so overlapping or previously hung local browser runs no longer deterministically reuse the same cached port pair
- rebuilt the authenticated shell into a top-level product shell with explicit live/mock badges, runtime-config source, live gateway probe, current user identity, global navigation, permission boundary summary, and a secondary telemetry inspector
- added `src/lib/runtime-health.ts` so login and authenticated pages can actively distinguish `reachable / auth_required / contract_gap / server_error / unreachable` instead of only echoing env flags
- redesigned the dashboard into a live-first entry workspace that tells testers who they are, what they can do next, where fallback still exists, and which routes remain permission-gated
- refreshed the global CSS system, page headers, login hero, workspace tiles, and shell hierarchy so the frontend reads like a real user-facing product rather than a baseline developer UI
- normalized remaining English or baseline wording in profile / research / marketing / ICP paths to stronger Chinese product copy, while keeping field labels and owned behaviors testable
- updated Playwright assertions for the rebuilt runtime shell and localized status badges, then re-ran the full owned browser suite to confirm no coverage regression
- stabilized `apps/web-user/playwright.config.ts` for Windows/local reuse drift by adding a per-run shared port cache, real ready-log waiting, `webServer.env` injection, and worker-safe URL resolution for browser helpers
- added a small Node test for Playwright port selection so the port/runtime fix has a fast RED->GREEN regression guard outside the full browser suite
- made `/icp` and `/service-desk` surface a dedicated `浏览器跟踪回填` badge plus an in-page warning banner whenever ICP history is coming from browser-tracked application numbers instead of a canonical live list endpoint
- extended the existing focused ICP browser flow so the fallback provenance is asserted in Playwright instead of only being mentioned in docs
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
- focused `/icp` upload-policy -> complete -> precheck -> submit + explicit browser-tracked fallback provenance
- `/sessions` rename / archive / restore / delete lifecycle

## Validation
- `node --test apps/web-user/tests/e2e/port-utils.test.mjs`
  - result: passed
- `npm run test:e2e`
  - result: 18 tests passed
  - note: after the product-shell refactor, updated localized assertions and re-ran the full owned browser suite end-to-end
- `npm run build`
  - result: passed

## Remaining Gaps
- Docker / Nginx entrypoint generation of `runtime-config.js` is still smoke-validated rather than Playwright-validated
- ICP application history still lacks a canonical list endpoint, so live mode continues to fall back to browser-local tracked `application_no` values plus detail reads; the UI now states this explicitly instead of implying a full live list
- live attachment staging still depends on backend file upload + complete semantics outside `apps/web-user`

## Integration Points
- `/runtime-config.js`
- auth/account: `/api/v1/auth/*`, `/api/v1/users/me`, `/api/v1/users/me/change-password`
- chat/session: `/api/v1/chat/sessions*`, `/api/v1/chat/completions`, `/api/v1/citations/{citation_id}`
- orders/refunds/tickets: `/api/v1/orders*`, `/api/v1/refunds*`, `/api/v1/tickets*`
- ICP/files: `/api/v1/icp/materials/check`, `/api/v1/icp/applications*`, `/api/v1/files/*`
- marketing: `/api/v1/marketing/campaigns`, `/api/v1/marketing/copy/generate`, `/api/v1/marketing/posters*`
- research: `/api/v1/research/tasks*`
