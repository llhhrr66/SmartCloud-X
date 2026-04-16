# Change Request

## Summary
- requester: supervisor-frontend-sdk
- date: 2026-04-16
- affected frozen path: `docs/contracts/shared/schema-catalog.md`, `docs/contracts/foundation-baseline.md`, `openapi/`, `packages/common-schemas/`
- blocking: no

## Background
`packages/frontend-sdk/` now prefers a live ICP history path for web-user by calling `GET /api/v1/icp/applications?page=...&page_size=...` and only falls back to locally tracked `application_no` detail fetches when the list endpoint is missing or lagging.

That improves real-backend adoption, but the current frozen spec/catalog still does not publish a canonical ICP application list request/response contract or pagination semantics. The shared SDK therefore keeps an owned interim outlet for:

1. ICP list page query typing
2. ICP list page envelope/list aliases
3. fallback metadata that distinguishes hard failure from tracked-detail fallback

## Current Gap
1. `docs/contracts/shared/schema-catalog.md` and the current frozen OpenAPI set do not define a canonical list contract for `GET /api/v1/icp/applications`.
2. Frontend consumers cannot rely on a frozen shared DTO/page schema for ICP history pagination or list envelopes.
3. The shared SDK must currently infer/own the ICP list page shape even though it is now part of the live frontend adapter path.

## Proposed Change
1. Promote a frozen ICP application list baseline covering:
   - `GET /api/v1/icp/applications`
   - page query parameters (`page`, `page_size`)
   - canonical list/page envelope shape
   - stable ICP application item fields reused by detail/list surfaces
2. Record in frozen contract docs that frontend consumers may prefer the list route and only use local tracked-detail fallback as a temporary compatibility path.
3. Once promoted, allow `packages/frontend-sdk/` to collapse its owned ICP list page typing onto the frozen shared exports.

## Impacted Consumers
- supervisor(s): `supervisor-frontend-sdk`, `supervisor-web-user`, `supervisor-foundation`
- service(s) or surface(s): `packages/frontend-sdk/`, `apps/web-user/`, future user-facing frontend consumers of ICP history
- required follow-up work:
  - foundation freezes the ICP list route contract and pagination semantics
  - frontend-sdk removes or narrows the owned ICP list typing outlet after frozen promotion

## Compatibility
- breaking or non-breaking: non-breaking additive change
- fallback or migration plan: shared SDK continues using its owned ICP list page contract plus tracked-detail fallback until frozen promotion lands
- temporary workaround already in use:
  - `packages/frontend-sdk/src/web-user/business-contracts.ts`
  - `packages/frontend-sdk/src/web-user/business-mappers.ts`
  - `packages/frontend-sdk/src/web-user/business-api.ts`
  - `apps/web-user/src/pages/ServiceDeskPage.tsx`

## Evidence
- code reference(s):
  - `packages/frontend-sdk/src/web-user/business-contracts.ts`
  - `packages/frontend-sdk/src/web-user/business-mappers.ts`
  - `packages/frontend-sdk/src/web-user/business-api.ts`
  - `packages/frontend-sdk/tests/web-user-business-api.test.js`
- log or validation reference(s):
  - `logs/supervisor-frontend-sdk/progress.log`
  - `docs/status/supervisor-frontend-sdk-status.md`

## Foundation Processing Result
- processed at: 2026-04-16
- decision: partially accepted; the defer is now explicit and route-specific
- implemented:
  - documented in `docs/contracts/foundation-baseline.md` and `docs/contracts/shared/schema-catalog.md` that the current defer on frontend-owned user-business DTOs still applies specifically to the SDK-owned `GET /api/v1/icp/applications` list contract
  - recorded the request in foundation tracking artifacts so future owner promotion of the backing ICP service contract can adopt this request instead of rediscovering the gap
- deferred:
  - no frozen `packages/common-schemas` DTO or `openapi/` placeholder was created for `GET /api/v1/icp/applications`
- rationale:
  - the current route shape exists only in frontend-owned adapters and documentation, not in a backend-owned frozen service contract, so freezing it now would duplicate an unstable owner-local shape inside foundation
