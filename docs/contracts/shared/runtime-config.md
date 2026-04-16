# Shared Runtime Config Baseline

The root `.env.example` reserves the following cross-project keys:
- `SMARTCLOUD_ENV`
- `SMARTCLOUD_LOG_LEVEL`
- `SMARTCLOUD_TIMEZONE`
- `SMARTCLOUD_DEFAULT_LOCALE`
- `SMARTCLOUD_API_PREFIX`
- `SMARTCLOUD_API_VERSION`
- `SMARTCLOUD_CORS_ALLOWED_ORIGINS`
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

## Loading expectations
- root-level shared keys define naming and defaults only; service owners still choose their own config loaders
- `SMARTCLOUD_ENV` should use the current shared environment vocabulary: `local`, `dev`, `test`, `staging`, or `prod`
- `SMARTCLOUD_API_PREFIX` and `SMARTCLOUD_API_VERSION` directly compose the segmented service paths used today by `rag-service` and `knowledge-service`
- `SMARTCLOUD_CORS_ALLOWED_ORIGINS` is the shared comma-separated browser-origin allow-list currently consumed by `rag-service` and `knowledge-service`
- `ALLOWED_INTERNAL_CALLERS` is the shared service-local allow-list key currently reused by `orchestrator-service`, `tool-hub-service`, and `business-tools-service`; each service must supply its own comma-separated caller identities
- services with flat canonical routes such as `orchestrator-service`, `tool-hub-service`, and `business-tools-service` should keep their service-local canonical prefixes (`/api/v1` or `/internal/v1`) and treat the shared prefix/version pair as a naming convention, not a forced override
- `BUSINESS_TOOLS_INTERNAL_API_PREFIX` and `TOOL_HUB_INTERNAL_API_PREFIX` are additive provider-transport override keys used when orchestrator/tool-hub HTTP clients must target a deployed downstream internal prefix that differs from the local `/internal/v1` default
- services should fail fast on missing secrets or invalid shared header names
- service-local `.env.{env}` files remain downstream-owned and should map back to these shared names when values are cross-cutting
