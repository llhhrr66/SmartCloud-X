# Change Request

## Summary
- requester: supervisor-auth-marketing-research
- date: 2026-04-16
- affected frozen path: `openapi/marketing-service.openapi.yaml`, `packages/common-schemas/src/schemas/external/user/`
- blocking: no

## Background
The owned `apps/marketing-service/` baseline already persists generated marketing copy and promotion-link artifacts, but the frozen contract still treats those flows as write-only. That makes downstream apps depend on local browser storage or immediate POST responses instead of being able to read back generated artifacts from the service.

## Current Gap
The frozen contract does not yet publish read routes for generated marketing artifacts:
- `GET /api/v1/marketing/copies`
- `GET /api/v1/marketing/copies/{copy_id}`
- `GET /api/v1/marketing/promotion-links`
- `GET /api/v1/marketing/promotion-links/{link_id}`

It also lacks reusable list DTO placeholders for paged marketing-copy history and promotion-link history responses.

## Proposed Change
Promote additive user-facing contract coverage for:
1. generated marketing copy history/detail retrieval
2. generated promotion-link history/detail retrieval
3. reusable external DTO placeholders for:
   - `MarketingCopyListData`
   - `PromotionLinkListData`

Suggested baseline behavior:
- reads stay scoped to authenticated `(tenant_id, user_id)`
- list routes use the canonical external envelope with `items`, `page`, `page_size`, `total`, `total_pages`, `sort_by`, and `sort_order`
- detail routes return the same artifact shapes currently returned by `copy/generate` and `promotion-links/generate`

## Impacted Consumers
- supervisor(s): supervisor-auth-marketing-research, supervisor-web-user
- service(s) or surface(s): `apps/marketing-service/`, `apps/web-user/`
- required follow-up work:
  - foundation decides whether these additive routes should become documented public contract or remain owner-local convenience reads
  - if promoted, downstream clients can stop treating generated copy/promotion-link history as app-local only

## Compatibility
- breaking or non-breaking: non-breaking additive promotion
- fallback or migration plan: current write routes remain unchanged; the owned app now serves the new read routes as additive helpers
- temporary workaround already in use: downstream apps can keep using immediate POST responses or browser-local task registries until the read routes are promoted

## Evidence
- code reference(s):
  - `apps/marketing-service/app/routes.py`
  - `apps/marketing-service/app/models.py`
  - `apps/marketing-service/app/store.py`
- test reference(s):
  - `apps/marketing-service/tests/test_marketing_api.py`

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - added reusable external user schemas for `MarketingCopyListData` and `PromotionLinkListData`, plus shared package exports/registry entries for the new history DTOs
  - promoted `GET /api/v1/marketing/copies`, `GET /api/v1/marketing/copies/{copy_id}`, `GET /api/v1/marketing/promotion-links`, and `GET /api/v1/marketing/promotion-links/{link_id}` into `openapi/marketing-service.openapi.yaml` with canonical external envelopes
  - refreshed shared contract summaries and foundation validation so the new marketing artifact-history routes, DTOs, and change-request record cannot silently regress
