# Change Request

## Summary
- requester: supervisor-frontend-sdk
- date: 2026-04-16
- affected frozen path: `packages/common-schemas/src/index.ts`, `packages/common-schemas/errors/error_codes.yaml`
- blocking: no

## Background
`packages/frontend-sdk/` now classifies shared HTTP/SSE failures against the frozen foundation error catalog so web-user and web-admin can share one reconnect/retry path. While tightening that logic, the SDK had to keep an owned supplement because the runtime/type exports in `packages/common-schemas/src/index.ts` do not currently match the full frozen YAML catalog in `packages/common-schemas/errors/error_codes.yaml`.

Examples present in the frozen YAML but missing from the exported `FoundationErrorCode` / `foundationErrorCodes` surface include:

1. `BUSINESS_TOOLS_CALLER_FORBIDDEN`
2. `TOOL_HUB_CALLER_FORBIDDEN`
3. `CHAT_CONTINUATION_NOT_AVAILABLE`
4. `CHAT_CONVERSATION_RUNNING`
5. `CHAT_MESSAGE_NOT_RUNNING`
6. `CHAT_MESSAGE_CANCELLED`

Because those codes are already frozen in YAML/OpenAPI examples, the frontend SDK can classify them safely today, but it cannot rely on the shared package exports as the single source of truth yet.

## Current Gap
1. `packages/common-schemas/errors/error_codes.yaml` is the frozen registry, but `packages/common-schemas/src/index.ts` exports an incomplete subset through `FoundationErrorCode` and `foundationErrorCodes`.
2. Shared frontend consumers therefore cannot reuse a complete exported error-code union/list from frozen space for strict client classification.
3. The SDK now keeps an owned supplement in `packages/frontend-sdk/src/core/envelope.ts`, which is usable but should not remain the long-term duplication point.

## Proposed Change
1. Align `packages/common-schemas/src/index.ts` with the full frozen YAML registry by exporting every currently frozen code from `errors/error_codes.yaml`.
2. Keep the exported list intentionally generated or otherwise checked against the YAML file so future frozen error-code additions do not drift again.
3. If foundation prefers not to widen `FoundationErrorCode`, publish an equivalent frozen exported list/union for frontend/backend consumers that is guaranteed to stay in sync with the YAML catalog.

## Impacted Consumers
- supervisor(s): `supervisor-frontend-sdk`, `supervisor-foundation`
- service(s) or surface(s): `packages/frontend-sdk/`, future shared frontend/backend consumers that want one frozen error-code export surface
- required follow-up work:
  - foundation aligns exported error-code types/lists to the frozen YAML catalog
  - frontend-sdk removes or shrinks its owned supplement after the frozen export becomes complete

## Compatibility
- breaking or non-breaking: non-breaking additive change
- fallback or migration plan: frontend-sdk continues using its owned supplement until the frozen export is complete
- temporary workaround already in use:
  - `packages/frontend-sdk/src/core/envelope.ts`
  - `packages/frontend-sdk/tests/core-envelope.test.js`
  - `packages/frontend-sdk/tests/core-http.test.js`

## Evidence
- code reference(s):
  - `packages/common-schemas/errors/error_codes.yaml`
  - `packages/common-schemas/src/index.ts`
  - `packages/frontend-sdk/src/core/envelope.ts`
- log or validation reference(s):
  - `logs/supervisor-frontend-sdk/progress.log`
  - `docs/status/supervisor-frontend-sdk-status.md`

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - aligned the exported `FoundationErrorCode` union and `foundationErrorCodes` list with the full frozen YAML catalog, including the already-promoted caller-forbidden and chat-continuation lifecycle codes
  - documented the shared typed export surface in `@smartcloud-x/common-schemas` so frontend/backend consumers can rely on one frozen error-code registry instead of owned supplement lists
  - hardened `scripts/validate_foundation.py` so future drift between `errors/error_codes.yaml` and the TypeScript exports now fails fast during foundation readiness checks
- deferred:
  - no additional error-code catalog restructuring was needed beyond keeping the TypeScript exports synchronized with the frozen YAML registry
- rationale:
  - the YAML catalog is already the frozen source of truth, so the lowest-risk fix was to keep the shared TypeScript export surface exactly in sync with it and enforce that invariant in the validator
