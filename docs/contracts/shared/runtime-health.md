# Shared Runtime Health Guidance

This document defines the additive field names foundation expects when a service publishes backend-selection evidence through `/healthz`, `/snapshot`, or a dedicated runtime endpoint.

## Liveness vs backend proof
- minimal `/healthz` routes may remain liveness-only
- liveness-only responses must not be treated as proof of which persistence backend is active
- if a service needs response-level backend evidence, it should either:
  - add a dedicated runtime/snapshot route, or
  - extend its health response with the additive fields below
- services that already publish richer runtime health may use `/healthz` for degraded-but-live evidence and `/readyz` for strict traffic readiness

## Canonical additive fields
- `runtime_mode`: one of `shared-backend`, `local-fallback`, or `mixed`
- `backends`: object keyed by stable backend identifiers such as `mysql`, `redis`, `minio`, `qdrant`, `opensearch`, `sqlite`, `file_store`
- each backend record should use:
  - `kind`: backend technology family
  - `role`: `primary`, `cache`, `queue`, `raw-object`, `index`, `fallback`, or `optional`
  - `configured`: boolean
  - `active`: boolean
  - `restart_durable`: boolean
  - `required_for_release`: boolean
  - `evidence`: short stable string such as `restart-smoke`, `snapshot`, `audit-read`, `event-replay`, `connector-ping`
  - `fallback`: nullable string naming the local/degraded path when the main backend is absent
  - `notes`: optional short string

## Readiness baseline
- `/readyz` should use status values `ready` and `not_ready`
- `/readyz` should return `not_ready_components[]` and the same additive `runtime` object used by `/healthz`
- `/healthz` may stay `ok` / `degraded`; `/readyz` is the stricter load-balancer signal
- upstream HTTP transport sections should expose nested `dependencyReadiness` objects when their effective readiness depends on a downstream service
- `dependencyReadiness` should use:
  - `ready`
  - `status`
  - `mode`
  - `service`
  - optional `httpStatus`
  - optional `notReadyComponents[]`
  - optional `error`

## Example shape
```json
{
  "status": "ok",
  "service": "marketing-service",
  "runtime_mode": "shared-backend",
  "backends": {
    "mysql": {
      "kind": "mysql",
      "role": "primary",
      "configured": true,
      "active": true,
      "restart_durable": true,
      "required_for_release": true,
      "evidence": "restart-smoke",
      "fallback": "sqlite://local-dev.db"
    },
    "minio": {
      "kind": "minio",
      "role": "raw-object",
      "configured": true,
      "active": true,
      "restart_durable": true,
      "required_for_release": false,
      "evidence": "connector-ping",
      "fallback": null
    }
  }
}
```

## Current rollout
- `auth-user-service`, `marketing-service`, and `research-service` still publish liveness-only `/healthz` responses today
- foundation now documents the canonical field names and OpenAPI guidance for those services, but route-level backend evidence remains an owner implementation step
- QA should keep using the persistence matrix in `docs/contracts/shared/persistence-backends.md` until each owner exposes response-level backend evidence
