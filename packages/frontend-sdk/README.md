# @smartcloud-x/frontend-sdk

Shared frontend baseline for SmartCloud-X web surfaces.

## Scope
- contract-aligned DTO/type exports for auth, orchestrator/chat, admin knowledge flows, marketing, research, and the current owned web-user business outlet for billing / order / ticket / ICP / file / citation-detail
- shared API client with envelope/error/SSE parsing, a strict shared frontend error-code typing outlet that reuses frozen `FoundationErrorCode` exports plus the current owned supplement, frozen-foundation error-code classification (including `error_code` / `error_message` aliases, explicit in-band failure-envelope rejection, inferred shared status resolution, and `404` not-found handling), SSE transport error wrapping, reconnect delay helpers, and a reusable reconnect-consuming helper for browser chat/event streams
- page-shaped billing / order / refund / ticket adapters with owned pagination-query/result typings and surface-specific page aliases that reuse frozen pagination conventions while frontend contract promotion is pending
- browser auth/session helpers for user-web integration, including stricter silent-refresh gating for refreshable versus explicitly invalid auth failures
- reusable web-user and web-admin adapters, request-body helpers, admin retrieval mappers, typed admin mutation/query inputs, admin runtime snapshot / capabilities helpers, relative-base-safe admin URL/query handling, and wrapped named-resource normalization for billing/order/ticket/ICP/file/citation detail payloads

## Current adoption
- `apps/web-user` now reuses the shared API client, auth/session manager/store, auth/chat/marketing/research DTOs, billing/order/ticket/ICP/file/citation-detail DTOs and adapters, chat request-body helpers, marketing copy/poster/research/auth request-response helpers, chat/session response mappers, and shared SSE reconnect helpers through thin local shims
- `apps/web-admin` now reuses the shared request wrapper, knowledge/rag/admin adapter surface, admin retrieval preview/diagnostics mappers, readiness-aware health DTOs, shared admin mutation/query input types, and shared runtime snapshot / RAG capabilities helpers (including runtime event-counter / outbox detail typings) through a thin local shim

## Known gaps
- billing / order / ticket / ICP / file / citation-detail DTOs are now shared in `packages/frontend-sdk/` through an owned frontend typing outlet, but no frozen shared frontend contract has been promoted for those surfaces yet
- owned page-query / page-result typings for billing / order / refund / ticket now live in the shared SDK, but the underlying business payloads still need frozen OpenAPI/common-schema promotion before the outlet can collapse onto frozen exports
- `packages/common-schemas/src/index.ts` does not yet export every frozen code listed in `packages/common-schemas/errors/error_codes.yaml`, so the SDK currently keeps an owned supplement for strict shared error classification; promotion is tracked in `docs/contracts/change-requests/2026-04-16-frontend-sdk-foundation-error-code-export-alignment.md`
- user-facing canonical frontend DTO promotion beyond the currently frozen auth / orchestrator / marketing / research contracts should continue through `docs/contracts/change-requests/`, after which the owned business outlet can collapse onto frozen shared exports
