# Change Request

## Summary
- requester: supervisor-integration-qa
- date: 2026-04-16
- affected frozen path: `packages/common-schemas/src/schemas/external/auth/auth-user-profile.schema.json`, related TypeScript exports, and `openapi/auth-user-service.openapi.yaml`
- blocking: no

## Background
The project-level QA baseline validates live auth responses against the frozen auth OpenAPI/common-schema contract. During that validation, the current demo-user success responses from `auth-user-service` returned `avatar_url: null`.

## Current Gap
The frozen `AuthUserProfile` schema currently defines:
- `avatar_url` as `type: string`
- no nullable variant

That conflicts with the live baseline response shape for the demo user, where `avatar_url` is present but null on:
- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`

## Proposed Change
Promote additive nullability alignment for `avatar_url` on the frozen auth user profile contract:
1. allow `avatar_url` to be omitted or null when no avatar is configured
2. align the shared TypeScript type export and OpenAPI examples accordingly
3. document that non-empty strings remain the expected populated value when an avatar exists

## Impacted Consumers
- supervisor(s): supervisor-auth-marketing-research, supervisor-foundation, supervisor-integration-qa
- service(s) or surface(s): auth-user-service, frontend-sdk auth DTO consumers, web-user auth/profile consumers, QA contract validation
- required follow-up work: foundation promotion into frozen schema/OpenAPI/types

## Compatibility
- breaking or non-breaking: non-breaking additive
- fallback or migration plan: consumers may continue treating `avatar_url` as optional until the frozen schema is updated
- temporary workaround already in use: QA baseline records this as a documented contract drift and skips hard-failing only on the affected auth success responses

## Evidence
- code reference(s):
  - `apps/auth-user-service/app/main.py`
  - `apps/auth-user-service/app/routes.py`
  - `packages/common-schemas/src/schemas/external/auth/auth-user-profile.schema.json`
- mock/example/stub reference(s):
  - `tests/integration/test_auth_marketing_research_flow.py`
  - `scripts/qa/project_smoke.py`
- log or failing validation reference(s):
  - live contract validation failed with `data.user.avatar_url: None is not of type 'string'`

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - updated the shared `AuthUserProfile` schema/type so `avatar_url` may be omitted or explicitly `null` when no avatar is configured
  - aligned auth OpenAPI examples and shared auth-contract/foundation documentation with the nullable avatar baseline while keeping non-empty strings as the populated value contract
  - added validator coverage for the processed change request and the promoted nullable `avatar_url` field
