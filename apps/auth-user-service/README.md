# SmartCloud-X Auth User Service

FastAPI baseline for user auth, profile management, admin auth bootstrap, and internal auth validation/check routes.

## Implemented routes

### Public user auth
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/send-code`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `POST /api/v1/auth/password/forgot`
- `POST /api/v1/auth/forgot-password`
- `POST /api/v1/auth/password/reset`
- `POST /api/v1/auth/reset-password`
- `GET /api/v1/auth/me`
- `GET /api/v1/auth/profile`
- `PATCH /api/v1/users/me`
- `PATCH /api/v1/auth/profile`
- `POST /api/v1/users/me/change-password`
- `POST /api/v1/auth/change-password`

### Admin bootstrap
- `POST /api/v1/admin/auth/login`
- `GET /api/v1/admin/auth/me`
- `POST /api/v1/admin/auth/action-confirmations`

### Internal auth helpers
- `GET /internal/v1/auth/validate-token`
- `POST /internal/v1/auth/check-permission`
- `POST /internal/v1/auth/invalidate-subject-cache`

## Local baseline defaults
- Demo user account: `demo@smartcloud.local`
- Demo user mobile: `13800000001`
- Demo user password: `Password123!`
- Demo admin username: `admin`
- Demo admin password: `Admin123!`
- Starter verification code for local development: `123456`

## Runtime notes
- Persistent local JSON store path: `AUTH_USER_SERVICE_DATA_PATH`
- JWT signing uses shared `SMARTCLOUD_JWT_SECRET`
- Internal caller allow-list now honors the shared `ALLOWED_INTERNAL_CALLERS` env key and still accepts the legacy `AUTH_USER_SERVICE_ALLOWED_INTERNAL_CALLERS` override for compatibility.
- Public access tokens are accepted by the owned `research-service` and `marketing-service` baselines when they use the same shared secret and issuer/audience env values.
- `research-service` and `marketing-service` can also opt into strict current-state validation against `GET /internal/v1/auth/validate-token` by configuring their owned `*_AUTH_VALIDATION_MODE=strict` and `*_AUTH_VALIDATE_TOKEN_URL` env vars.
- Refresh rotation is bound to the persisted refresh-session record; tampered session bindings and access-token payloads passed to logout are rejected.
- Logout now also revokes the caller's current access token immediately, so the same bearer token can no longer read `/auth/me` or pass internal token validation after logout.
- Internal auth routes require an allow-listed `X-Caller-Service`; missing or unlisted callers now fail with `403 AUTH_CALLER_FORBIDDEN` before token introspection proceeds.
- Internal `GET /internal/v1/auth/validate-token` now also enforces current subject token-version state and refresh-session revocation, so stale user/admin tokens do not validate after password rotation or explicit refresh-session logout.
- Profile updates allow `avatar_url: null` to explicitly clear an existing avatar while keeping other mutable fields string-backed.
- Code-based login and reset-password flows now honor the matching account type (`mobile` vs `email`) when resolving the starter user account, so a code issued for one identifier type cannot be replayed against another field on the same user.
- Email verification-code and reset-password flows normalize trimmed or mixed-case email identifiers to the stored account form, so `Demo@SmartCloud.Local` and `demo@smartcloud.local` resolve to the same starter user.
- Re-sending a verification code inside the active TTL window now reuses the existing starter code record instead of silently extending the expiration time on each retry.
