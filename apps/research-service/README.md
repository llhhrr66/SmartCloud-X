# SmartCloud-X Research Service

FastAPI baseline for user-facing research task creation, polling, and placeholder report results.

## Implemented routes
- `GET /healthz`
- `GET /api/v1/research/tasks`
- `POST /api/v1/research/tasks`
- `GET /api/v1/research/tasks/{task_id}`
- `GET /api/v1/research/tasks/{task_id}/status`
- `GET /api/v1/research/tasks/{task_id}/result`

## Runtime notes
- Persistent local JSON store path: `RESEARCH_SERVICE_DATA_PATH`
- Uses the shared `SMARTCLOUD_JWT_SECRET`, `SMARTCLOUD_AUTH_ISSUER`, and `SMARTCLOUD_AUTH_AUDIENCE` values so access tokens from `auth-user-service` are accepted here; internal-audience service tokens are not accepted on public user routes.
- Optional strict current-state validation is available via `RESEARCH_SERVICE_AUTH_VALIDATION_MODE=strict` plus `RESEARCH_SERVICE_AUTH_VALIDATE_TOKEN_URL`; when enabled, the service calls `auth-user-service` `GET /internal/v1/auth/validate-token` as `research-service` so logout/password-rotation invalidation propagates before token expiry.
- Async task creation requires `Idempotency-Key`; duplicate submissions replay the original accepted task id/status while conflicting payload reuse returns `4090001`.
- `RESEARCH_SERVICE_AUTO_COMPLETE_SECONDS=0` keeps the starter baseline in instant-complete mode for local smoke tests; any positive value now exposes a more realistic `queued -> running -> completed` lifecycle on detail/status/result reads before the placeholder report becomes ready.
- Task visibility and idempotency replay are scoped by authenticated `(tenant_id, user_id)` instead of user id alone, so the same account id can safely create isolated baselines across multiple tenants.
- Owner-local compatibility alias `GET /api/v1/research/tasks/{task_id}/report` is also available for clients that expect an explicit report route; it currently returns the same placeholder payload as `/result` without widening the frozen public contract.
