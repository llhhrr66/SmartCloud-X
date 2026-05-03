# Shared Runtime Health Guidance

This document defines the shared field names and semantics used when a service publishes runtime health, backend-selection evidence, and traffic readiness through `/healthz`, `/readyz`, `/snapshot`, or dedicated runtime endpoints.

> Contract posture: this document reflects the current repo baseline after readiness closeout work. It does **not** treat placeholder OpenAPI text or future target-state architecture as implementation proof.

## Liveness vs readiness vs runtime evidence
- `/healthz` answers: "is the service alive, and is it degraded?"
- `/readyz` answers: "is the service ready to receive traffic?"
- runtime/backend evidence answers: "which backend path is active, and is it acceptable for release?"
- minimal liveness-only routes must not be treated as proof of backend selection
- services that need response-level backend evidence should either:
  - extend `/healthz` with the additive fields below, or
  - expose a dedicated runtime/snapshot route that uses the same field semantics
- readiness is stricter than liveness: a service may be live but still `not_ready`

## Canonical top-level fields
The current five-service baseline uses these top-level fields when health/readiness responses expose structured runtime data:
- `status`
- `service`
- `runtime_mode`
- `runtime`

Additional route-specific fields:
- `/healthz` may add `degraded_components[]`
- `/readyz` should add `not_ready_components[]`
- gateway readiness aggregation may add owner-specific fields such as `upstreams` or `not_ready_upstreams`

## Status values
### `/healthz`
- `ok`: service is live and no release-relevant degradation is currently reported
- `degraded`: service is live, but one or more dependencies or runtime paths are degraded

### `/readyz`
- `ready`: service can accept intended traffic for the current environment
- `not_ready`: service should not receive intended traffic for the current environment

### Nested dependency readiness
`dependencyReadiness.status` uses:
- `ready`
- `not_ready`

## Canonical additive fields
### `runtime_mode`
`runtime_mode` describes the effective runtime path, not the desired target architecture.

Allowed values:
- `shared-backend`: the intended shared backend path is configured and active
- `local-fallback`: only owner-local or compatibility fallback is active
- `mixed`: both intended and fallback/degraded paths are present, or some critical dependencies are shared while others are temporarily fallback/degraded

Interpretation rules:
- `shared-backend` is the expected release posture for the aligned mainline path
- `local-fallback` is acceptable for local smoke, isolated tests, and development recovery only unless an owner explicitly documents otherwise
- `mixed` is a migration or degraded transition posture and must not be silently described as fully aligned production state

### `runtime.backends`
`runtime.backends` should be keyed by stable backend identifiers such as:
- `mysql`
- `mongodb`
- `redis`
- `minio`
- `qdrant`
- `opensearch`
- `sqlite`
- `memory`
- `file_store`

Each backend record should use:
- `kind`: backend technology family
- `role`: `primary`, `cache`, `queue`, `raw-object`, `index`, `fallback`, or `optional`
- `configured`: boolean
- `active`: boolean
- `restart_durable`: boolean
- `required_for_release`: boolean
- `evidence`: short stable string such as `engine-dialect`, `cache-ping`, `connector-ping`, `http-probe`, `snapshot`, `event-replay`
- `fallback`: nullable string naming the local/degraded path when the main backend is absent
- `notes`: optional short string

### `fallback`
- `fallback` describes the alternate path used when the mainline backend is unavailable or intentionally bypassed
- examples: `sqlite://local-fallback`, `memory-ttl`, `knowledge_chunks`, `json-mirror`
- `fallback` is descriptive metadata; it does not, by itself, imply the service is ready for release

### `required_for_release`
- `required_for_release=true` means the backend is part of the intended environment's release gate
- `required_for_release=false` means the backend may be optional, degraded, compatibility-only, or allowed to fall back without blocking all traffic
- a service may still return `/healthz.status=ok` while a non-release-required backend is inactive
- a service should return `/readyz.status=not_ready` when a release-required backend or dependency is not ready for the intended environment

## Readiness baseline
`/readyz` should use the stricter traffic-readiness contract:
- HTTP `200` with `status=ready`
- HTTP `503` with `status=not_ready`
- include `service`
- include `not_ready_components[]`
- include the same or equivalent `runtime` object used by `/healthz`
- tolerate unrelated query parameters; readiness routes must not return `400` for extra probe parameters
- do not fail with `500` merely because diagnostic-field construction is incomplete

### Minimal `/readyz` schema
The minimum reusable readiness shape for service-owned `/readyz` routes is:

```json
{
  "status": "ready",
  "service": "tool-hub-service",
  "runtime_mode": "shared-backend",
  "not_ready_components": [],
  "runtime": {}
}
```

Interpretation rules:
- `status` must be `ready` or `not_ready`
- `service` must be the stable kebab-case service name used in runtime payloads and gateway aggregation
- `not_ready_components` must always be an array, never `null`
- `runtime_mode` is recommended when the service distinguishes `shared-backend`, `mixed`, or `local-fallback`
- `runtime` may contain additive owner-defined evidence, but callers should be able to reason about readiness from the top-level fields alone

## Service-specific interpretation note: orchestrator optional document store
The current `orchestrator-service` implementation intentionally evaluates optional document-store degradation differently across `/healthz` and `/readyz`.

Current code-backed behavior (`apps/orchestrator-service/app/api/routes/health.py`):
- `/healthz` includes optional configured document-store degradation in `degraded_components[]`
- `/readyz` excludes optional document-store degradation from `not_ready_components[]`
- therefore `GET /healthz` may return `status="degraded"` while `GET /readyz` still returns `status="ready"`

This is the expected current semantic boundary when the degraded item is the optional conversation document store:
- example degraded component: `conversationStore`
- typical runtime evidence lives under `runtime.conversationStore.documentStore`
- if that nested `documentStore` is not required for the current environment, its backend error or `ready=false` state does **not** block traffic readiness by itself
- QA and release checks must treat this as: "live but degraded diagnostic surface" rather than "not ready"

Interpretation rule for reviewers and probe authors:
- do **not** infer `not_ready` from orchestrator `/healthz.status="degraded"` alone
- use `/readyz` as the traffic gate
- when `/healthz.degraded_components` contains `conversationStore` because of an optional document store, record it as degraded runtime evidence, not as a release-blocking readiness failure unless `/readyz` also reports `not_ready`


Each upstream entry should expose:
- `contract`: probe contract used for that upstream; expected values are `readyz` or `healthz-fallback`
- `status`: gateway's derived readiness view for that upstream; expected values are `ready` or `not_ready`
- `http_status`: upstream probe HTTP status code when available
- `payload`: parsed upstream response payload when JSON decoding succeeds
- `error`: probe/contract failure summary when the upstream cannot be treated as ready

Minimal gateway aggregate shape:

```json
{
  "data": {
    "service": "gateway-service",
    "status": "not_ready",
    "not_ready_upstreams": ["auth-user-service"],
    "upstreams": {
      "auth-user-service": {
        "contract": "healthz-fallback",
        "status": "not_ready",
        "http_status": 200,
        "payload": {
          "status": "ok",
          "service": "auth-user-service"
        },
        "error": "upstream readiness contract unavailable; using /healthz fallback"
      }
    }
  },
  "request_id": "req-123"
}
```

### `healthz-fallback` interpretation
- `healthz-fallback` means gateway could only probe `/healthz` because the upstream readiness contract was absent from the registry or unavailable at runtime
- `healthz-fallback` is a contract gap, not successful readiness proof
- even if the fallback `/healthz` probe returns HTTP `200`, gateway and QA must treat that upstream as `not_ready`
- release/readiness reviews should record `healthz-fallback` as a blocking explanation until the upstream publishes and gateway consumes a real `/readyz`

## dependencyReadiness baseline
When effective readiness depends on a downstream HTTP service or provider, the owning service should expose nested `dependencyReadiness` records.

`dependencyReadiness` should use:
- `ready`: boolean
- `status`: `ready` or `not_ready`
- `mode`: current probe or transport mode such as `http`
- `service`: downstream service name
- optional `httpStatus`
- optional `notReadyComponents[]`
- optional `error`

This object is especially relevant for:
- gateway upstream readiness aggregation
- rag-service probing knowledge-service
- any service whose traffic acceptance depends on a downstream HTTP dependency rather than only local process state

## Admin audit header baseline
Admin write routes that create, mutate, rebuild, trigger high-risk actions, or otherwise require audit context must require the operator reason header:
- header name: `X-Operator-Reason`
- shared OpenAPI parameter: `XOperatorReasonRequiredHeader`
- environment mapping: `SMARTCLOUD_OPERATOR_REASON_HEADER` on the backend and `VITE_OPERATOR_REASON_HEADER` on the admin frontend

Requirements:
- admin reads may omit the header unless the owning route declares stronger policy
- admin writes that require audit context must document the header as required in OpenAPI and route-level contract text
- missing operator reason must be rejected explicitly or captured as a clearly visible audit-gap condition; it must not be silently dropped from the write path

Example write request:

```http
POST /api/v1/admin/knowledge-bases HTTP/1.1
Authorization: Bearer <admin-token>
X-Operator-Reason: 初始化验收知识库
Content-Type: application/json
```

## Current five-service baseline
The current aligned baseline is:
- `gateway-service`
  - `/healthz`: aggregated liveness/degraded view
  - `/readyz`: canonical external envelope containing gateway readiness aggregation data
  - upstream probing should prefer `/readyz`; if an upstream only exposes `/healthz`, the result should be marked as a contract gap or fallback probe path rather than treated as equivalent readiness proof
- `orchestrator-service`
  - `/healthz` and `/readyz` already act as the model for direct JSON readiness payloads
- `auth-user-service`
  - `/healthz` may include backend evidence
  - `/readyz` is the release-oriented gate for MySQL/shared-backend vs SQLite/local-fallback
- `knowledge-service`
  - `/healthz` remains a richer runtime diagnostic surface
  - `/readyz` is the strict traffic gate and may expose domain-index mode through `runtime`
- `rag-service`
  - `/healthz` remains a richer runtime diagnostic surface
  - `/readyz` is the strict traffic gate and may expose nested `knowledgeService.dependencyReadiness`

## Example shapes
### `/healthz`
```json
{
  "status": "degraded",
  "service": "rag-service",
  "runtime_mode": "mixed",
  "degraded_components": ["knowledgeService"],
  "runtime": {
    "cache": {
      "kind": "redis",
      "role": "cache",
      "configured": true,
      "active": true,
      "restart_durable": true,
      "required_for_release": false,
      "evidence": "cache-ping",
      "fallback": "memory-ttl",
      "notes": null
    },
    "knowledgeService": {
      "dependencyReadiness": {
        "ready": false,
        "status": "not_ready",
        "mode": "http",
        "service": "knowledge-service",
        "httpStatus": 503,
        "notReadyComponents": ["vectorStore"],
        "error": "upstream not ready"
      }
    }
  }
}
```

### `/readyz`
```json
{
  "status": "not_ready",
  "service": "auth-user-service",
  "runtime_mode": "local-fallback",
  "not_ready_components": ["mysql"],
  "runtime": {
    "backends": {
      "sqlite": {
        "kind": "sqlite",
        "role": "fallback",
        "configured": true,
        "active": true,
        "restart_durable": true,
        "required_for_release": false,
        "evidence": "engine-dialect",
        "fallback": null,
        "notes": "local/test compatibility database derived from owner config"
      }
    }
  }
}
```

## QA and review guidance
- do not treat placeholder OpenAPI descriptions as runtime evidence
- do not treat `/healthz` and `/readyz` as interchangeable
- use `runtime_mode`, backend records, and `dependencyReadiness` together when deciding whether a service is release-ready
- if an upstream is only probeable via `/healthz`, record that as a contract gap or fallback probe path in QA output
- if a service runs on `local-fallback`, it may be valid for local validation but should not be reported as shared-backend release proof
