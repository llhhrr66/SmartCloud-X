# Supervisor Auth Marketing Research Status

## Status
- phase: final-closeout-green
- updated at: 2026-04-17T16:00:13+08:00
- owned scope: `apps/auth-user-service/`, `apps/research-service/`, `apps/marketing-service/`
- runtime stance: MySQL-first database-backed services with SQLite fallback kept only for local/test compatibility; `/healthz` publishes canonical additive backend evidence and both local and shell-only remote live smoke are green for auth/marketing/research

## Completed
- `auth-user-service` remains database-backed for user/admin/session/challenge/revocation state and shared bearer-token compatibility across marketing/research remains intact.
- `marketing-service` keeps the completed-task MinIO self-heal path, so persisted poster tasks with missing objects are repaired on read when object storage is configured.
- `research-service` remains database-backed for task/idempotency persistence, and restart-aware task detail/status/result flows remain green.
- QA-011 is closed in owned scope: auth/marketing/research `/healthz` now publish `runtime_mode` plus canonical `backends` records aligned with `docs/contracts/shared/runtime-health.md`, and both local-fallback and live shared-backend smoke paths assert those fields.
- QA-012 is closed in owned scope: the shell-only remote live `auth-marketing-research` smoke against `45.207.220.216` is green again and proves `marketingPosterObjectStored=true`.
- The latest real blocker from window 6 is also closed in owned scope: remote auth login no longer fails on MySQL lock-wait/lost-connection during auth table pruning.
- This auth-user-service round also tightened auth-owned coverage without redesigning the service:
  - profile persistence now trims mutable string fields before saving and enforces bounded input lengths at the API model layer
  - admin action confirmation now has explicit negative tests for wrong password and incomplete non-password verification payloads
  - internal permission checks now have direct denial-path coverage, and cache invalidation writes are asserted as persisted audit events
  - logout misuse coverage now proves a user cannot revoke with another subject's refresh token payload

## Root Cause
- The latest remote live failure was not the older marketing MinIO artifact issue. It occurred earlier during auth login.
- `auth-user-service` called `_prune_expired()` from multiple hot request-path methods, including `get_user_by_account()` on login.
- `_prune_expired()` executed synchronous bulk `DELETE` statements against auth expiry tables on every request and then reloaded the store snapshot. Against the shared remote MySQL runtime this triggered `OperationalError(1205, 'Lock wait timeout exceeded; try restarting transaction')` on `auth_refresh_sessions`, which surfaced as login `500`.

## Fix Summary
- Moved auth expiry cleanup to low-frequency best-effort pruning instead of treating it as mandatory synchronous work before every hot-path read/write.
- Kept auth correctness by enforcing expiration in the relevant lookups themselves:
  - refresh-session reads ignore expired rows
  - verification-code verify/consume ignore expired rows
  - verification-code issuance now replaces expired scoped rows even when global prune is skipped
  - password-challenge and revoked-token lookups now respect expiration directly
- Preserved the previous marketing and runtime-health improvements already landed in owner scope.

## Self-review
- Chose a store-local auth fix instead of adding retries or QA-only workarounds, because the failure originated in owner request-path cleanup behavior.
- Added failing auth tests first for three behaviors:
  - prune OperationalError must not crash auth
  - expired refresh sessions must not be accepted if prune is skipped
  - expired scoped verification codes must be replaced even if prune is skipped
- Re-ran local and remote smoke after the auth store change to confirm the fix removed the real blocker instead of only shifting timing.

## Validation
- `uv run --with ... python -m pytest apps/auth-user-service/tests apps/marketing-service/tests apps/research-service/tests -q` → `113 passed in 53.61s`
- `uv run --with ... python -m pytest tests/integration/test_auth_marketing_research_flow.py -q` → `1 passed in 2.52s`
- `uv run --with ... python -m compileall apps/auth-user-service/app apps/marketing-service/app apps/research-service/app` → passed
- `uv run --with ... python scripts/qa/project_smoke.py --scenario auth-marketing-research` → passed in local fallback mode, including `runtimeHealth` assertions
- shell-only remote override:
  - `SMARTCLOUD_QA_USE_LIVE_INFRA=1`
  - `SMARTCLOUD_QA_REQUEST_TIMEOUT_SECONDS=60`
  - `SMARTCLOUD_QA_SHARED_MYSQL_DSN=mysql+pymysql://smartcloud:***@45.207.220.216:3306/smartcloud`
  - `SMARTCLOUD_QA_SHARED_REDIS_URL=redis://45.207.220.216:6379/0`
  - `SMARTCLOUD_QA_SHARED_RAG_REDIS_URL=redis://45.207.220.216:6379/1`
  - `SMARTCLOUD_QA_SHARED_MINIO_ENDPOINT=http://45.207.220.216:19000`
  - `SMARTCLOUD_QA_SHARED_MINIO_BUCKET=knowledge-raw`
  - `SMARTCLOUD_QA_SHARED_MINIO_ACCESS_KEY=smartcloud`
  - `SMARTCLOUD_QA_SHARED_MINIO_SECRET_KEY=***
  - plus `NO_PROXY=127.0.0.1,localhost`
- the same remote live smoke now passes and proves:
  - auth login/me flow survives restart
  - `marketingPosterObjectStored=true`
  - auth / marketing / research `runtime_mode=shared-backend`
  - marketing `backends.minio.active=true`
- targeted auth rerun on 2026-04-21:
  - `PYTHONPATH="/home/ljr/SmartCloud-X/apps/auth-user-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" /home/ljr/SmartCloud-X/.venv/bin/pytest /home/ljr/SmartCloud-X/apps/auth-user-service/tests/test_auth_api.py -q` → `50 passed in 20.92s`
  - `/home/ljr/SmartCloud-X/.venv/bin/python -m compileall apps/auth-user-service/app` → passed
  - `uv run --with-requirements apps/auth-user-service/requirements.txt --with httpx --with pytest python -m pytest apps/auth-user-service/tests apps/marketing-service/tests apps/research-service/tests -q` → `124 passed in 65.84s`

## Blockers / Risks
- No active owned blocker remains.
- OpenAPI promotion remains outside this window because `openapi/` is a frozen zone; owner route reality is already implemented.
- Targeted auth rerun added stronger auth-owned proof instead of just repeating status claims:
  - internal validate-token already had explicit tests for allow-list rejection, stale/revoked/logout token denial, and this round added a direct denied-permissions ordering/complete-list assertion for `check-permission`
  - profile update now also has an explicit persistence test proving `avatar_url: null` clears only the avatar while preserving the other mutable fields across store reload
  - `/healthz` now also has a direct shared-backend branch test proving the MySQL/SQLite/Redis backend records switch coherently when auth runs off a non-SQLite database URL
  - `check-permission` now also rejects blank permission entries through the internal validation envelope, so caller allow-list/auth proof and contract hygiene are both explicit at the auth boundary

## Integration Points
- Shared auth env values (`SMARTCLOUD_JWT_SECRET`, issuer, audience) still let auth-issued user tokens work across research and marketing services.
- Strict downstream validation against `auth-user-service` internal `validate-token` remains available for marketing/research and was not regressed.
- The auth prune change is intentionally internal to `auth-user-service` store behavior; it does not alter public route contracts.
