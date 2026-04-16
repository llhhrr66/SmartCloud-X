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
            "new_password": "Password789!",
            "confirm_password": "Password789!",
        },
    )
    assert reset.status_code == 404

    login_with_original_password = client.post(
        "/api/v1/auth/login",
        json={
            "login_type": "password",
            "account": "demo@smartcloud.local",
            "password": "Password123!",
        },
    )
    assert login_with_original_password.status_code == 200


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
    access_token = login.json()["data"]["access_token"]

    me = client.get(
        "/api/v1/admin/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me.status_code == 200
    assert me.json()["data"]["admin_id"] == "admin_10001"

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
        params={"token": "invalid"},
        headers={
            "Authorization": f"Bearer {wrong_service_token}",
            "X-Caller-Service": "gateway-service",
        },
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_internal_auth_requires_allowed_caller_header(client, token_codec) -> None:
    service_token = token_codec.issue_service_token("gateway-service").token
    response = client.get(
        "/internal/v1/auth/validate-token",
        params={"token": service_token},
        headers={"Authorization": f"Bearer {service_token}"},
    )
    assert response.status_code == 403
    payload = response.json()
    assert payload["error"]["code"] == "AUTH_CALLER_FORBIDDEN"
    assert payload["error"]["details"]["header"] == "X-Caller-Service"


def test_internal_auth_rejects_unlisted_caller_header(client, token_codec) -> None:
    service_token = token_codec.issue_service_token("gateway-service").token
    response = client.get(
        "/internal/v1/auth/validate-token",
        params={"token": service_token},
        headers={
            "Authorization": f"Bearer {service_token}",
            "X-Caller-Service": "unknown-service",
        },
    )
    assert response.status_code == 403
    payload = response.json()
    assert payload["error"]["code"] == "AUTH_CALLER_FORBIDDEN"
    assert "gateway-service" in payload["error"]["details"]["allowed_callers"]


def test_internal_auth_supports_shared_allowed_internal_callers_env(
    client,
    token_codec,
    service_modules,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ALLOWED_INTERNAL_CALLERS", "qa-probe-service")
    monkeypatch.delenv("AUTH_USER_SERVICE_ALLOWED_INTERNAL_CALLERS", raising=False)
    service_modules["config"].get_settings.cache_clear()

    user_token = token_codec.issue_access_token(
        subject_type="user",
        subject_id="u_10001",
        roles=["user"],
        permissions=["user:research.read"],
        tenant_id="default",
    ).token
    service_token = token_codec.issue_service_token("qa-probe-service").token

    response = client.get(
        "/internal/v1/auth/validate-token",
        params={"token": user_token},
        headers={
            "Authorization": f"Bearer {service_token}",
            "X-Caller-Service": "qa-probe-service",
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["subject_id"] == "u_10001"


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
    service_headers = {
        "Authorization": f"Bearer {service_token}",
        "X-Caller-Service": "gateway-service",
    }

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

    validated = client.get(
        "/internal/v1/auth/validate-token",
        params={"token": access_token},
        headers=service_headers,
    )
    assert validated.status_code == 401
    assert validated.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_internal_validate_token_rejects_revoked_refresh_token(client, token_codec) -> None:
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
    refresh_token = login.json()["data"]["refresh_token"]

    logout = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"refresh_token": refresh_token},
    )
    assert logout.status_code == 200

    service_token = token_codec.issue_service_token("gateway-service").token
    validated = client.get(
        "/internal/v1/auth/validate-token",
        params={"token": refresh_token},
        headers={
            "Authorization": f"Bearer {service_token}",
            "X-Caller-Service": "gateway-service",
        },
    )
    assert validated.status_code == 401
    assert validated.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_internal_validate_token_rejects_logged_out_access_token(client, token_codec) -> None:
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
    refresh_token = login.json()["data"]["refresh_token"]

    logout = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"refresh_token": refresh_token},
    )
    assert logout.status_code == 200

    service_token = token_codec.issue_service_token("gateway-service").token
    validated = client.get(
        "/internal/v1/auth/validate-token",
        params={"token": access_token},
        headers={
            "Authorization": f"Bearer {service_token}",
            "X-Caller-Service": "gateway-service",
        },
    )
    assert validated.status_code == 401
    assert validated.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_logout_rejects_access_token_in_refresh_token_payload(client) -> None:
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

    logout_response = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {login_data['access_token']}"},
        json={"refresh_token": login_data["access_token"]},
    )
    assert logout_response.status_code == 401
    assert logout_response.json()["code"] == 4010002

    refresh_response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": login_data["refresh_token"]},
    )
    assert refresh_response.status_code == 200


def test_logout_revokes_current_access_token_for_user_routes(client) -> None:
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

    logout_response = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {login_data['access_token']}"},
        json={"refresh_token": login_data["refresh_token"]},
    )
    assert logout_response.status_code == 200

    me_response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login_data['access_token']}"},
    )
    assert me_response.status_code == 401
    assert me_response.json()["code"] == 4010002


def test_refresh_rejects_when_refresh_session_subject_binding_is_tampered(client, token_codec, settings, auth_store) -> None:
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "login_type": "password",
            "account": "demo@smartcloud.local",
            "password": "Password123!",
        },
    )
    assert login_response.status_code == 200
    refresh_token = login_response.json()["data"]["refresh_token"]

    claims = token_codec.decode(refresh_token, audience=settings.auth_audience)
    refresh_session = auth_store.get_refresh_session(str(claims["jti"]))
    assert refresh_session is not None
    refresh_session.subject_id = "u_99999"
    auth_store._persist()  # type: ignore[attr-defined]

    refresh_response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_response.status_code == 401
    assert refresh_response.json()["code"] == 4010002
