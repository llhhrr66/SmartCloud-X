# SmartCloud-X Auth User Service

FastAPI baseline for user auth, profile management, admin auth bootstrap, and internal auth validation/check routes.

- Auth 关键路由与用户画像核心职责已接住，但 `user profile` 仍是账户画像，不是更广的业务画像。
- 当前 `user profile` 覆盖的是账号级资料（name/avatar/locale/time_zone），不是项目文档里更广义的业务用户画像。
- permission handling 在 auth 自有边界内已对齐 gateway/research/marketing 所需的 internal validate/check 合约；跨服务业务策略是否真正使用这些权限键仍取决于下游调用。
- README、状态文件、测试整体与当前 public/internal route 行为一致：本轮又补了 denied_permissions 顺序/完整性、avatar 清空后的跨重载持久化，以及 `/healthz` shared-backend 分支的直接测试证据。
- obvious missing tests 经本轮定点补齐后，RBAC、admin confirmation、invalidation、token lifecycle、profile 边界/持久化、health contract 已有直接证据覆盖；auth 自身边界内暂无新的明显测试空洞。

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
- Primary runtime persistence now uses `AUTH_USER_SERVICE_DATABASE_URL` with shared `SMARTCLOUD_MYSQL_DSN` fallback; local/test runs may still point that setting at SQLite.
- `AUTH_USER_SERVICE_BOOTSTRAP_PATH` (legacy alias: `AUTH_USER_SERVICE_DATA_PATH`) is now migration/bootstrap input only, not the authoritative runtime store.
- JWT signing uses shared `SMARTCLOUD_JWT_SECRET`
- Internal caller allow-list now honors the shared `ALLOWED_INTERNAL_CALLERS` env key and still accepts the legacy `AUTH_USER_SERVICE_ALLOWED_INTERNAL_CALLERS` override for compatibility.
- Public access tokens are accepted by the owned `research-service` and `marketing-service` baselines when they use the same shared secret and issuer/audience env values.
- `research-service` and `marketing-service` can also opt into strict current-state validation against `GET /internal/v1/auth/validate-token` by configuring their owned `*_AUTH_VALIDATION_MODE=*** and `*_AUTH_VALIDATE_TOKEN_URL` env vars.
- Refresh rotation, token revocation, verification codes, and password-reset challenges are now persisted in database tables; tampered session bindings and access-token payloads passed to logout are rejected.
- Logout now also revokes the caller's current access token immediately, so the same bearer token can no longer read `/auth/me` or pass internal token validation after logout.
- Internal auth routes require an allow-listed `X-Caller-Service`; missing or unlisted callers now fail with `403 AUTH_CALLER_FORBIDDEN` via the internal `ApiEnvelope.error` structure before token introspection proceeds.
- Internal `GET /internal/v1/auth/validate-token` now also enforces current subject token-version state and refresh-session revocation, so stale user/admin tokens do not validate after password rotation or explicit refresh-session logout.
- Internal `POST /internal/v1/auth/check-permission` returns `allowed=false` plus an exact `denied_permissions` list when gateway/research/marketing ask for permissions the subject does not currently hold, and blank permission keys are rejected with the internal validation envelope before authorization logic runs.
- Internal `POST /internal/v1/auth/invalidate-subject-cache` persists invalidation events to the auth database so downstream cache purges remain auditable across process restarts.
- Expired verification-code / password-challenge / refresh-session cleanup is now low-frequency best-effort maintenance instead of a hard requirement on every hot request path; runtime validity checks enforce expiration in their own lookups so remote MySQL lock contention no longer breaks login or refresh flows.
- Profile updates allow `avatar_url: null` to explicitly clear an existing avatar while keeping other mutable fields string-backed.
- Profile updates now trim persisted `name`, `locale`, `time_zone`, and string avatar URLs before saving, and Pydantic input limits keep those fields within reviewable bounds.
- Profile updates now also reject malformed avatar URLs, reject non-BCP47-style locale values, and reject unknown IANA time zones before persistence, so public error envelopes stay stable for downstream callers.
- Code-based login and reset-password flows now honor the matching account type (`mobile` vs `email`) when resolving the starter user account, so a code issued for one identifier type cannot be replayed against another field on the same user.
- Email verification-code and reset-password flows normalize trimmed or mixed-case email identifiers to the stored account form, so `Demo@SmartCloud.Local` and `demo@smartcloud.local` resolve to the same starter user.
- Re-sending a verification code inside the active TTL window now reuses the existing starter code record instead of silently extending the expiration time on each retry.

## Known limitations
- `user profile` is still account-centric only: name, avatar, locale, and time zone. Broader business portrait fields described by the platform document are not implemented in this service yet.
- Permission responses are current-state accurate for auth-owned users/admins, but cross-service business policy still depends on downstream services requesting the right permission keys.
- Admin bootstrap still uses the seeded local admin account and simple second-factor payload presence checks for non-password confirmation methods; it is not a full MFA system.
- `/healthz` reports runtime/backend evidence, but it does not actively ping MySQL/Redis/other dependencies.

## Validation commands used in this round
- `PYTHONPATH="/home/ljr/SmartCloud-X/apps/auth-user-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" /home/ljr/SmartCloud-X/.venv/bin/pytest /home/ljr/SmartCloud-X/apps/auth-user-service/tests/test_auth_api.py -q` → `50 passed in 20.92s`
- `/home/ljr/SmartCloud-X/.venv/bin/python -m compileall apps/auth-user-service/app` → passed
- `uv run --with-requirements apps/auth-user-service/requirements.txt --with httpx --with pytest python -m pytest apps/auth-user-service/tests apps/marketing-service/tests apps/research-service/tests -q` → `124 passed in 65.84s`

## Auth-owned evidence mapping
- internal validate-token: covered by `test_internal_auth_routes_validate_and_check_permissions`, `test_internal_validate_token_rejects_unlisted_caller_before_token_introspection`, `test_internal_validate_token_rejects_stale_user_access_token`, `test_internal_validate_token_rejects_revoked_refresh_token`, and `test_internal_validate_token_rejects_logged_out_access_token`
- caller allow-list: covered by `test_internal_routes_require_allowed_caller_header`, `test_internal_auth_requires_allowed_caller_header`, `test_internal_auth_rejects_unlisted_caller_header`, `test_internal_validate_token_rejects_unlisted_caller_before_token_introspection`, and `test_internal_auth_supports_shared_allowed_internal_callers_env`
- check-permission + denied_permissions: covered by `test_internal_check_permission_denies_missing_permissions`, `test_internal_check_permission_returns_all_denied_permissions_in_request_order`, and `test_internal_check_permission_returns_validation_error_for_blank_permission_entries`
- invalidate-subject-cache audit evidence: covered by `test_internal_invalidate_subject_cache_persists_event`
- profile validation/persistence edge coverage: covered by `test_profile_update_accepts_boundary_lengths_and_persists_exact_values`, `test_profile_update_trims_boundary_values_before_persisting`, `test_profile_update_accepts_explicit_avatar_clear_and_preserves_other_fields_across_reload`, `test_profile_update_rejects_invalid_avatar_url_and_returns_canonical_field_details`, `test_profile_update_rejects_null_for_non_nullable_fields_with_stable_error_envelope`, `test_profile_update_rejects_invalid_time_zone_and_locale_shapes`, `test_profile_update_rejects_unknown_time_zone_alias_with_stable_field_pointer`, `test_profile_update_trims_valid_locale_before_validation`, and `test_auth_database_persists_profile_updates_across_store_reload`; invalid avatar URL / locale / time_zone / blank admin captcha field errors now explicitly assert canonical `error.field`定位
- health contract evidence: covered by `test_healthz_reports_runtime_backend_evidence_for_local_fallback`, `test_healthz_contract_matches_auth_readme_runtime_notes`, and `test_healthz_shared_backend_mode_switches_mysql_record_when_database_url_is_non_sqlite`

## Broader owned-scope note
- auth 自身定点验证已绿。
- broader owned-scope 联跑当前已绿：`apps/auth-user-service/tests apps/marketing-service/tests apps/research-service/tests` 共 `113 passed`；因此这轮不再存在“被 marketing/research 联跑拖住”的 auth blocker。
