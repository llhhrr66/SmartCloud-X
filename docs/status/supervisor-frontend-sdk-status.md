# Supervisor Frontend SDK Status

## Status
- phase: shared-status-catalog-and-page-metadata-tightening-self-reviewed
- updated at: 2026-04-17T00:16:19+08:00
- owned scope: `packages/frontend-sdk/`
- pending before final signoff: no active owned-path blocker; remaining follow-up is frozen user-business / ICP-list contract promotion, frozen stream-event replay route/OpenAPI promotion, plus later workspace-package import cleanup outside this run

## Completed
- tightened [business-mappers.ts](/home/ljr/SmartCloud-X/packages/frontend-sdk/src/web-user/business-mappers.ts) so shared billing / order / ticket / ICP page adapters now infer deterministic `totalPages` from `total` plus `page_size` and normalize uppercase or mixed-case `sortOrder` metadata at the SDK boundary instead of leaving that cleanup to thin app consumers
- expanded [business-constants.ts](/home/ljr/SmartCloud-X/packages/frontend-sdk/src/web-user/business-constants.ts) with shared known status catalogs and guards for ticket, refund, ICP application, file lifecycle, and file scan surfaces, completing the reusable enum outlet for the currently adopted billing / order / ticket / ICP / file frontend domains
- minimally aligned [domain.ts](/home/ljr/SmartCloud-X/apps/web-user/src/types/domain.ts) so the thin web-user shim now re-exports the added shared business type aliases (`BillingSummaryRange`, `TicketCategory`, `IcpMaterialType`, `FileLifecycleStatus`, `FileScanStatus`) instead of leaving those route-facing types reachable only through direct SDK imports
- added stronger shared validation in [core-http.test.js](/home/ljr/SmartCloud-X/packages/frontend-sdk/tests/core-http.test.js), [web-user-business-api.test.js](/home/ljr/SmartCloud-X/packages/frontend-sdk/tests/web-user-business-api.test.js), and [web-user-business-fallbacks.test.js](/home/ljr/SmartCloud-X/packages/frontend-sdk/tests/web-user-business-fallbacks.test.js) for structured text/event-stream request-id fallback, inferred page counts, normalized sort-order casing, and the expanded shared business-status catalog

## Self-review
- completed on 2026-04-17
- fixes made during review:
  - no additional defect was found during the post-validation diff review; the tightened mapper/catalog behavior matched the passing validation set, so no follow-up code patch was required after the review pass

## Validation
- `./apps/web-user/node_modules/typescript/bin/tsc -p packages/frontend-sdk/tsconfig.runtime.json`
- `node --test packages/frontend-sdk/tests/core-http.test.js`
- `node --test packages/frontend-sdk/tests/core-envelope.test.js`
- `node --test packages/frontend-sdk/tests/core-sse.test.js`
- `node --test packages/frontend-sdk/tests/web-user-business-api.test.js`
- `node --test packages/frontend-sdk/tests/web-user-business-fallbacks.test.js`
- `./apps/web-user/node_modules/typescript/bin/tsc -p apps/web-user/tsconfig.json --noEmit`

## Blockers / Risks
- no active blocker remains in owned paths after this run
- billing / order / ticket / ICP / file / citation-detail still live in the owned frontend-sdk contract outlet; frozen shared frontend contract promotion remains tracked in [2026-04-16-frontend-sdk-user-business-contract-promotion.md](/home/ljr/SmartCloud-X/docs/contracts/change-requests/2026-04-16-frontend-sdk-user-business-contract-promotion.md)
- the primary spec/openapi/catalog still do not freeze a canonical ICP application list contract for `GET /api/v1/icp/applications`; that gap is tracked in [2026-04-16-frontend-sdk-icp-application-list-contract-promotion.md](/home/ljr/SmartCloud-X/docs/contracts/change-requests/2026-04-16-frontend-sdk-icp-application-list-contract-promotion.md), so the shared SDK still owns the ICP page/fallback outlet
- live orchestrator message-event list/replay routes still matter to shared frontend consumption, but the route-level `CHAT_STREAM_EVENTS_NOT_FOUND` replay contract is still not frozen in `openapi/`; that remaining gap is tracked in [2026-04-16-frontend-sdk-chat-stream-events-not-found-promotion.md](/home/ljr/SmartCloud-X/docs/contracts/change-requests/2026-04-16-frontend-sdk-chat-stream-events-not-found-promotion.md)
- apps still consume the SDK through thin local shims; that is usable now, but a formal workspace package-consumption convention remains a later cleanup item

## Integration Points
- [business-mappers.ts](/home/ljr/SmartCloud-X/packages/frontend-sdk/src/web-user/business-mappers.ts) now emits normalized page metadata for shared list surfaces, so billing / ticket / ICP consumers receive stable `totalPages` and lowercase `sortOrder` without app-local recomputation or casing guards
- [business-constants.ts](/home/ljr/SmartCloud-X/packages/frontend-sdk/src/web-user/business-constants.ts) now gives thin app callers one shared source for ticket/refund/ICP/file status vocabularies in addition to the earlier billing-summary, ticket-priority/category, ICP-material, and upload-biz catalogs
- [domain.ts](/home/ljr/SmartCloud-X/apps/web-user/src/types/domain.ts) now re-exports the shared business type aliases needed by thin web-user code that wants to stay on the local shim instead of importing those types from the package path directly
- [core-http.test.js](/home/ljr/SmartCloud-X/packages/frontend-sdk/tests/core-http.test.js) now validates structured text/event-stream error bodies that omit `request_id`, keeping the shared HTTP client’s request-correlation story aligned across JSON and SSE-shaped failures
