from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from pydantic import AnyHttpUrl
from sqlalchemy.exc import OperationalError


def test_user_password_login_and_profile_lifecycle(client) -> None:
    login_response = client.post(
    "/api/v1/auth/login",
    json={
    "login_type": "password",
    "account": "demo@smartcloud.local",
    "password": "Password123!",
    },
    )
    assert login_response.status_code == 200
    login_data = login_response.json()["data"]
    access_token = login_data["access_token"]
    refresh_token = login_data["refresh_token"]

    me_response = client.get(
    "/api/v1/auth/me",
    headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me_response.status_code == 200
    assert me_response.json()["data"]["email"] == "demo@smartcloud.local"

    profile_response = client.patch(
    "/api/v1/users/me",
    headers={"Authorization": f"Bearer {access_token}"},
    json={"name": "新版用户", "time_zone": "UTC"},
    )
    assert profile_response.status_code == 200
    assert profile_response.json()["data"]["name"] == "新版用户"
    assert profile_response.json()["data"]["time_zone"] == "UTC"

    change_password_response = client.post(
    "/api/v1/users/me/change-password",
    headers={"Authorization": f"Bearer {access_token}"},
    json={
    "old_password": "Password123!",
    "new_password": "Password456!",
    "confirm_password": "Password456!",
    },
    )
    assert change_password_response.status_code == 200

    stale_refresh = client.post(
    "/api/v1/auth/refresh",
    json={"refresh_token": refresh_token},
    )
    assert stale_refresh.status_code == 401

    relogin = client.post(
    "/api/v1/auth/login",
    json={
    "login_type": "password",
    "account": "demo@smartcloud.local",
    "password": "Password456!",
    },
    )
    assert relogin.status_code == 200


def test_send_code_sms_login_and_password_reset_flow(client) -> None:
    send_code = client.post(
    "/api/v1/auth/send-code",
    json={
    "scene": "login",
    "account": "13800000001",
    "account_type": "mobile",
    },
    )
    assert send_code.status_code == 200
    assert send_code.json()["data"]["expire_in"] == 300

    sms_login = client.post(
    "/api/v1/auth/login",
    json={
    "login_type": "sms",
    "account": "13800000001",
    "sms_code": "123456",
    },
    )
    assert sms_login.status_code == 200

    reset_send_code = client.post(
    "/api/v1/auth/send-code",
    json={
    "scene": "reset_password",
    "account": "demo@smartcloud.local",
    "account_type": "email",
    },
    )
    assert reset_send_code.status_code == 200

    forgot = client.post(
    "/api/v1/auth/password/forgot",
    json={
    "account": "demo@smartcloud.local",
    "account_type": "email",
    "verification_code": "123456",
    },
    )
    assert forgot.status_code == 200
    challenge_id = forgot.json()["data"]["challenge_id"]

    reset = client.post(
    "/api/v1/auth/password/reset",
    json={
    "challenge_id": challenge_id,
    "account": "demo@smartcloud.local",
    "verification_code": "123456",
    "new_password": "Password123!",
    "confirm_password": "Password123!",
    },
    )
    assert reset.status_code == 200
    assert reset.json()["data"]["success"] is True


def test_auth_alias_routes_cover_profile_and_password_recovery_flows(client) -> None:
    login_response = client.post(
    "/api/v1/auth/login",
    json={
    "login_type": "password",
    "account": "demo@smartcloud.local",
    "password": "Password123!",
    },
    )
    assert login_response.status_code == 200
    tokens = login_response.json()["data"]
    access_token = tokens["access_token"]

    profile = client.get(
    "/api/v1/auth/profile",
    headers={"Authorization": f"Bearer {access_token}"},
    )
    assert profile.status_code == 200
    assert profile.json()["data"]["user_id"] == "u_10001"

    updated_profile = client.patch(
    "/api/v1/auth/profile",
    headers={"Authorization": f"Bearer {access_token}"},
    json={"name": "兼容别名用户"},
    )
    assert updated_profile.status_code == 200
    assert updated_profile.json()["data"]["name"] == "兼容别名用户"

    avatar_set = client.patch(
    "/api/v1/auth/profile",
    headers={"Authorization": f"Bearer {access_token}"},
    json={"avatar_url": "https://cdn.smartcloud.local/avatars/u_10001.png"},
    )
    assert avatar_set.status_code == 200
    assert avatar_set.json()["data"]["avatar_url"] == "https://cdn.smartcloud.local/avatars/u_10001.png"

    avatar_cleared = client.patch(
    "/api/v1/auth/profile",
    headers={"Authorization": f"Bearer {access_token}"},
    json={"avatar_url": None},
    )
    assert avatar_cleared.status_code == 200
    assert avatar_cleared.json()["data"]["avatar_url"] is None

    change_password = client.post(
    "/api/v1/auth/change-password",
    headers={"Authorization": f"Bearer {access_token}"},
    json={
    "old_password": "Password123!",
    "new_password": "Password789!",
    "confirm_password": "Password789!",
    },
    )
    assert change_password.status_code == 200

    reset_send_code = client.post(
    "/api/v1/auth/send-code",
    json={
    "scene": "reset_password",
    "account": "demo@smartcloud.local",
    "account_type": "email",
    },
    )
    assert reset_send_code.status_code == 200

    forgot = client.post(
    "/api/v1/auth/forgot-password",
    json={
    "account": "demo@smartcloud.local",
    "account_type": "email",
    "verification_code": "123456",
    },
    )
    assert forgot.status_code == 200
    challenge_id = forgot.json()["data"]["challenge_id"]

    reset = client.post(
    "/api/v1/auth/reset-password",
    json={
    "challenge_id": challenge_id,
    "account": "demo@smartcloud.local",
    "verification_code": "123456",
    "new_password": "Password123!",
    "confirm_password": "Password123!",
    },
    )
    assert reset.status_code == 200


def test_openapi_publishes_promoted_auth_alias_routes(client) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/auth/profile" in paths
    assert "/api/v1/auth/forgot-password" in paths
    assert "/api/v1/auth/reset-password" in paths
    assert "/api/v1/auth/change-password" in paths
    assert "/api/v1/users/me/profile" not in paths


def test_public_validation_errors_return_canonical_error_envelope(client) -> None:
    response = client.post(
    "/api/v1/auth/login",
    json={
    "login_type": "password",
    "account": "demo@smartcloud.local",
    },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == 4001001
    assert payload["message"] == "request validation failed"
    assert payload["data"] is None


def test_verification_codes_are_single_use_for_login_and_password_recovery(client) -> None:
    send_login_code = client.post(
    "/api/v1/auth/send-code",
    json={
    "scene": "login",
    "account": "13800000001",
    "account_type": "mobile",
    },
    )
    assert send_login_code.status_code == 200

    first_sms_login = client.post(
    "/api/v1/auth/login",
    json={
    "login_type": "sms",
    "account": "13800000001",
    "sms_code": "123456",
    },
    )
    assert first_sms_login.status_code == 200

    reused_sms_login = client.post(
    "/api/v1/auth/login",
    json={
    "login_type": "sms",
    "account": "13800000001",
    "sms_code": "123456",
    },
    )
    assert reused_sms_login.status_code == 401

    send_reset_code = client.post(
    "/api/v1/auth/send-code",
    json={
    "scene": "reset_password",
    "account": "demo@smartcloud.local",
    "account_type": "email",
    },
    )
    assert send_reset_code.status_code == 200

    first_forgot = client.post(
    "/api/v1/auth/password/forgot",
    json={
    "account": "demo@smartcloud.local",
    "account_type": "email",
    "verification_code": "123456",
    },
    )
    assert first_forgot.status_code == 200
    challenge_id = first_forgot.json()["data"]["challenge_id"]

    reused_forgot = client.post(
    "/api/v1/auth/password/forgot",
    json={
    "account": "demo@smartcloud.local",
    "account_type": "email",
    "verification_code": "123456",
    },
    )
    assert reused_forgot.status_code == 400

    reset = client.post(
    "/api/v1/auth/password/reset",
    json={
    "challenge_id": challenge_id,
    "account": "demo@smartcloud.local",
    "verification_code": "123456",
    "new_password": "Password123!",
    "confirm_password": "Password123!",
    },
    )
    assert reset.status_code == 200


def test_code_login_requires_matching_account_type(client) -> None:
    send_email_code = client.post(
    "/api/v1/auth/send-code",
    json={
    "scene": "login",
    "account": "13800000001",
    "account_type": "email",
    },
    )
    assert send_email_code.status_code == 200

    email_login = client.post(
    "/api/v1/auth/login",
    json={
    "login_type": "email_code",
    "account": "13800000001",
    "email_code": "123456",
    },
    )
    assert email_login.status_code == 401


def test_send_code_reuses_active_window_and_normalizes_email_identifier(client, auth_store) -> None:
    first = client.post(
    "/api/v1/auth/send-code",
    json={
    "scene": "login",
    "account": " Demo@SmartCloud.Local ",
    "account_type": "email",
    },
    )
    assert first.status_code == 200

    stored_code = auth_store._snapshot.verification_codes[0]
    assert stored_code.account == "demo@smartcloud.local"
    initial_created_at = stored_code.created_at
    initial_expires_at = stored_code.expires_at

    second = client.post(
    "/api/v1/auth/send-code",
    json={
    "scene": "login",
    "account": "demo@smartcloud.local",
    "account_type": "email",
    },
    )
    assert second.status_code == 200
    assert len(auth_store._snapshot.verification_codes) == 1
    assert auth_store._snapshot.verification_codes[0].created_at == initial_created_at
    assert auth_store._snapshot.verification_codes[0].expires_at == initial_expires_at

    login = client.post(
    "/api/v1/auth/login",
    json={
    "login_type": "email_code",
    "account": "demo@smartcloud.local",
    "email_code": "123456",
    },
    )
    assert login.status_code == 200


def test_password_reset_honors_challenge_account_type(client) -> None:
    send_reset_code = client.post(
    "/api/v1/auth/send-code",
    json={
    "scene": "reset_password",
    "account": "13800000001",
    "account_type": "email",
    },
    )
    assert send_reset_code.status_code == 200

    forgot = client.post(
    "/api/v1/auth/forgot-password",
    json={
    "account": "13800000001",
    "account_type": "email",
    "verification_code": "123456",
    },
    )
    assert forgot.status_code == 200
    challenge_id = forgot.json()["data"]["challenge_id"]

    reset = client.post(
    "/api/v1/auth/reset-password",
    json={
    "challenge_id": challenge_id,
    "account": "13800000001",
    "verification_code": "123456",
    "new_password": "Password123!",
    "confirm_password": "Password123!",
    },
    )
    assert reset.status_code == 404


def test_admin_login_me_and_action_confirmation(client) -> None:
    login = client.post(
    "/api/v1/admin/auth/login",
    json={
    "username": "admin",
    "password": "Admin123!",
    "captcha_token": "captcha-ok",
    },
    )
    assert login.status_code == 200
    payload = login.json()["data"]
    access_token = payload["access_token"]
    assert payload["admin"]["admin_id"] == "admin_10001"

    me = client.get(
    "/api/v1/admin/auth/me",
    headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me.status_code == 200
    assert set(me.json()["data"]["permissions"]) >= {"admin:manage", "user:manage"}

    confirm = client.post(
    "/api/v1/admin/auth/action-confirmations",
    headers={"Authorization": f"Bearer {access_token}"},
    json={
    "action": "knowledge.reindex",
    "resource_scope": "kb:default",
    "verification_method": "password",
    "verification_payload": {"password": "Admin123!"},
    },
    )
    assert confirm.status_code == 200
    assert confirm.json()["data"]["confirm_token"].startswith("confirm_")


def test_admin_login_rejects_invalid_password(client) -> None:
    response = client.post(
    "/api/v1/admin/auth/login",
    json={
    "username": "admin",
    "password": "not-th...word",
    "captcha_token": "captcha-ok",
    },
    )
    assert response.status_code == 401
    payload = response.json()
    assert payload["code"] == 4010001
    assert payload["message"] == "invalid admin account or credential"


def test_admin_login_rejects_blank_captcha_token(client) -> None:
    response = client.post(
    "/api/v1/admin/auth/login",
    json={
    "username": "admin",
    "password": "Admin123!",
    "captcha_token": " ",
    },
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == 4001001
    assert payload["message"] == "request validation failed"
    assert payload["error"]["type"] == "validation_error"
    assert payload["error"]["field"] == "captcha_token"
    first_error = payload["error"]["details"]["errors"][0]
    assert first_error["type"] == "value_error"
    assert "captcha_token cannot be blank" in first_error["msg"]


def test_admin_action_confirmation_rejects_invalid_password(client) -> None:
    login = client.post(
    "/api/v1/admin/auth/login",
    json={
    "username": "admin",
    "password": "Admin123!",
    "captcha_token": "captcha-ok",
    },
    )
    assert login.status_code == 200
    access_token = login.json()["data"]["access_token"]

    confirm = client.post(
    "/api/v1/admin/auth/action-confirmations",
    headers={"Authorization": f"Bearer {access_token}"},
    json={
    "action": "knowledge.reindex",
    "resource_scope": "kb:default",
    "verification_method": "password",
    "verification_payload": {"password": "not-th...word"},
    },
    )
    assert confirm.status_code == 403


def test_admin_action_confirmation_requires_non_password_verification_payload(client) -> None:
    login = client.post(
    "/api/v1/admin/auth/login",
    json={
    "username": "admin",
    "password": "Admin123!",
    "captcha_token": "captcha-ok",
    },
    )
    assert login.status_code == 200
    access_token = login.json()["data"]["access_token"]

    confirm = client.post(
    "/api/v1/admin/auth/action-confirmations",
    headers={"Authorization": f"Bearer {access_token}"},
    json={
    "action": "knowledge.reindex",
    "resource_scope": "kb:default",
    "verification_method": "totp",
    "verification_payload": {},
    },
    )
    assert confirm.status_code == 403


def test_internal_auth_routes_validate_and_check_permissions(client, token_codec) -> None:
    user_login = client.post(
    "/api/v1/auth/login",
    json={
    "login_type": "password",
    "account": "demo@smartcloud.local",
    "password": "Password123!",
    },
    )
    token_to_validate = user_login.json()["data"]["access_token"]

    service_token = token_codec.issue_service_token("gateway-service").token
    headers = {
    "Authorization": f"Bearer {service_token}",
    "X-Caller-Service": "gateway-service",
    }

    validated = client.get(
    "/internal/v1/auth/validate-token",
    params={"token": token_to_validate},
    headers=headers,
    )
    assert validated.status_code == 200
    assert validated.json()["data"]["subject_type"] == "user"

    permission_check = client.post(
    "/internal/v1/auth/check-permission",
    headers=headers,
    json={
    "subject_type": "user",
    "subject_id": "u_10001",
    "permissions": ["user:research.read", "user:marketing.write"],
    },
    )
    assert permission_check.status_code == 200
    assert permission_check.json()["data"]["allowed"] is True

    invalidate = client.post(
    "/internal/v1/auth/invalidate-subject-cache",
    headers=headers,
    json={
    "subject_type": "user",
    "subject_ids": ["u_10001"],
    },
    )
    assert invalidate.status_code == 200
    assert invalidate.json()["data"]["invalidated_subject_ids"] == ["u_10001"]


def test_internal_check_permission_denies_missing_permissions(client, token_codec) -> None:
    service_token = token_codec.issue_service_token("gateway-service").token
    response = client.post(
    "/internal/v1/auth/check-permission",
    headers={
    "Authorization": f"Bearer {service_token}",
    "X-Caller-Service": "gateway-service",
    },
    json={
    "subject_type": "user",
    "subject_id": "u_10001",
    "permissions": ["user:research.read", "user:ops.write"],
    },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["allowed"] is False
    assert payload["denied_permissions"] == ["user:ops.write"]


def test_internal_check_permission_returns_all_denied_permissions_in_request_order(client, token_codec) -> None:
    service_token = token_codec.issue_service_token("gateway-service").token
    response = client.post(
        "/internal/v1/auth/check-permission",
        headers={
            "Authorization": f"Bearer {service_token}",
            "X-Caller-Service": "gateway-service",
        },
        json={
            "subject_type": "user",
            "subject_id": "u_10001",
            "permissions": ["user:ops.write", "user:research.read", "user:billing.manage", "user:ops.write"],
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["allowed"] is False
    assert payload["denied_permissions"] == ["user:ops.write", "user:billing.manage", "user:ops.write"]


def test_internal_check_permission_returns_validation_error_for_blank_permission_entries(client, token_codec) -> None:
    service_token = token_codec.issue_service_token("gateway-service").token
    response = client.post(
        "/internal/v1/auth/check-permission",
        headers={
            "Authorization": f"Bearer {service_token}",
            "X-Caller-Service": "gateway-service",
        },
        json={
            "subject_type": "user",
            "subject_id": "u_10001",
            "permissions": ["user:research.read", "   ", "user:marketing.write"],
        },
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert payload["error"]["message"] == "request validation failed"
    first_error = payload["error"]["details"]["errors"][0]
    assert first_error["loc"] == ["body"]
    assert first_error["type"] == "value_error"
    assert first_error["msg"] == "Value error, permissions entries cannot be blank"


def test_internal_validate_token_rejects_unlisted_caller_before_token_introspection(client, token_codec) -> None:
    user_token = token_codec.issue_access_token(
    subject_type="user",
    subject_id="u_10001",
    roles=["user"],
    permissions=["user:research.read"],
    tenant_id="default",
    ).token
    service_token = token_codec.issue_service_token("gateway-service").token

    response = client.get(
    "/internal/v1/auth/validate-token",
    params={"token": user_token},
    headers={
    "Authorization": f"Bearer {service_token}",
    "X-Caller-Service": "unknown-service",
    },
    )

    assert response.status_code == 403
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "AUTH_CALLER_FORBIDDEN"
    assert payload["error"]["message"] == "caller 'unknown-service' is not allowed"
    assert "gateway-service" in payload["error"]["details"]["allowed_callers"]


def test_internal_invalidate_subject_cache_persists_event(client, token_codec, auth_store) -> None:
    service_token = token_codec.issue_service_token("gateway-service").token
    response = client.post(
    "/internal/v1/auth/invalidate-subject-cache",
    headers={
    "Authorization": f"Bearer {service_token}",
    "X-Caller-Service": "gateway-service",
    },
    json={
    "subject_type": "user",
    "subject_ids": ["u_10001", "u_10002"],
    },
    )
    assert response.status_code == 200
    assert auth_store._snapshot.invalidation_log[-1].subject_type == "user"
    assert auth_store._snapshot.invalidation_log[-1].subject_ids == ["u_10001", "u_10002"]


def test_internal_auth_accepts_business_tools_service_as_default_caller(client, token_codec) -> None:
    token_to_validate = token_codec.issue_access_token(
    subject_type="user",
    subject_id="u_10001",
    roles=["user"],
    permissions=["user:research.read"],
    tenant_id="default",
    ).token

    service_token = token_codec.issue_service_token("business-tools-service").token
    response = client.get(
    "/internal/v1/auth/validate-token",
    params={"token": token_to_validate},
    headers={
    "Authorization": f"Bearer {service_token}",
    "X-Caller-Service": "business-tools-service",
    },
    )
    assert response.status_code == 200
    assert response.json()["data"]["subject_id"] == "u_10001"


def test_internal_auth_requires_matching_service_token(client, token_codec) -> None:
    wrong_service_token = token_codec.issue_service_token("orchestrator-service").token
    response = client.get(
    "/internal/v1/auth/validate-token",
    params={"token": "abc"},
    headers={
    "Authorization": f"Bearer {wrong_service_token}",
    "X-Caller-Service": "gateway-service",
    },
    )
    assert response.status_code == 401


def test_internal_auth_requires_allowed_caller_header(client, token_codec) -> None:
    service_token = token_codec.issue_service_token("gateway-service").token
    response = client.get(
    "/internal/v1/auth/validate-token",
    params={"token": "abc"},
    headers={"Authorization": f"Bearer {service_token}"},
    )
    assert response.status_code == 403


def test_internal_auth_rejects_unlisted_caller_header(client, token_codec) -> None:
    service_token = token_codec.issue_service_token("gateway-service").token
    response = client.get(
    "/internal/v1/auth/validate-token",
    params={"token": "abc"},
    headers={
    "Authorization": f"Bearer {service_token}",
    "X-Caller-Service": "bad-service",
    },
    )
    assert response.status_code == 403


def test_internal_auth_supports_shared_allowed_internal_callers_env(
    monkeypatch,
    service_modules,
    token_codec,
) -> None:
    monkeypatch.setenv("ALLOWED_INTERNAL_CALLERS", "gateway-service,custom-service")
    config = service_modules["config"]
    dependencies = importlib.import_module("app.dependencies")
    original_config_get_settings = config.get_settings
    original_dependencies_get_settings = dependencies.get_settings

    def _stub_settings():
        settings = original_config_get_settings().model_copy(deep=True)
        settings.allowed_internal_callers = ["gateway-service", "custom-service"]
        return settings

    config.get_settings = _stub_settings
    dependencies.get_settings = _stub_settings
    try:
        client = TestClient(service_modules["main"].app)
        service_token = token_codec.issue_service_token("custom-service").token
        response = client.get(
            "/internal/v1/auth/validate-token",
            params={
                "token": token_codec.issue_access_token(
                    subject_type="user",
                    subject_id="u_10001",
                    roles=["user"],
                    permissions=[],
                    tenant_id="default",
                ).token
            },
            headers={
                "Authorization": f"Bearer {service_token}",
                "X-Caller-Service": "custom-service",
            },
        )
    finally:
        config.get_settings = original_config_get_settings
        dependencies.get_settings = original_dependencies_get_settings

    assert response.status_code == 200


def test_internal_validate_token_rejects_stale_user_access_token(client, token_codec) -> None:
    login = client.post(
        "/api/v1/auth/login",
        json={
            "login_type": "password",
            "account": "demo@smartcloud.local",
            "password": "Password123!",
        },
    )
    assert login.status_code == 200
    access_token = login.json()["data"]["access_token"]
    service_token = token_codec.issue_service_token("gateway-service").token

    response = client.get(
        "/internal/v1/auth/validate-token",
        params={"token": access_token},
        headers={
            "Authorization": f"Bearer {service_token}",
            "X-Caller-Service": "gateway-service",
        },
    )
    assert response.status_code == 200

    change_password = client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "old_password": "Password123!",
            "new_password": "Password456!",
            "confirm_password": "Password456!",
        },
    )
    assert change_password.status_code == 200

    stale_check = client.get(
        "/internal/v1/auth/validate-token",
        params={"token": access_token},
        headers={
            "Authorization": f"Bearer {service_token}",
            "X-Caller-Service": "gateway-service",
        },
    )
    assert stale_check.status_code == 401


def test_internal_validate_token_rejects_revoked_refresh_token(client, token_codec) -> None:
    login = client.post(
    "/api/v1/auth/login",
    json={
    "login_type": "password",
    "account": "demo@smartcloud.local",
    "password": "Password123!",
    },
    )
    refresh_token = login.json()["data"]["refresh_token"]
    client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token}, headers={"Authorization": f"Bearer {login.json()['data']['access_token']}"})
    service_token = token_codec.issue_service_token("gateway-service").token
    response = client.get(
    "/internal/v1/auth/validate-token",
    params={"token": refresh_token},
    headers={
    "Authorization": f"Bearer {service_token}",
    "X-Caller-Service": "gateway-service",
    },
    )
    assert response.status_code == 401


def test_internal_validate_token_rejects_logged_out_access_token(client, token_codec) -> None:
    login = client.post(
    "/api/v1/auth/login",
    json={
    "login_type": "password",
    "account": "demo@smartcloud.local",
    "password": "Password123!",
    },
    )
    access_token = login.json()["data"]["access_token"]
    client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {access_token}"})
    service_token = token_codec.issue_service_token("gateway-service").token
    response = client.get(
    "/internal/v1/auth/validate-token",
    params={"token": access_token},
    headers={
    "Authorization": f"Bearer {service_token}",
    "X-Caller-Service": "gateway-service",
    },
    )
    assert response.status_code == 401


def test_logout_rejects_access_token_in_refresh_token_payload(client) -> None:
    login = client.post(
    "/api/v1/auth/login",
    json={
    "login_type": "password",
    "account": "demo@smartcloud.local",
    "password": "Password123!",
    },
    )
    access_token = login.json()["data"]["access_token"]
    response = client.post(
    "/api/v1/auth/logout",
    headers={"Authorization": f"Bearer {access_token}"},
    json={"refresh_token": access_token},
    )
    assert response.status_code == 401


def test_logout_rejects_other_users_refresh_token(client, token_codec) -> None:
    login = client.post(
    "/api/v1/auth/login",
    json={
    "login_type": "password",
    "account": "demo@smartcloud.local",
    "password": "Password123!",
    },
    )
    access_token = login.json()["data"]["access_token"]
    other_refresh = token_codec.issue_refresh_token(
    subject_type="user",
    subject_id="u_other",
    roles=["user"],
    permissions=[],
    tenant_id="default",
    ).token
    response = client.post(
    "/api/v1/auth/logout",
    headers={"Authorization": f"Bearer {access_token}"},
    json={"refresh_token": other_refresh},
    )
    assert response.status_code == 403


def test_refresh_rejects_mismatched_refresh_session_binding(client, auth_store) -> None:
    login = client.post(
    "/api/v1/auth/login",
    json={
    "login_type": "password",
    "account": "demo@smartcloud.local",
    "password": "Password123!",
    },
    )
    refresh_token = login.json()["data"]["refresh_token"]
    session = auth_store._snapshot.refresh_sessions[0]
    session.subject_id = "u_other"
    auth_store._persist()  # type: ignore[attr-defined]
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 401


def test_user_profile_and_change_password_routes_require_login(client) -> None:
    profile = client.get("/api/v1/auth/profile")
    assert profile.status_code == 401
    update = client.patch("/api/v1/auth/profile", json={"name": "匿名"})
    assert update.status_code == 401
    change_password = client.post(
    "/api/v1/auth/change-password",
    json={
    "old_password": "Password123!",
    "new_password": "Password456!",
    "confirm_password": "Password456!",
    },
    )
    assert change_password.status_code == 401


def test_admin_routes_require_admin_token(client) -> None:
    admin_me = client.get("/api/v1/admin/auth/me")
    assert admin_me.status_code == 401
    confirm = client.post(
    "/api/v1/admin/auth/action-confirmations",
    json={
    "action": "knowledge.reindex",
    "resource_scope": "kb:default",
    "verification_method": "password",
    "verification_payload": {"password": "Admin123!"},
    },
    )
    assert confirm.status_code == 401


def test_refresh_without_refresh_token_returns_validation_error(client) -> None:
    response = client.post("/api/v1/auth/refresh", json={})
    assert response.status_code == 400
    assert response.json()["code"] == 4001001


def test_auth_database_persists_profile_updates_across_store_reload(client, service_modules) -> None:
    login = client.post(
    "/api/v1/auth/login",
    json={
    "login_type": "password",
    "account": "demo@smartcloud.local",
    "password": "Password123!",
    },
    )
    assert login.status_code == 200
    access_token = login.json()["data"]["access_token"]

    update = client.patch(
    "/api/v1/auth/profile",
    headers={"Authorization": f"Bearer {access_token}"},
    json={"name": "数据库持久化用户"},
    )
    assert update.status_code == 200

    service_modules["store"].get_auth_store.cache_clear()
    reloaded_store = service_modules["store"].get_auth_store()
    assert reloaded_store.get_user_by_id("u_10001").name == "数据库持久化用户"


def test_profile_update_trims_strings_rejects_empty_payload_and_blank_values(client) -> None:
    login = client.post(
    "/api/v1/auth/login",
    json={
    "login_type": "password",
    "account": "demo@smartcloud.local",
    "password": "Password123!",
    },
    )
    assert login.status_code == 200
    access_token = login.json()["data"]["access_token"]

    update = client.patch(
    "/api/v1/auth/profile",
    headers={"Authorization": f"Bearer {access_token}"},
    json={"name": "  新名字  ", "locale": "  en-US  ", "time_zone": "  UTC  "},
    )
    assert update.status_code == 200
    payload = update.json()["data"]
    assert payload["name"] == "新名字"
    assert payload["locale"] == "en-US"
    assert payload["time_zone"] == "UTC"

    empty_update = client.patch(
    "/api/v1/auth/profile",
    headers={"Authorization": f"Bearer {access_token}"},
    json={},
    )
    assert empty_update.status_code == 400
    assert empty_update.json()["code"] == 4001001

    blank_name_update = client.patch(
    "/api/v1/auth/profile",
    headers={"Authorization": f"Bearer {access_token}"},
    json={"name": "   "},
    )
    assert blank_name_update.status_code == 400
    assert blank_name_update.json()["code"] == 4001001

    blank_avatar_update = client.patch(
    "/api/v1/auth/profile",
    headers={"Authorization": f"Bearer {access_token}"},
    json={"avatar_url": "   "},
    )
    assert blank_avatar_update.status_code == 400
    assert blank_avatar_update.json()["code"] == 4001001


def test_profile_update_rejects_overlong_fields_with_canonical_field_details(client) -> None:
    login = client.post(
    "/api/v1/auth/login",
    json={
    "login_type": "password",
    "account": "demo@smartcloud.local",
    "password": "Password123!",
    },
    )
    assert login.status_code == 200
    access_token = login.json()["data"]["access_token"]

    response = client.patch(
    "/api/v1/auth/profile",
    headers={"Authorization": f"Bearer {access_token}"},
    json={"name": "x" * 121},
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == 4001001
    assert payload["error"]["type"] == "validation_error"
    assert payload["error"]["field"] == "name"


def test_profile_update_trims_boundary_values_before_persisting(client, service_modules) -> None:
    login = client.post(
    "/api/v1/auth/login",
    json={
    "login_type": "password",
    "account": "demo@smartcloud.local",
    "password": "Password123!",
    },
    )
    assert login.status_code == 200
    access_token = login.json()["data"]["access_token"]

    raw_name = f" {'名' * 118} "
    raw_avatar = f"  https://cdn.smartcloud.local/{'b' * 2015}  "
    raw_locale = "  zh-Hans-CN  "
    raw_time_zone = "  Asia/Shanghai  "

    response = client.patch(
    "/api/v1/auth/profile",
    headers={"Authorization": f"Bearer {access_token}"},
    json={
    "name": raw_name,
    "avatar_url": raw_avatar,
    "locale": raw_locale,
    "time_zone": raw_time_zone,
    },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["name"] == "名" * 118
    assert payload["avatar_url"] == f"https://cdn.smartcloud.local/{'b' * 2015}"
    assert payload["locale"] == "zh-Hans-CN"
    assert payload["time_zone"] == "Asia/Shanghai"

    service_modules["store"].get_auth_store.cache_clear()
    reloaded_store = service_modules["store"].get_auth_store()
    persisted = reloaded_store.get_user_by_id("u_10001")
    assert persisted is not None
    assert persisted.name == "名" * 118
    assert persisted.avatar_url == f"https://cdn.smartcloud.local/{'b' * 2015}"
    assert persisted.locale == "zh-Hans-CN"
    assert persisted.time_zone == "Asia/Shanghai"


def test_profile_update_accepts_boundary_lengths_and_persists_exact_values(client, service_modules) -> None:
    login = client.post(
    "/api/v1/auth/login",
    json={
    "login_type": "password",
    "account": "demo@smartcloud.local",
    "password": "Password123!",
    },
    )
    assert login.status_code == 200
    access_token = login.json()["data"]["access_token"]

    payload = {
    "name": "名" * 120,
    "avatar_url": f"https://cdn.smartcloud.local/{'a' * 2019}",
    "locale": "zh-Hans-CN-abcde-fghij-klmno-pqr",
    "time_zone": "America/Argentina/ComodRivadavia",
    }

    assert len(payload["name"]) == 120
    assert len(payload["avatar_url"]) == 2048
    assert len(payload["locale"]) == 32
    assert len(payload["time_zone"]) <= 64

    response = client.patch(
    "/api/v1/auth/profile",
    headers={"Authorization": f"Bearer {access_token}"},
    json=payload,
    )
    if response.status_code != 200:
        error_payload = response.json()
        first_error = error_payload["error"]["details"]["errors"][0]
        raise AssertionError(f"unexpected validation error: {first_error}")
    assert response.status_code == 200
    profile = response.json()["data"]
    assert profile["name"] == payload["name"]
    assert profile["avatar_url"] == payload["avatar_url"]
    assert profile["locale"] == payload["locale"]
    assert profile["time_zone"] == payload["time_zone"]
    assert str(AnyHttpUrl(profile["avatar_url"])) == payload["avatar_url"]
    assert ZoneInfo(profile["time_zone"]).key == payload["time_zone"]

    service_modules["store"].get_auth_store.cache_clear()
    reloaded_store = service_modules["store"].get_auth_store()
    persisted = reloaded_store.get_user_by_id("u_10001")
    assert persisted is not None
    assert persisted.name == payload["name"]
    assert persisted.avatar_url == payload["avatar_url"]
    assert persisted.locale == payload["locale"]
    assert persisted.time_zone == payload["time_zone"]


def test_profile_update_rejects_invalid_avatar_url_and_returns_canonical_field_details(client) -> None:
    login = client.post(
    "/api/v1/auth/login",
    json={
    "login_type": "password",
    "account": "demo@smartcloud.local",
    "password": "Password123!",
    },
    )
    assert login.status_code == 200
    access_token = login.json()["data"]["access_token"]

    response = client.patch(
    "/api/v1/auth/profile",
    headers={"Authorization": f"Bearer {access_token}"},
    json={"avatar_url": "not-a-url"},
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == 4001001
    assert payload["message"] == "request validation failed"
    assert payload["error"]["type"] == "validation_error"
    assert payload["error"]["field"] == "avatar_url"
    error_entry = payload["error"]["details"]["errors"][0]
    assert error_entry["loc"] == ["body"]
    assert error_entry["msg"] == "Value error, avatar_url must be an absolute http(s) URL"


def test_profile_update_rejects_null_for_non_nullable_fields_with_stable_error_envelope(client) -> None:
    login = client.post(
    "/api/v1/auth/login",
    json={
    "login_type": "password",
    "account": "demo@smartcloud.local",
    "password": "Password123!",
    },
    )
    assert login.status_code == 200
    access_token = login.json()["data"]["access_token"]

    for field_name in ("name", "locale", "time_zone"):
        response = client.patch(
            "/api/v1/auth/profile",
            headers={"Authorization": f"Bearer {access_token}"},
            json={field_name: None},
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["code"] == 4001001
        assert payload["message"] == "request validation failed"
        assert payload["error"]["type"] == "validation_error"
        assert payload["error"]["field"] == field_name
        error_entry = payload["error"]["details"]["errors"][0]
        assert error_entry["loc"] == ["body"]
        assert error_entry["msg"] == f"Value error, {field_name} cannot be null"


def test_profile_update_accepts_explicit_avatar_clear_and_preserves_other_fields_across_reload(client, service_modules) -> None:
    service_modules["store"].get_auth_store().clear()
    login = client.post(
        "/api/v1/auth/login",
        json={
            "login_type": "password",
            "account": "demo@smartcloud.local",
            "password": "Password123!",
        },
    )
    assert login.status_code == 200
    access_token = login.json()["data"]["access_token"]

    seeded = client.patch(
        "/api/v1/auth/profile",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "name": "头像清空前",
            "avatar_url": "https://cdn.smartcloud.local/avatar-before-clear.png",
            "locale": "en-US",
            "time_zone": "UTC",
        },
    )
    assert seeded.status_code == 200

    cleared = client.patch(
        "/api/v1/auth/profile",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"avatar_url": None},
    )
    assert cleared.status_code == 200
    payload = cleared.json()["data"]
    assert payload["avatar_url"] is None
    assert payload["name"] == "头像清空前"
    assert payload["locale"] == "en-US"
    assert payload["time_zone"] == "UTC"

    service_modules["store"].get_auth_store.cache_clear()
    reloaded_store = service_modules["store"].get_auth_store()
    persisted = reloaded_store.get_user_by_id("u_10001")
    assert persisted is not None
    assert persisted.avatar_url is None
    assert persisted.name == "头像清空前"
    assert persisted.locale == "en-US"
    assert persisted.time_zone == "UTC"


def test_profile_update_rejects_invalid_time_zone_and_locale_shapes(client) -> None:
    login = client.post(
    "/api/v1/auth/login",
    json={
    "login_type": "password",
    "account": "demo@smartcloud.local",
    "password": "Password123!",
    },
    )
    assert login.status_code == 200
    access_token = login.json()["data"]["access_token"]

    invalid_time_zone = client.patch(
    "/api/v1/auth/profile",
    headers={"Authorization": f"Bearer {access_token}"},
    json={"time_zone": "Mars/OlympusMons"},
    )
    assert invalid_time_zone.status_code == 400
    invalid_time_zone_payload = invalid_time_zone.json()
    assert invalid_time_zone_payload["code"] == 4001001
    assert invalid_time_zone_payload["error"]["type"] == "validation_error"
    assert invalid_time_zone_payload["error"]["field"] == "time_zone"
    tz_error = invalid_time_zone_payload["error"]["details"]["errors"][0]
    assert tz_error["loc"] == ["body"]
    assert tz_error["msg"] == "Value error, time_zone must be a valid IANA time zone"

    invalid_locale = client.patch(
    "/api/v1/auth/profile",
    headers={"Authorization": f"Bearer {access_token}"},
    json={"locale": "中文"},
    )
    assert invalid_locale.status_code == 400
    invalid_locale_payload = invalid_locale.json()
    assert invalid_locale_payload["code"] == 4001001
    assert invalid_locale_payload["error"]["type"] == "validation_error"
    assert invalid_locale_payload["error"]["field"] == "locale"
    locale_error = invalid_locale_payload["error"]["details"]["errors"][0]
    assert locale_error["loc"] == ["body"]
    assert locale_error["msg"] == "Value error, locale must use BCP 47 style tags"


def test_profile_update_rejects_unknown_time_zone_alias_with_stable_field_pointer(client) -> None:
    login = client.post(
    "/api/v1/auth/login",
    json={
    "login_type": "password",
    "account": "demo@smartcloud.local",
    "password": "Password123!",
    },
    )
    assert login.status_code == 200
    access_token = login.json()["data"]["access_token"]

    response = client.patch(
        "/api/v1/auth/profile",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"time_zone": "UTC+8"},
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["field"] == "time_zone"


def test_profile_update_trims_valid_locale_before_validation(client) -> None:
    login = client.post(
    "/api/v1/auth/login",
    json={
    "login_type": "password",
    "account": "demo@smartcloud.local",
    "password": "Password123!",
    },
    )
    assert login.status_code == 200
    access_token = login.json()["data"]["access_token"]

    response = client.patch(
        "/api/v1/auth/profile",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"locale": "  en-US  "},
    )
    assert response.status_code == 200
    assert response.json()["data"]["locale"] == "en-US"


def test_healthz_reports_runtime_backend_evidence_for_local_fallback(client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    payload = response.json()

    assert payload["status"] == "ok"
    assert payload["service"] == "auth-user-service"
    assert payload["runtime_mode"] == "local-fallback"
    assert payload["backends"]["sqlite"]["kind"] == "sqlite"
    assert payload["backends"]["sqlite"]["role"] == "fallback"
    assert payload["backends"]["sqlite"]["configured"] is True
    assert payload["backends"]["sqlite"]["active"] is True
    assert payload["backends"]["sqlite"]["restart_durable"] is True
    assert payload["backends"]["sqlite"]["required_for_release"] is False
    assert payload["backends"]["sqlite"]["evidence"] == "engine-dialect"
    assert payload["backends"]["mysql"]["kind"] == "mysql"
    assert payload["backends"]["mysql"]["configured"] is False
    assert payload["backends"]["mysql"]["active"] is False
    assert payload["backends"]["mysql"]["required_for_release"] is True
    assert payload["backends"]["redis"]["kind"] == "redis"
    assert payload["backends"]["redis"]["role"] == "optional"
    assert payload["backends"]["redis"]["configured"] is False
    assert payload["backends"]["redis"]["active"] is False


def test_healthz_contract_matches_auth_readme_runtime_notes(client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    payload = response.json()

    assert set(payload.keys()) == {"status", "service", "runtime_mode", "backends"}
    assert set(payload["backends"].keys()) == {"mysql", "sqlite", "redis"}
    assert payload["backends"]["mysql"]["role"] == "primary"
    assert payload["backends"]["mysql"]["fallback"] == "sqlite://local-fallback"
    assert payload["backends"]["sqlite"]["notes"] == "local/test compatibility database derived from owner config"
    assert payload["backends"]["redis"]["notes"] == (
    "declared config only; current auth runtime persists revocation and session state in database tables"
    )


def test_healthz_shared_backend_mode_switches_mysql_record_when_database_url_is_non_sqlite(service_modules) -> None:
    config = service_modules["config"]
    main = service_modules["main"]
    routes = importlib.import_module("app.routes")
    original_get_settings = config.get_settings
    original_main_get_settings = main.get_settings
    original_routes_get_settings = routes.get_settings

    def _stub_settings():
        settings = original_get_settings().model_copy(deep=True)
        settings.database_url = "mysql+pymysql://smartcloud:secret@127.0.0.1:3306/smartcloud"
        settings.bootstrap_path = None
        settings.redis_url = "redis://127.0.0.1:6379/0"
        return settings

    config.get_settings = _stub_settings
    main.get_settings = _stub_settings
    routes.get_settings = _stub_settings
    try:
        payload = routes.healthz()
    finally:
        config.get_settings = original_get_settings
        main.get_settings = original_main_get_settings
        routes.get_settings = original_routes_get_settings

    assert payload["runtime_mode"] == "shared-backend"
    assert payload["backends"]["mysql"]["configured"] is True
    assert payload["backends"]["mysql"]["active"] is True
    assert payload["backends"]["mysql"]["restart_durable"] is True
    assert payload["backends"]["mysql"]["evidence"] == "engine-dialect"
    assert payload["backends"]["mysql"].get("notes") is None
    assert payload["backends"]["sqlite"]["configured"] is False
    assert payload["backends"]["sqlite"]["active"] is False
    assert payload["backends"]["sqlite"]["fallback"] is None
    assert payload["backends"]["redis"]["configured"] is True


def test_prune_expired_is_best_effort_on_operational_error(auth_store, monkeypatch) -> None:
    class _FailingTransaction:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _FailingSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def begin(self):
            return _FailingTransaction()

        def execute(self, *_args, **_kwargs):
            raise OperationalError("DELETE FROM auth_refresh_sessions", {}, Exception("lock wait timeout"))

    monkeypatch.setattr(auth_store, "_session", lambda: _FailingSession())
    auth_store._prune_expired()


def test_get_refresh_session_ignores_expired_row_when_prune_is_skipped(auth_store, monkeypatch) -> None:
    expired_at = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    auth_store.save_refresh_session(
        token_id="expired-refresh",
        subject_type="user",
        subject_id="u_10001",
        token_version=1,
        expires_at=expired_at,
    )

    monkeypatch.setattr(auth_store, "_prune_expired", lambda: None)
    assert auth_store.get_refresh_session("expired-refresh") is None


def test_issue_verification_code_replaces_expired_scoped_row_when_prune_is_skipped(auth_store, monkeypatch) -> None:
    initial = auth_store.issue_verification_code(scene="login", account="demo@smartcloud.local", account_type="email")
    stored = auth_store._snapshot.verification_codes[0]
    stored.created_at = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    stored.expires_at = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    auth_store._persist()  # type: ignore[attr-defined]

    monkeypatch.setattr(auth_store, "_prune_expired", lambda: None)
    refreshed = auth_store.issue_verification_code(scene="login", account="demo@smartcloud.local", account_type="email")

    assert refreshed.expires_at != initial.expires_at
    assert len(auth_store._snapshot.verification_codes) == 1
    assert auth_store._snapshot.verification_codes[0].created_at != stored.created_at
