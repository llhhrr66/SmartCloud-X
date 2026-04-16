# Supervisor Auth Marketing Research Status

## Status
- phase: done
- updated at: 2026-04-16T14:41:58+08:00
- owned scope: `apps/auth-user-service/`, `apps/research-service/`, `apps/marketing-service/`

## Completed
- `auth-user-service` remains a usable FastAPI baseline for login, send-code, refresh, logout, forgot/reset password, me/profile/change-password, admin bootstrap, and internal auth validation/check flows.
- `research-service` remains a usable FastAPI baseline for task create/list/detail plus published status/result helper routes and the owner-local report alias for placeholder output retrieval.
- `marketing-service` remains a usable FastAPI baseline for currently active published campaign listing, copy generation, promotion-link placeholder generation, generated copy/promotion-link history/detail reads, poster task create/list/detail, and published poster-result helper routes.
- `research-service` and `marketing-service` now scope task visibility plus async Idempotency-Key replay by authenticated `(tenant_id, user_id)` instead of `user_id` alone.
- Added regression coverage proving same-user cross-tenant research and poster requests do not collide, leak task detail, or replay the wrong async task.
- Added regression coverage proving generated marketing copy and promotion-link artifacts can be listed or fetched later and remain isolated by authenticated tenant scope.
- Fixed the remaining marketing user-surface spec drift so list and generation routes now reject draft, future, and expired campaigns instead of checking `published` status alone.
- Reset the owned repo-local auth/research/marketing JSON stores to clean starter data so local baseline runs no longer inherit stale refresh sessions, stale research tasks, or invalid draft-marketing artifacts.

## Self-review
- reviewed the marketing campaign visibility logic after the active-window fix to ensure the same user-surface rule is applied consistently to listing, copy generation, promotion-link generation, and poster creation.
- confirmed the new future-dated campaign regression covers both browse and write behavior without widening the owned route surface.
- after that follow-up review pass, no additional code defects were found in the owned changes.

## Validation
- `.venv/bin/python -m py_compile apps/auth-user-service/app/*.py apps/auth-user-service/app/core/*.py apps/auth-user-service/tests/*.py apps/research-service/app/*.py apps/research-service/app/core/*.py apps/research-service/tests/*.py apps/marketing-service/app/*.py apps/marketing-service/app/core/*.py apps/marketing-service/tests/*.py`
- `.venv/bin/pytest apps/auth-user-service/tests apps/research-service/tests apps/marketing-service/tests -q` → `59 passed in 10.27s`

## Blockers / Risks
- no active implementation blocker remains inside owned directories.
- optional repo-level integration validation at `tests/integration/test_auth_marketing_research_flow.py` could not be collected in `.venv` because `jsonschema` is not installed.
- all three services still use local JSON persistence and shared-secret token verification, so they remain practical starter baselines rather than production multi-instance storage or centralized token-introspection deployments.

## Integration Points
- `auth-user-service` issues the starter bearer tokens that `research-service` and `marketing-service` validate locally via the shared SmartCloud auth env values.
- `auth-user-service` internal routes honor the shared `ALLOWED_INTERNAL_CALLERS` key, so downstream deployments should prefer that frozen runtime setting instead of auth-local env naming.
- downstream trusted callers can use `auth-user-service` internal validation/check routes for current-state token and permission checks, including stale-token rejection after logout, password rotation, or refresh-session revocation.
- `research-service` and `marketing-service` can opt into those current-state checks directly by setting `RESEARCH_SERVICE_AUTH_VALIDATION_MODE=strict` or `MARKETING_SERVICE_AUTH_VALIDATION_MODE=strict` plus the corresponding `*_AUTH_VALIDATE_TOKEN_URL`.
- downstream callers must still send `Idempotency-Key` on `POST /api/v1/research/tasks` and `POST /api/v1/marketing/posters`; replay/conflict handling is now isolated to the authenticated tenant/user context instead of being shared across tenants.
- `marketing-service` now exposes only currently active published campaign ids on the user surface, so downstream clients should treat draft, future, and expired campaign ids as unsupported inputs for browse or generation flows.
- downstream clients can now read generated marketing copy and promotion-link artifacts back from `marketing-service` without relying solely on the original POST response or browser-local storage.
