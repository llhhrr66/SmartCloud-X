# Change Request

## Summary
- requester: supervisor-auth-marketing-research
- date: 2026-04-16
- affected frozen path: `openapi/marketing-service.openapi.yaml`, `packages/common-schemas/src/schemas/external/user/`
- blocking: no

## Background
The owned `apps/marketing-service/` baseline now implements the user-facing marketing routes required by the current mission. The frozen placeholder OpenAPI already covers campaign listing and poster task history/detail, but it still lacks the two other practical marketing capabilities needed by the current owned service and web-user integration path.

## Current Gap
The frozen contract does not yet publish:
- `POST /api/v1/marketing/copy/generate`
- `POST /api/v1/marketing/promotion-links/generate`

It also does not publish reusable response/request DTOs for generated marketing copy or placeholder promotion-link payloads.

## Proposed Change
Promote additive user-facing contract coverage for:
1. `POST /api/v1/marketing/copy/generate`
   - request: `campaign_id`, `topic`, `audience`, `tone`, `keywords[]`
   - response baseline: `copy_id`, `campaign_id`, `campaign_name`, `topic`, `audience`, `tone`, `headline`, `summary`, `body`, `call_to_action`, `keywords[]`, optional `landing_page_url`, `created_at`
2. `POST /api/v1/marketing/promotion-links/generate`
   - request: `campaign_id`, `channel`, optional `source`, optional `content_tag`
   - response baseline: `link_id`, `campaign_id`, `campaign_name`, `channel`, `short_url`, `landing_page_url`, `tracking_code`, `created_at`, `note`

The change is additive and should keep the existing campaign/poster placeholder coverage untouched.

## Impacted Consumers
- supervisor(s): supervisor-auth-marketing-research, supervisor-web-user
- service(s) or surface(s): `apps/marketing-service/`, `apps/web-user/`
- required follow-up work:
  - foundation promotes the missing OpenAPI + shared external DTO placeholders
  - downstream consumers can then depend on the routes without app-local-only assumptions

## Compatibility
- breaking or non-breaking: non-breaking additive promotion
- fallback or migration plan: keep the owned app-local implementation as the live baseline until frozen OpenAPI/common-schema promotion lands
- temporary workaround already in use: `apps/marketing-service/` already serves both routes with canonical external envelopes and app-local DTOs

## Evidence
- code reference(s):
  - `apps/marketing-service/app/routes.py`
  - `apps/marketing-service/app/models.py`
  - `apps/marketing-service/app/store.py`
- mock/example/stub reference(s):
  - `apps/web-user/src/api/services/marketing.ts`
  - `apps/web-user/src/types/domain.ts`
- log or failing validation reference(s):
  - no validator failure in owned scope; the gap is a frozen-contract omission discovered while implementing the required marketing baseline

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - added reusable external user schemas for `MarketingCopyRequest`, `MarketingCopyResult`, `PromotionLinkRequest`, and `PromotionLinkResult` in `packages/common-schemas`
  - promoted `POST /api/v1/marketing/copy/generate` and `POST /api/v1/marketing/promotion-links/generate` into `openapi/marketing-service.openapi.yaml` with canonical external envelopes
  - refreshed shared README/contract summaries and foundation validation so the new marketing contract roots and route baselines cannot silently regress
