# Shared Runtime Config Baseline

The root `.env.example` reserves the following cross-project keys:
- `SMARTCLOUD_ENV`
- `SMARTCLOUD_LOG_LEVEL`
- `SMARTCLOUD_TIMEZONE`
- `SMARTCLOUD_DEFAULT_LOCALE`
- `SMARTCLOUD_API_PREFIX`
- `SMARTCLOUD_API_VERSION`
- `SMARTCLOUD_CORS_ALLOWED_ORIGINS`
- `SMARTCLOUD_MYSQL_DSN`
- `SMARTCLOUD_REDIS_URL`
- `SMARTCLOUD_MINIO_ENDPOINT`
- `SMARTCLOUD_MINIO_BUCKET`
- `SMARTCLOUD_MINIO_ACCESS_KEY`
- `SMARTCLOUD_MINIO_SECRET_KEY`
- `SMARTCLOUD_AUTH_ISSUER`
- `SMARTCLOUD_AUTH_AUDIENCE`
- `SMARTCLOUD_INTERNAL_AUTH_AUDIENCE`
- `SMARTCLOUD_JWT_ALGORITHM`
- `SMARTCLOUD_JWT_SECRET`
- `SMARTCLOUD_TOKEN_TTL_MINUTES`
- `SMARTCLOUD_REQUEST_TIMEOUT_MS`
- `SMARTCLOUD_SSE_HEARTBEAT_INTERVAL_SECONDS`
- `ALLOWED_INTERNAL_CALLERS`
- `BUSINESS_TOOLS_INTERNAL_API_PREFIX`
- `TOOL_HUB_INTERNAL_API_PREFIX`
- `SMARTCLOUD_TRACE_ENABLED`
- `SMARTCLOUD_REQUEST_ID_HEADER`
- `SMARTCLOUD_TRACE_ID_HEADER`
- `SMARTCLOUD_CONVERSATION_ID_HEADER`
- `SMARTCLOUD_TENANT_ID_HEADER`
- `SMARTCLOUD_CALLER_SERVICE_HEADER`
- `SMARTCLOUD_TOOL_CALL_ID_HEADER`
- `SMARTCLOUD_IDEMPOTENCY_KEY_HEADER`
- `SMARTCLOUD_OPERATOR_REASON_HEADER`
- `SMARTCLOUD_LANGSMITH_ENABLED`
- `SMARTCLOUD_LANGSMITH_PROJECT`
- `SMARTCLOUD_PHOENIX_ENABLED`
- `SMARTCLOUD_PHOENIX_COLLECTOR_ENDPOINT`

Downstream services may add local env keys inside their owned directories or deployment templates, but changes to these shared names must route through foundation.

## Shared persistence connector keys
- `SMARTCLOUD_MYSQL_DSN` is the shared DSN name for authoritative MySQL-backed metadata and state stores across auth, orchestrator, tool-hub, knowledge, marketing, and research baselines
- `SMARTCLOUD_REDIS_URL` is the shared Redis connection key for cache, SSE replay, idempotency, queue, and runtime-coordination paths
- `SMARTCLOUD_MINIO_ENDPOINT`, `SMARTCLOUD_MINIO_BUCKET`, `SMARTCLOUD_MINIO_ACCESS_KEY`, and `SMARTCLOUD_MINIO_SECRET_KEY` are the shared raw-object connector keys currently reused by knowledge-service and marketing-service
- the repo-wide persistence matrix and release-vs-local fallback rules now live in `docs/contracts/shared/persistence-backends.md`

## Current documented owner-local runtime knobs
- `orchestrator-service` currently exposes owner-local `DEFAULT_AGENT_TIMEOUT_SECONDS` and `AGENT_CONFIG_STORE_PATH` for its process-local admin agent-config baseline
- these keys are documented for contract discoverability, but they are not reserved shared root `.env.example` names and remain downstream-owned orchestrator runtime settings
- `BUSINESS_TOOLS_REDIS_NAMESPACE` remains owner-local instead of a reserved root key, but it is now documented as the shared namespace knob reused by business-tools, tool-hub, and orchestrator whenever local/degraded business-tools Redis state must stay aligned

## Loading expectations
- root-level shared keys define naming and defaults only; service owners still choose their own config loaders
- `SMARTCLOUD_ENV` should use the current shared environment vocabulary: `local`, `dev`, `test`, `staging`, or `prod`
- `SMARTCLOUD_API_PREFIX` and `SMARTCLOUD_API_VERSION` directly compose the segmented service paths used today by `rag-service` and `knowledge-service`
- `SMARTCLOUD_CORS_ALLOWED_ORIGINS` is the shared comma-separated browser-origin allow-list currently consumed by `rag-service` and `knowledge-service`
- `SMARTCLOUD_MYSQL_DSN` is the shared authoritative metadata/state-store connector for services that have already migrated off JSON/file-only persistence on their mainline runtime path
- `SMARTCLOUD_REDIS_URL` is the shared runtime coordination connector for SSE replay, cache, idempotency, and queue-backed flows; services may still keep degraded local fallback spools, but release promotion should not depend on those fallbacks
- `SMARTCLOUD_MINIO_*` keys describe the current shared raw-object connector baseline; service-local bucket/layout knobs may extend this, but shared endpoint/bucket/credential names should not drift
- `ALLOWED_INTERNAL_CALLERS` is the shared service-local allow-list key currently reused by `orchestrator-service`, `tool-hub-service`, and `business-tools-service`; each service must supply its own comma-separated caller identities
- services with flat canonical routes such as `orchestrator-service`, `tool-hub-service`, and `business-tools-service` should keep their service-local canonical prefixes (`/api/v1` or `/internal/v1`) and treat the shared prefix/version pair as a naming convention, not a forced override
- `BUSINESS_TOOLS_INTERNAL_API_PREFIX` and `TOOL_HUB_INTERNAL_API_PREFIX` are additive provider-transport override keys used when orchestrator/tool-hub HTTP clients must target a deployed downstream internal prefix that differs from the local `/internal/v1` default
- `BUSINESS_TOOLS_REDIS_NAMESPACE` should stay owner-local, but all three local/degraded business-tools executors should reuse the same base namespace before appending owned suffixes such as `:idempotency` or `:query-cache`
- retrieval/index connector keys such as `SMARTCLOUD_QDRANT_URL` and `SMARTCLOUD_OPENSEARCH_URL` are tracked in `docs/contracts/shared/persistence-backends.md`; they remain owner-local until a second service binds them directly through frozen root config
- services should fail fast on missing secrets or invalid shared header names
- service-local `.env.{env}` files remain downstream-owned and should map back to these shared names when values are cross-cutting
