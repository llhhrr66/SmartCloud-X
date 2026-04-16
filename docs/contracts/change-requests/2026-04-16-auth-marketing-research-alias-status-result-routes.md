# Change Request

## Summary
- requester: supervisor-auth-marketing-research
- date: 2026-04-16
- affected frozen path: `openapi/auth-user-service.openapi.yaml`, `openapi/research-service.openapi.yaml`, `openapi/marketing-service.openapi.yaml`, `packages/common-schemas/src/schemas/external/user/`
- blocking: no

## Background
The owned auth, research, and marketing services now expose practical compatibility/helper routes that make the current user mission easier to integrate without changing the already-frozen primary polling/detail surfaces.

## Current Gap
The frozen contract does not yet publish these additive routes:
- `POST /api/v1/auth/forgot-password`
- `POST /api/v1/auth/reset-password`
- `GET/PATCH /api/v1/auth/profile`
- `POST /api/v1/auth/change-password`
- `GET /api/v1/research/tasks/{task_id}/status`
- `GET /api/v1/research/tasks/{task_id}/result`
- `GET /api/v1/marketing/posters/{task_id}/result`

The frozen contract also lacks reusable DTOs for the additive research-result, research-status, and poster-result payloads currently served by the owned services.

## Proposed Change
Promote additive compatibility coverage for:
1. auth aliases that normalize mission wording (`forgot-password`, `reset-password`, `profile`, `change-password`) onto the existing auth/account baseline
2. research helper routes for task status polling and placeholder result/report retrieval
3. marketing helper route for poster-result retrieval
4. shared external DTO placeholders for:
   - `ResearchTaskStatusData`
   - `ResearchTaskResultData`
   - `PosterResultData`

## Impacted Consumers
- supervisor(s): supervisor-auth-marketing-research, supervisor-web-user
- service(s) or surface(s): `apps/auth-user-service/`, `apps/research-service/`, `apps/marketing-service/`, `apps/web-user/`
- required follow-up work:
  - foundation decides whether these helper routes should become documented public contract or remain owner-local compatibility aliases
  - if promoted, downstream consumers can stop treating them as app-local convenience routes

## Compatibility
- breaking or non-breaking: non-breaking additive promotion
- fallback or migration plan: existing frozen routes remain the primary contract; the new routes are owner-local additive helpers today
- temporary workaround already in use: the owned services already serve these routes with canonical external envelopes while marking them as non-schema aliases inside app code

## Evidence
- code reference(s):
  - `apps/auth-user-service/app/routes.py`
  - `apps/research-service/app/routes.py`
  - `apps/research-service/app/models.py`
  - `apps/marketing-service/app/routes.py`
  - `apps/marketing-service/app/models.py`
- test reference(s):
  - `apps/auth-user-service/tests/test_auth_api.py`
  - `apps/research-service/tests/test_research_api.py`
  - `apps/marketing-service/tests/test_marketing_api.py`

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - published additive auth compatibility aliases for `/api/v1/auth/forgot-password`, `/api/v1/auth/reset-password`, `/api/v1/auth/profile`, and `/api/v1/auth/change-password` in `openapi/auth-user-service.openapi.yaml`
  - published additive research/marketing helper routes for `/api/v1/research/tasks/{task_id}/status`, `/api/v1/research/tasks/{task_id}/result`, and `/api/v1/marketing/posters/{task_id}/result`
  - added shared placeholder DTOs for `ResearchTaskStatusData`, `ResearchTaskResultData`, and `PosterResultData`, then wired them into the shared schema registry, OpenAPI component refs, and foundation documentation/validation
