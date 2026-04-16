# Change Request: Shared MySQL / Redis Runtime Config Promotion

## Date
- 2026-04-16

## Requested By
- supervisor-orchestrator

## Background
- the 2026-04-16 real-infra migration priority requires `orchestrator-service`, `tool-hub-service`, and `business-tools-service` to move their authoritative runtime paths away from process-local JSON/file storage and toward MySQL + Redis-backed persistence
- the owned services now consume `SMARTCLOUD_MYSQL_DSN` and `SMARTCLOUD_REDIS_URL` so the same deploy/runtime wiring can drive MySQL-backed session/audit/config storage and Redis-backed SSE/idempotency/query-cache storage
- these shared env keys already appear in deployment and other service-local implementations, but they are not yet reserved in the frozen shared runtime-config contract

## Requested Contract Update
- reserve `SMARTCLOUD_MYSQL_DSN` as the shared MySQL connection-string key for runtime metadata/state stores
- reserve `SMARTCLOUD_REDIS_URL` as the shared Redis connection-string key for cache, stream, queue, and runtime-coordination paths
- document that service owners may continue to add service-local table/namespace keys while reusing these shared connection keys

## Why This Needs Foundation
- `docs/contracts/shared/runtime-config.md` is frozen outside `change-requests/`
- the new cross-service runtime keys affect shared deployment conventions and should be promoted centrally rather than remaining only owner-local implementation details

## Current Owner-Local Behavior
- `apps/orchestrator-service` now uses `SMARTCLOUD_MYSQL_DSN` for conversation/state/agent-config persistence and `SMARTCLOUD_REDIS_URL` for SSE replay plus local business-tools Redis-backed caches
- `apps/tool-hub-service` now uses `SMARTCLOUD_MYSQL_DSN` for tool-call audit persistence and `SMARTCLOUD_REDIS_URL` for local business-tools Redis-backed caches
- `apps/business-tools` now uses `SMARTCLOUD_REDIS_URL` for idempotency and query-cache mainline persistence

## Compatibility
- additive only
- no request/response contract break is required
- services still preserve file/memory fallback paths for degraded mode when the shared middleware is unavailable

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - reserved `SMARTCLOUD_MYSQL_DSN` and `SMARTCLOUD_REDIS_URL` in `.env.example`
  - added the same keys to `@smartcloud-x/common` `sharedRuntimeEnvKeys`
  - documented the shared MySQL/Redis connector semantics in `docs/contracts/shared/runtime-config.md` and the new shared persistence matrix
- deferred:
  - service-local table names, Redis namespaces, and deployment-specific DSN options remain downstream-owned
- rationale:
  - these connector names are already reused across multiple runtime paths and deployment assets, so leaving them owner-local would keep the real-infra migration ambiguous for downstream teams
