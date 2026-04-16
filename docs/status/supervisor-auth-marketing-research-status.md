# Supervisor Auth Marketing Research Status

## Status
- phase: done-real-infra-migration
- updated at: 2026-04-16T18:13:48+08:00
- owned scope: `apps/auth-user-service/`, `apps/research-service/`, `apps/marketing-service/`
- runtime stance: MySQL-first database-backed services with SQLite fallback only for local/test compatibility when DATABASE_URL is unset

## Completed
- `auth-user-service` now uses database tables for authoritative user/admin/session/challenge/revocation state while preserving the existing login, send-code, refresh, logout, forgot/reset password, me/profile/change-password, admin bootstrap, and internal auth routes.
- `research-service` now uses database tables for research tasks and idempotency records; detail/status/result/report flows read persisted task state instead of repo-local JSON snapshots.
- `marketing-service` now uses database tables for campaigns, generated copy, promotion links, poster tasks, and poster idempotency, and it includes MinIO-friendly poster placeholder upload support.
- Legacy `*_DATA_PATH` inputs are now treated as bootstrap/migration fixtures and also derive a colocated SQLite database path when `*_DATABASE_URL` / shared `SMARTCLOUD_MYSQL_DSN` is not set, which keeps local and integration harnesses working without JSON runtime dependence.
- Added database-persistence regression coverage proving auth profile changes, research tasks, and marketing generated copy survive store reloads.

## Self-review
- found and fixed a compatibility defect where old `*_DATA_PATH`-only harnesses no longer influenced runtime persistence after the migration; configs now derive a SQLite database path from that legacy input when no explicit DATABASE_URL is present.
- found and fixed naive/aware datetime handling in the new database stores so running/completed task transitions and campaign visibility behave correctly under SQLite-backed local tests.
- after those fixes, reran owned compile/tests plus the repo integration flow and found no remaining defects in owned scope.

## Validation
- `.venv/bin/python -m py_compile apps/auth-user-service/app/*.py apps/auth-user-service/app/core/*.py apps/auth-user-service/tests/*.py apps/research-service/app/*.py apps/research-service/app/core/*.py apps/research-service/tests/*.py apps/marketing-service/app/*.py apps/marketing-service/app/core/*.py apps/marketing-service/tests/*.py`
- `.venv/bin/pytest apps/auth-user-service/tests apps/research-service/tests apps/marketing-service/tests tests/integration/test_auth_marketing_research_flow.py -q` → `63 passed in 36.12s`

## Blockers / Risks
- no active implementation blocker remains inside owned directories.
- production rollout still depends on real MySQL and optional MinIO environment wiring; local and integration validation used SQLite fallback when DATABASE_URL was not explicitly pointed at MySQL.
- Redis remains optional in the owned baseline; authoritative runtime state is now durable in database tables, and Redis-specific acceleration can be layered on without reintroducing JSON runtime stores.

## Integration Points
- shared auth env values (`SMARTCLOUD_JWT_SECRET`, issuer, audience) still let auth-issued user tokens work across research and marketing services.
- downstream harnesses that still pass only `*_DATA_PATH` continue to work because the owned services now derive a colocated SQLite database from that legacy input while keeping the JSON file itself as bootstrap data only.
- strict downstream auth validation against `auth-user-service` internal `validate-token` remains available and now runs on top of database-backed auth state.
- `marketing-service` poster results use `MARKETING_SERVICE_MINIO_*` / shared `SMARTCLOUD_MINIO_*` when available and otherwise preserve the existing public poster URL contract.
