# Change Request

## Summary
- requester: supervisor-frontend-sdk
- date: 2026-04-16
- affected frozen path: `packages/common-schemas/errors/error_codes.yaml`, `packages/common-schemas/src/index.ts`, `openapi/orchestrator-service.openapi.yaml`
- blocking: no

## Background
`packages/frontend-sdk/` now owns the shared frontend transport/error layer for web-user and web-admin. During stricter SSE/reconnect alignment, the SDK had to classify the live orchestrator replay/list miss code `CHAT_STREAM_EVENTS_NOT_FOUND` so frontend chat replay and reconnect flows stop treating that case as retryable transport failure.

The current live orchestrator implementation already returns `HTTP 404` with `detail.code = "CHAT_STREAM_EVENTS_NOT_FOUND"` from:

1. `GET /chat/sessions/{conversation_id}/messages/{message_id}/events`
2. `GET /chat/sessions/{conversation_id}/messages/{message_id}/events/stream`

but that route/code pair is still absent from frozen OpenAPI and the frozen foundation error-code catalog.

## Current Gap
1. `packages/common-schemas/errors/error_codes.yaml` and `packages/common-schemas/src/index.ts` do not include `CHAT_STREAM_EVENTS_NOT_FOUND`.
2. `openapi/orchestrator-service.openapi.yaml` does not currently describe the message-event list/replay routes or their `404` replay-miss code.
3. Shared frontend consumers therefore cannot stay fully frozen-contract-aligned for this live backend error and must keep a narrow owned supplement in `packages/frontend-sdk/`.

## Proposed Change
1. Add `CHAT_STREAM_EVENTS_NOT_FOUND` to the frozen foundation error-code catalog with canonical `status=404` / not-found semantics.
2. Document the two message-event list/replay routes in `openapi/orchestrator-service.openapi.yaml`, including their `404` error response.
3. If foundation prefers a different canonical public code for this replay-miss case, document the replacement and the deprecation path for `CHAT_STREAM_EVENTS_NOT_FOUND` so shared frontend adapters can remove the owned supplement cleanly.

## Impacted Consumers
- supervisor(s): `supervisor-frontend-sdk`, `supervisor-orchestrator`, `supervisor-foundation`, `supervisor-web-user`
- service(s) or surface(s): `packages/frontend-sdk/`, `apps/web-user/` chat replay and SSE reconnect flows, future shared chat/event consumers
- required follow-up work:
  - foundation freezes the route/error contract
  - frontend-sdk removes the owned supplemental code after frozen promotion
  - web-user can rely entirely on shared not-found classification instead of route-specific error literals

## Compatibility
- breaking or non-breaking: non-breaking additive change
- fallback or migration plan: `packages/frontend-sdk/` currently carries `CHAT_STREAM_EVENTS_NOT_FOUND` as an owned supplemental shared error code and classifies it as `not_found` / non-retryable for SSE helpers
- temporary workaround already in use:
  - `packages/frontend-sdk/src/core/error-codes.ts`
  - `packages/frontend-sdk/src/core/envelope.ts`
  - `apps/web-user/src/pages/ChatPage.tsx`

## Evidence
- code reference(s):
  - `apps/orchestrator-service/app/api/routes/orchestration.py`
  - `packages/frontend-sdk/src/core/error-codes.ts`
  - `packages/frontend-sdk/src/core/envelope.ts`
  - `packages/frontend-sdk/tests/core-envelope.test.js`
  - `packages/frontend-sdk/tests/core-http.test.js`
  - `packages/frontend-sdk/tests/core-sse.test.js`
- mock/example/stub reference(s):
  - none; the live service implementation currently defines the route behavior directly
- log or validation reference(s):
  - `logs/supervisor-frontend-sdk/progress.log`
  - `docs/status/supervisor-frontend-sdk-status.md`

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - added `CHAT_STREAM_EVENTS_NOT_FOUND` to `packages/common-schemas/errors/error_codes.yaml` and synchronized `FoundationErrorCode` / `foundationErrorCodes`
  - published `GET /api/v1/chat/sessions/{conversation_id}/messages/{message_id}/events` and `GET /api/v1/chat/sessions/{conversation_id}/messages/{message_id}/events/stream` in `openapi/orchestrator-service.openapi.yaml`
  - added shared stored stream replay record/page schemas so the event replay list route has a reusable frozen DTO baseline
- deferred:
  - no gateway-normalized public alias was added beyond the current orchestrator-owned route surface
- rationale:
  - the backend route and string code already exist in the live orchestrator implementation, so frontend consumers should not keep an owned supplement for this not-found replay case
