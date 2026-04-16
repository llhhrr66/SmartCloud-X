# Change Request: Business-Tools Redis Namespace Alignment

## Date
- 2026-04-16

## Requested By
- supervisor-orchestrator

## Background
- `business-tools-service` already supports owner-local `BUSINESS_TOOLS_REDIS_NAMESPACE` so its Redis-backed idempotency and query-cache keys can be isolated per deployment
- `orchestrator-service` and `tool-hub-service` now activate local business-tools execution only for transport-local or degraded HTTP-connect fallback paths, but those paths still need to hit the same Redis keyspace as `business-tools-service` when operators customize the namespace
- without an aligned namespace knob across the three owned services, degraded fallback can silently write/read a different Redis keyspace from the mainline business-tools runtime in non-default environments

## Requested Contract Update
- document `BUSINESS_TOOLS_REDIS_NAMESPACE` as the owner-local namespace key reused across `business-tools-service`, `tool-hub-service`, and `orchestrator-service` whenever business-tools Redis-backed idempotency/query-cache state must stay aligned
- clarify that upstream local fallback execution should append owned suffixes such as `:idempotency` and `:query-cache` to the same base namespace instead of hardcoding the default `smartcloud:business-tools`

## Why This Needs Foundation
- `docs/contracts/shared/runtime-config.md` is frozen outside `change-requests/`
- even though this remains owner-local rather than a reserved root `.env.example` key, the same env name is now intentionally shared across three services and should be discoverable in the frozen runtime-config baseline

## Current Owner-Local Behavior
- `apps/business-tools` uses `BUSINESS_TOOLS_REDIS_NAMESPACE` as the base namespace for Redis-backed idempotency/query-cache persistence
- `apps/orchestrator-service` and `apps/tool-hub-service` now reuse the same base namespace when local business-tools execution activates, including degraded HTTP-connect fallback paths

## Compatibility
- additive only
- no request/response contract break is required
- existing deployments that do not set `BUSINESS_TOOLS_REDIS_NAMESPACE` continue to use `smartcloud:business-tools`

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - documented `BUSINESS_TOOLS_REDIS_NAMESPACE` in `docs/contracts/shared/runtime-config.md` as an owner-local but intentionally shared namespace knob across business-tools, tool-hub, and orchestrator local/degraded execution paths
  - recorded the same alignment requirement in `docs/contracts/shared/persistence-backends.md` so Redis-backed idempotency/query-cache fallbacks do not silently split keyspace across services
- deferred:
  - `BUSINESS_TOOLS_REDIS_NAMESPACE` was intentionally not promoted into reserved root `.env.example` / `sharedRuntimeEnvKeys`
- rationale:
  - the env name now matters across three services, so frozen docs need to expose it, but it is still a business-tools-specific namespace knob rather than a root cross-project connector key
