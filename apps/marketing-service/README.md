# SmartCloud-X Marketing Service

FastAPI baseline for user-facing campaign browsing, copy generation, poster task polling, and promotion-link placeholder generation.

## Implemented routes
- `GET /healthz`
- `GET /api/v1/marketing/campaigns`
- `POST /api/v1/marketing/copy/generate`
- `GET /api/v1/marketing/copies`
- `GET /api/v1/marketing/copies/{copy_id}`
- `POST /api/v1/marketing/promotion-links/generate`
- `GET /api/v1/marketing/promotion-links`
- `GET /api/v1/marketing/promotion-links/{link_id}`
- `GET /api/v1/marketing/posters`
- `POST /api/v1/marketing/posters`
- `GET /api/v1/marketing/posters/{task_id}`
- `GET /api/v1/marketing/posters/{task_id}/result`

## Runtime notes
- Primary runtime persistence now uses `MARKETING_SERVICE_DATABASE_URL` with shared `SMARTCLOUD_MYSQL_DSN` fallback; local/test runs may still point that setting at SQLite.
- `MARKETING_SERVICE_BOOTSTRAP_PATH` (legacy alias: `MARKETING_SERVICE_DATA_PATH`) is now migration/bootstrap input only, not the authoritative runtime store.
- Uses the shared `SMARTCLOUD_JWT_SECRET`, `SMARTCLOUD_AUTH_ISSUER`, and `SMARTCLOUD_AUTH_AUDIENCE` values so access tokens from `auth-user-service` are accepted here; internal-audience service tokens are not accepted on public user routes.
- Optional strict current-state validation is available via `MARKETING_SERVICE_AUTH_VALIDATION_MODE=strict` plus `MARKETING_SERVICE_AUTH_VALIDATE_TOKEN_URL`; when enabled, the service calls `auth-user-service` `GET /internal/v1/auth/validate-token` as `marketing-service` so logout/password-rotation invalidation propagates before token expiry.
- User-facing campaign reads and generation flows operate on currently active published campaigns only; draft, expired, or not-yet-started campaign IDs are not exposed in listings and are rejected by the write endpoints.
- Generated copy, promotion-link, and poster-task records are now persisted in database tables and can be listed or fetched later through read routes scoped to the authenticated `(tenant_id, user_id)`.
- Copy generation now falls back to the selected campaign highlights when callers omit `keywords`, which makes the starter payloads more useful for local demos without requiring prompt tuning on every request.
- Poster task creation requires `Idempotency-Key`; duplicate submissions replay the original accepted task id/status while conflicting payload reuse returns `4090001`.
- `MARKETING_SERVICE_AUTO_COMPLETE_SECONDS=0` keeps the starter poster flow in instant-complete mode for smoke tests; any positive value now exposes a more realistic `queued -> running -> completed` lifecycle before the placeholder asset URL appears.
- Poster task visibility and idempotency replay are scoped by authenticated `(tenant_id, user_id)` so the same account id can generate isolated assets in different tenants without leaking task state.
- Poster completion now prefers `MARKETING_SERVICE_MINIO_*` / shared `SMARTCLOUD_MINIO_*` settings for placeholder asset upload and falls back to the configured public poster URL root when object storage is unavailable.
- `copy/generate`, `promotion-links/generate`, and the poster result helper route now align with the promoted frozen contract and appear in the live FastAPI schema.
