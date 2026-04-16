# SmartCloud-X Web User API Integration Notes

## Scope
- owner: `supervisor-web-user`
- app: `apps/web-user`
- purpose: document current user-web integration baselines, mock/live behavior, and pending contracts

## Implemented frontend service modules
- `src/api/services/auth.ts`
  - `login`
  - `refresh`
  - `getCurrentUser`
  - `logout`
  - `sendCode`
  - `createPasswordResetChallenge`
  - `resetPassword`
- `src/api/services/chat.ts`
  - session list/create/detail/messages
  - rename/archive/restore/delete
  - cancel placeholder
  - retry adapter for `POST /api/v1/chat/sessions/{conversation_id}/retry`
  - SSE event mapping for both baseline and canonical spec event names
  - direct-open `/chat/:conversation_id` hydration now fetches session detail before messages and surfaces a route-level not-found empty state
- `src/stores/chat.ts`
  - app-local `conversationStore / messageStore / sseStore`
  - session/message cache separation for `/chat`
  - stream snapshot updates decoupled from page-local render state
  - SSE reconnect metadata (`reconnecting`, `reconnectAttempt`, `lastEventAt`) for the spec `20.15.1` 断流重连要求
- `src/api/services/billing.ts`
  - billing summary/details
  - invoice/order/ticket list aggregation
- `src/api/services/serviceDesk.ts`
  - order/refund/ticket workspace
  - order detail + refund detail adapters for `/api/v1/orders/{order_no}` and `/api/v1/refunds/{refund_no}`
  - ticket detail + reply adapters for `/api/v1/tickets/{ticket_no}` and `/api/v1/tickets/{ticket_no}/replies`
  - ICP material precheck and application submit
  - browser-local ICP application tracking for live mode
  - shared data source for `/service-desk`, `/tickets`, and `/icp`
- `src/api/services/research.ts`
  - create task
  - list placeholder for mock / future live list contract
- `src/api/services/marketing.ts`
  - campaigns
  - marketing copy generate
  - poster task create
  - poster history placeholder for mock / future live list contract
- `src/lib/request-meta.ts`
  - stable `X-Request-Id` helper
  - deterministic `Idempotency-Key` generation for repeated-submit-sensitive writes
- `src/lib/telemetry.ts`
  - app-local telemetry store for `page_view`, `login_submit`, `api_error`, `permission_denied`, and `chat_stream_*`
  - last-40 event persistence in browser storage for QA / integration debugging
- `src/api/services/user.ts`
  - current user/profile update/change password placeholders
- `src/api/services/files.ts`
  - upload policy / complete / fetch / delete placeholders
- `src/api/services/citations.ts`
  - citation detail placeholder
- `src/lib/task-registry.ts`
  - local registry for recently created research/poster tasks in live mode
- `src/config/env.ts`
  - merges build-time Vite env with optional `/runtime-config.js` overrides
  - exposes whether runtime overrides are active so the shell can surface deployment mode

## Auth/session behavior
- live mode enables silent refresh on `401` / `4010002`
- auth session changes are synchronized through `src/auth/session-manager.ts`
- protected routes wait for initial session bootstrap before redirecting to `/login`
- API client auto-populates `X-Client-Platform`, `X-Client-Version`, `X-Tenant-Id`, and `X-User-Id` from the local frontend/auth context to better match spec `20.5.3`
- runtime config can now be switched at container start via `/runtime-config.js`, so API gateway/base URL, title, version, mock mode, and timeout knobs no longer require rebuilding the image
- API client + live write services now also use stable `X-Request-Id` and deterministic `Idempotency-Key` values so double-click retries keep the spec `20.13.1/20.13.7` idempotency intent instead of generating a fresh random key every submit
- login page now covers password login, SMS/email verification login, and the spec `20.13.2` forgot-password challenge/reset flow under `/api/v1/auth/password/*`
- login page now rejects channel/account mismatches locally, so SMS code login only accepts mobile numbers and email code login only accepts email accounts before calling the live auth APIs
- mock auth now enforces the current local password baseline for both `/login` and `/users/me/change-password`, so password-change and password-reset UX can be exercised end-to-end before live auth integration is ready

## Chat event compatibility
The UI normalizes both event families into a single frontend event model:

- baseline/mock events:
  - `meta`
  - `reasoning`
  - `route`
  - `tool_call`
  - `tool_result`
  - `retrieval`
  - `delta`
  - `citation`
  - `done`
  - `error`
  - `ping`
- canonical spec events:
  - `message.started`
  - `agent.routed`
  - `tool.started`
  - `tool.finished`
  - `message.delta`
  - `citation.delta`
  - `message.completed`
  - `message.error`
  - `heartbeat`

Additional chat-page baseline notes:
- `/chat` now keeps conversation list, message cache, and SSE state in separate app-local stores to align better with spec `20.15.3`
- first-load session/message requests are skipped when the store already has fresh data, reducing duplicate fetches during route re-renders
- `/chat/:conversationId` now explicitly hydrates `GET /api/v1/chat/sessions/{conversation_id}` before rendering the detail view, so deep links outside the default session-list page still show the correct scene/status/agent metadata
- the page now exposes starter prompts for billing / technical / ICP / marketing entry flows so the user-facing baseline is immediately usable without memorizing example questions
- live/mock chat streams now attempt up to 3 automatic reconnects after abnormal disconnects; the UI resets the in-flight stream snapshot between retries to avoid duplicate deltas and surfaces reconnect status in-page

## Deployment/runtime config notes
- `index.html` now loads `/runtime-config.js` before the React entrypoint
- `apps/web-user/public/runtime-config.js` ships a safe empty default for local dev / plain static hosting
- the container image writes `/usr/share/nginx/html/runtime-config.js` from environment variables during Nginx startup via `docker-entrypoint.d/40-runtime-config.sh`
- nginx serves `/runtime-config.js` with `Cache-Control: no-store` so environment changes are reflected without a stale cached config blob

## Frontend telemetry notes
- route changes record `page_view`
- login form submissions record `login_submit`
- API client request/stream failures record `api_error`
- feature-guard denials record `permission_denied`
- chat send / finish / failure paths record `chat_stream_start`, `chat_stream_end`, and `chat_stream_error`
- the app shell surfaces the latest 40 locally stored events so QA can confirm spec `20.15.4` event coverage without waiting for a backend analytics sink

## Browser-validated flows
The owned Playwright suite now validates the following flows against the local mock API server:

1. login -> dashboard baseline
2. forgot-password send-code -> challenge -> reset -> sign in with the new password
3. chat send -> SSE disconnect once -> reconnect -> citation detail open
4. citation detail `403` permission error rendering
5. billing page `401` -> refresh token -> retry recovery
6. route-level permission denial UX for restricted marketing access
7. structured `429` marketing API error rendering
8. marketing copy generation + poster task creation
9. research task creation
10. `/orders` detail drawer + refund submission + refreshed refund history
11. `/profile` profile update + password rotation + forced re-login
12. focused `/tickets` creation flow
13. composite `/service-desk` upload separation + ticket + ICP flow
14. focused `/icp` upload-policy -> complete -> precheck -> submit flow
15. `/sessions` rename / archive / restore / delete lifecycle actions

## Baseline-only but not yet browser-covered
These owned surfaces remain implemented but are not yet directly covered by Playwright:

1. research report file preview via `/api/v1/files/{file_id}`
2. runtime-config container override behavior

## Known contract gaps
1. live list endpoints for research-task history and poster-task history are still pending; the frontend now falls back to locally tracked task IDs plus detail queries
2. ICP application history still lacks a canonical list endpoint in the primary spec, so live mode falls back to locally tracked `application_no` values plus detail queries
3. file upload and cancel flows still depend on backend delivery; retry now consumes the current session-level response but richer resume semantics are still backend-owned

## Primary integration surfaces
- auth: `/api/v1/auth/*`
- password recovery: `/api/v1/auth/password/forgot`, `/api/v1/auth/password/reset`
- chat: `/api/v1/chat/sessions*`, `/api/v1/chat/completions`
- billing: `/api/v1/billing/*`, `/api/v1/orders`, `/api/v1/tickets`
- service desk: `/api/v1/orders`, `/api/v1/refunds`, `/api/v1/tickets`, `/api/v1/orders/{order_no}`, `/api/v1/refunds/{refund_no}`, `/api/v1/orders/{order_no}/refunds`, `/api/v1/icp/materials/check`, `/api/v1/icp/applications`, `/api/v1/icp/applications/{application_no}`
- ticket detail/reply: `/api/v1/tickets/{ticket_no}`, `/api/v1/tickets/{ticket_no}/replies`
- marketing: `/api/v1/marketing/campaigns`, `/api/v1/marketing/posters*`
- research: `/api/v1/research/tasks*`, report preview via `/api/v1/files/{file_id}`
- files: `/api/v1/files/*`
- citations: `/api/v1/citations/{citation_id}`

## Frontend route mapping notes
- `/service-desk` is the comprehensive workspace for refunds, tickets, ICP, and upload-policy staging
- `/orders` is the focused order/refund route for spec-aligned detail-drawer and refund-submit flows
- `/tickets` is a focused wrapper around the shared service-desk state for spec-aligned ticket operations
- `/tickets` now includes list selection, detail timeline, and reply composer while reusing the shared attachment staging flow
- `/tickets` also accepts chat-escalation query params (`subject/content/category/priority/prefill_notice`) so the chat page can prefill a human-support draft with conversation/trace context
- `/icp` is a focused wrapper around the shared service-desk state for spec-aligned ICP operations
- shared upload staging now separates generic attachments from ICP materials and allows staged-file removal before submit, so ticket/refund evidence no longer gets mislabeled as ICP material by default
- dashboard and billing now degrade gracefully when only part of the live data contract is available

## Frontend fallbacks for partial live contracts
- research page:
  - create uses `POST /api/v1/research/tasks`
  - history fallback uses stored task IDs + `GET /api/v1/research/tasks/{task_id}`
- marketing page:
  - copy generator uses `POST /api/v1/marketing/copy/generate`
  - create uses `POST /api/v1/marketing/posters`
  - history fallback uses stored task IDs + `GET /api/v1/marketing/posters/{task_id}`
  - poster polling now auto-refreshes every 3s for up to 10 minutes, then stops and requires manual refresh to match the page-level spec constraint
- service desk pages:
  - orders/refunds/tickets use their canonical list endpoints directly in live mode
  - billing workspace now degrades partial live failures instead of blanking the full page when one downstream billing/order/ticket segment is unavailable
  - `/orders` prefers `GET /api/v1/orders/{order_no}` and `GET /api/v1/refunds/{refund_no}` for detail panels, but falls back to list data if those detail routes are not yet available
  - ticket detail/reply uses `GET /api/v1/tickets/{ticket_no}` + `POST /api/v1/tickets/{ticket_no}/replies`; mock mode seeds a reply timeline for local validation
  - ICP history fallback uses stored application IDs + `GET /api/v1/icp/applications/{application_no}`
  - attachment staging starts from `POST /api/v1/files/upload-policy`; the UI maps generic files to `chat_attachment` and ICP files to `icp_material`, and mock mode can simulate `POST /api/v1/files/complete` before attaching or removing staged files
- chat page:
  - citation drill-down uses `GET /api/v1/citations/{citation_id}`
  - retry uses `POST /api/v1/chat/sessions/{conversation_id}/retry` and refreshes the current exchange in place
  - direct-open detail routes now show a 404-style empty state when `GET /api/v1/chat/sessions/{conversation_id}` or the messages route returns not found, instead of falling through to a writable draft composer
  - conversation/message/SSE stores keep the route state separated so in-flight stream metadata survives normal page re-renders
  - the manual-assist card can deep-link into `/tickets` with prefilled conversation ID, trace ID, agent, and latest user intent
  - replayable SSE examples live under `apps/web-user/tests/mocks/user/chat/*.sse`, including an error-path sample
- additional user JSON fixtures for auth / billing / orders / tickets / icp / marketing / research live under `apps/web-user/tests/mocks/user/**/*.json`
- auth fixtures now also include send-code / password-forgot / password-reset success samples under `apps/web-user/tests/mocks/user/auth/`
- research page:
  - completed tasks can fetch export metadata via `GET /api/v1/files/{file_id}`
