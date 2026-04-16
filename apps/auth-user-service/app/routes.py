from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.dependencies import (
    build_trace_context,
    require_admin_subject,
    require_internal_subject,
    require_user_subject,
)
from app.models import (
    AdminActionConfirmationRequest,
    AdminActionConfirmationResponseData,
    AdminLoginRequest,
    AdminLoginResponseData,
    ChangePasswordRequest,
    CurrentSubject,
    ForgotPasswordRequest,
    ForgotPasswordResponseData,
    InvalidateSubjectCacheRequest,
    InvalidateSubjectCacheResponseData,
    InternalTokenValidationResponseData,
    LoginRequest,
    LoginResponseData,
    LogoutRequest,
    OperationStatusData,
    PermissionCheckRequest,
    PermissionCheckResponseData,
    RefreshTokenRequest,
    RefreshTokenResponseData,
    ResetPasswordRequest,
    SendCodeRequest,
    SendCodeResponseData,
    ServiceError,
    UserProfileUpdateRequest,
    ApiEnvelope,
    CanonicalErrorDetail,
    CanonicalErrorEnvelope,
    CanonicalSuccessEnvelope,
    now_timestamp_ms,
)
from app.security import TokenError, get_token_codec
from app.store import UNSET, get_auth_store, normalize_account_identifier


health_router = APIRouter(tags=["health"])
router = APIRouter(tags=["user-auth"])
admin_router = APIRouter(tags=["admin-auth"])
internal_router = APIRouter(tags=["internal-auth"])
_settings = get_settings()


@health_router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "auth-user-service"}


@router.post("/auth/login")
def login(payload: LoginRequest, request: Request) -> JSONResponse:
    trace = build_trace_context(request)
    store = get_auth_store()
    user = None

    if payload.login_type == "password":
        user = store.get_user_by_account(payload.account)
        if user is None:
            raise ServiceError(401, 4010002, "invalid account or credential", public=True)
        if not store.verify_user_password(user, payload.password or ""):
            raise ServiceError(401, 4010002, "invalid account or credential", public=True)
    elif payload.login_type == "sms":
        user = store.get_user_by_account_type(payload.account, "mobile")
        if user is None:
            raise ServiceError(401, 4010002, "invalid account or credential", public=True)
        if not store.consume_verification_code(
            scene="login",
            account=payload.account,
            account_type="mobile",
            code=payload.sms_code or "",
        ):
            raise ServiceError(401, 4010002, "invalid verification code", public=True)
    elif payload.login_type == "email_code":
        user = store.get_user_by_account_type(payload.account, "email")
        if user is None:
            raise ServiceError(401, 4010002, "invalid account or credential", public=True)
        if not store.consume_verification_code(
            scene="login",
            account=payload.account,
            account_type="email",
            code=payload.email_code or "",
        ):
            raise ServiceError(401, 4010002, "invalid verification code", public=True)

    access_token = get_token_codec().issue_access_token(
        subject_type="user",
        subject_id=user.user_id,
        roles=user.roles,
        permissions=user.permissions,
        tenant_id=user.tenant_id,
        token_version=user.token_version,
    )
    refresh_token = get_token_codec().issue_refresh_token(
        subject_type="user",
        subject_id=user.user_id,
        roles=user.roles,
        permissions=user.permissions,
        tenant_id=user.tenant_id,
        token_version=user.token_version,
    )
    store.save_refresh_session(
        token_id=str(refresh_token.claims["jti"]),
        subject_type="user",
        subject_id=user.user_id,
        token_version=user.token_version,
        expires_at=refresh_token.expires_at.isoformat(),
    )
    response = LoginResponseData(
        access_token=access_token.token,
        refresh_token=refresh_token.token,
        expires_in=access_token.expires_in,
        user=user.to_public_profile(),
    )
    return _canonical_success(trace.request_id or "", response.model_dump(mode="json"))


@router.post("/auth/send-code")
def send_code(payload: SendCodeRequest, request: Request) -> JSONResponse:
    trace = build_trace_context(request)
    record = get_auth_store().issue_verification_code(
        scene=payload.scene,
        account=payload.account,
        account_type=payload.account_type,
    )
    response = SendCodeResponseData(
        scene=payload.scene,
        masked_account=_mask_account(record.account, payload.account_type),
        expire_in=max(int((_parse_iso(record.expires_at) - _parse_iso(record.created_at)).total_seconds()), 1),
    )
    return _canonical_success(trace.request_id or "", response.model_dump(mode="json"))


@router.post("/auth/refresh")
def refresh_token(payload: RefreshTokenRequest, request: Request) -> JSONResponse:
    trace = build_trace_context(request)
    try:
        claims = get_token_codec().decode(payload.refresh_token, audience=_settings.auth_audience)
    except TokenError as exc:
        raise ServiceError(401, 4010002, str(exc), public=True) from exc
    if claims.get("subject_type") != "user" or claims.get("token_type") != "refresh":
        raise ServiceError(401, 4010002, "invalid refresh token", public=True)
    subject_id = str(claims.get("subject_id") or claims.get("sub") or "")
    token_version = int(claims.get("ver") or 0)
    session = get_auth_store().get_refresh_session(str(claims.get("jti") or ""))
    if session is None or session.revoked:
        raise ServiceError(401, 4010002, "refresh token has been revoked", public=True)
    if session.subject_type != "user" or session.subject_id != subject_id or session.token_version != token_version:
        raise ServiceError(401, 4010002, "invalid refresh token", public=True)
    user = get_auth_store().get_user_by_id(subject_id)
    if user is None or user.token_version != token_version:
        raise ServiceError(401, 4010002, "refresh token is no longer valid", public=True)

    get_auth_store().revoke_refresh_session(session.token_id)
    access_token = get_token_codec().issue_access_token(
        subject_type="user",
        subject_id=user.user_id,
        roles=user.roles,
        permissions=user.permissions,
        tenant_id=user.tenant_id,
        token_version=user.token_version,
    )
    refresh_token_next = get_token_codec().issue_refresh_token(
        subject_type="user",
        subject_id=user.user_id,
        roles=user.roles,
        permissions=user.permissions,
        tenant_id=user.tenant_id,
        token_version=user.token_version,
    )
    get_auth_store().save_refresh_session(
        token_id=str(refresh_token_next.claims["jti"]),
        subject_type="user",
        subject_id=user.user_id,
        token_version=user.token_version,
        expires_at=refresh_token_next.expires_at.isoformat(),
    )
    response = RefreshTokenResponseData(
        access_token=access_token.token,
        refresh_token=refresh_token_next.token,
        expires_in=access_token.expires_in,
        user=user.to_public_profile(),
    )
    return _canonical_success(trace.request_id or "", response.model_dump(mode="json"))


@router.get("/auth/me")
@router.get("/auth/profile")
@router.get("/users/me/profile", include_in_schema=False)
def get_current_user(
    request: Request,
    subject: CurrentSubject = Depends(require_user_subject()),
) -> JSONResponse:
    trace = build_trace_context(request)
    user = get_auth_store().get_user_by_id(subject.subject_id)
    if user is None:
        raise ServiceError(401, 4010002, "user not found", public=True)
    return _canonical_success(trace.request_id or "", user.to_public_profile().model_dump(mode="json"))


@router.post("/auth/logout")
def logout(
    request: Request,
    payload: LogoutRequest | None = None,
    subject: CurrentSubject = Depends(require_user_subject()),
) -> JSONResponse:
    trace = build_trace_context(request)
    store = get_auth_store()
    if payload and payload.refresh_token:
        try:
            claims = get_token_codec().decode(payload.refresh_token, audience=_settings.auth_audience)
        except TokenError as exc:
            raise ServiceError(401, 4010002, str(exc), public=True) from exc
        if claims.get("subject_type") != "user" or claims.get("token_type") != "refresh":
            raise ServiceError(401, 4010002, "refresh token required", public=True)
        if str(claims.get("subject_id") or claims.get("sub") or "") != subject.subject_id:
            raise ServiceError(403, 4030001, "refresh token does not belong to current user", public=True)
        refresh_session = store.get_refresh_session(str(claims.get("jti") or ""))
        if refresh_session is not None and (
            refresh_session.subject_type != "user"
            or refresh_session.subject_id != subject.subject_id
            or refresh_session.token_version != int(claims.get("ver") or 0)
        ):
            raise ServiceError(401, 4010002, "refresh token is no longer valid", public=True)
        store.revoke_refresh_session(str(claims.get("jti") or ""))
    else:
        store.revoke_subject_refresh_sessions("user", subject.subject_id)
    store.revoke_access_token(
        token_id=subject.token_id,
        subject_type=subject.subject_type,
        subject_id=subject.subject_id,
        expires_at=subject.expires_at,
    )
    return _canonical_success(trace.request_id or "", OperationStatusData().model_dump(mode="json"))


@router.post("/auth/password/forgot")
@router.post("/auth/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, request: Request) -> JSONResponse:
    trace = build_trace_context(request)
    store = get_auth_store()
    if not store.consume_verification_code(
        scene="reset_password",
        account=payload.account,
        account_type=payload.account_type,
        code=payload.verification_code,
    ):
        raise ServiceError(400, 4001001, "invalid verification code", public=True)
    challenge = store.create_password_challenge(
        account=payload.account,
        account_type=payload.account_type,
        verification_code=payload.verification_code,
    )
    response = ForgotPasswordResponseData(
        challenge_id=challenge.challenge_id,
        expire_in=max(int((_parse_iso(challenge.expires_at) - _parse_iso(challenge.created_at)).total_seconds()), 1),
    )
    return _canonical_success(trace.request_id or "", response.model_dump(mode="json"))


@router.post("/auth/password/reset")
@router.post("/auth/reset-password")
def reset_password(payload: ResetPasswordRequest, request: Request) -> JSONResponse:
    trace = build_trace_context(request)
    store = get_auth_store()
    challenge = store.get_password_challenge(payload.challenge_id)
    if challenge is None:
        raise ServiceError(400, 4001001, "password reset challenge is invalid or expired", public=True)
    if (
        challenge.account != normalize_account_identifier(payload.account, challenge.account_type)
        or challenge.verification_code != payload.verification_code
    ):
        raise ServiceError(400, 4001001, "password reset challenge does not match account verification", public=True)
    user = store.reset_user_password(
        account=payload.account,
        account_type=challenge.account_type,
        new_password=payload.new_password,
    )
    if user is None:
        raise ServiceError(404, 4040001, "user account not found", public=True)
    store.revoke_subject_refresh_sessions("user", user.user_id)
    store.consume_password_challenge(payload.challenge_id)
    return _canonical_success(trace.request_id or "", OperationStatusData().model_dump(mode="json"))


@router.patch("/users/me")
@router.patch("/auth/profile")
@router.patch("/users/me/profile", include_in_schema=False)
def update_profile(
    payload: UserProfileUpdateRequest,
    request: Request,
    subject: CurrentSubject = Depends(require_user_subject()),
) -> JSONResponse:
    trace = build_trace_context(request)
    fields_set = payload.model_fields_set
    try:
        user = get_auth_store().update_user_profile(
            subject.subject_id,
            name=payload.name if "name" in fields_set else UNSET,
            avatar_url=payload.avatar_url if "avatar_url" in fields_set else UNSET,
            locale=payload.locale if "locale" in fields_set else UNSET,
            time_zone=payload.time_zone if "time_zone" in fields_set else UNSET,
        )
    except KeyError as exc:
        raise ServiceError(404, 4040001, "user account not found", public=True) from exc
    return _canonical_success(trace.request_id or "", user.to_public_profile().model_dump(mode="json"))


@router.post("/users/me/change-password")
@router.post("/auth/change-password")
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    subject: CurrentSubject = Depends(require_user_subject()),
) -> JSONResponse:
    trace = build_trace_context(request)
    user = get_auth_store().change_user_password(
        subject.subject_id,
        old_password=payload.old_password,
        new_password=payload.new_password,
    )
    if user is None:
        raise ServiceError(400, 4001001, "old password is incorrect", public=True)
    get_auth_store().revoke_subject_refresh_sessions("user", subject.subject_id)
    return _canonical_success(trace.request_id or "", OperationStatusData().model_dump(mode="json"))


@admin_router.post("/admin/auth/login")
def admin_login(payload: AdminLoginRequest, request: Request) -> JSONResponse:
    trace = build_trace_context(request)
    admin = get_auth_store().get_admin_by_username(payload.username)
    if admin is None or not get_auth_store().verify_admin_password(admin, payload.password):
        raise ServiceError(401, 4010001, "invalid admin account or credential", public=True)
    access_token = get_token_codec().issue_access_token(
        subject_type="admin",
        subject_id=admin.admin_id,
        roles=admin.roles,
        permissions=admin.permissions,
        token_version=admin.token_version,
    )
    refresh_token = get_token_codec().issue_refresh_token(
        subject_type="admin",
        subject_id=admin.admin_id,
        roles=admin.roles,
        permissions=admin.permissions,
        token_version=admin.token_version,
    )
    get_auth_store().save_refresh_session(
        token_id=str(refresh_token.claims["jti"]),
        subject_type="admin",
        subject_id=admin.admin_id,
        token_version=admin.token_version,
        expires_at=refresh_token.expires_at.isoformat(),
    )
    response = AdminLoginResponseData(
        access_token=access_token.token,
        refresh_token=refresh_token.token,
        admin=admin.to_session_profile(),
    )
    return _canonical_success(trace.request_id or "", response.model_dump(mode="json"))


@admin_router.get("/admin/auth/me")
def admin_me(
    request: Request,
    subject: CurrentSubject = Depends(require_admin_subject()),
) -> JSONResponse:
    trace = build_trace_context(request)
    admin = get_auth_store().get_admin_by_id(subject.subject_id)
    if admin is None:
        raise ServiceError(401, 4010001, "admin not found", public=True)
    return _canonical_success(trace.request_id or "", admin.to_session_profile().model_dump(mode="json"))


@admin_router.post("/admin/auth/action-confirmations")
def create_admin_action_confirmation(
    payload: AdminActionConfirmationRequest,
    request: Request,
    subject: CurrentSubject = Depends(require_admin_subject()),
) -> JSONResponse:
    trace = build_trace_context(request)
    admin = get_auth_store().get_admin_by_id(subject.subject_id)
    if admin is None:
        raise ServiceError(401, 4010001, "admin not found", public=True)
    verification_payload = payload.verification_payload or {}
    if payload.verification_method == "password":
        password = str(verification_payload.get("password") or "")
        if not password or not get_auth_store().verify_admin_password(admin, password):
            raise ServiceError(403, 4030001, "admin verification failed", public=True)
    else:
        provided = any(
            str(verification_payload.get(key) or "").strip()
            for key in ("code", "ticket", "assertion", "token")
        )
        if not provided:
            raise ServiceError(403, 4030001, "verification payload is incomplete", public=True)
    record = get_auth_store().create_admin_confirmation(
        admin_id=admin.admin_id,
        action=payload.action,
        resource_scope=payload.resource_scope,
    )
    response = AdminActionConfirmationResponseData(
        confirm_token=record.confirm_token,
        expired_at=record.expired_at,
        action=record.action,
        resource_scope=record.resource_scope,
    )
    return _canonical_success(trace.request_id or "", response.model_dump(mode="json"))


@internal_router.get("/auth/validate-token")
def validate_token(
    request: Request,
    token: str = Query(min_length=1),
    _: CurrentSubject = Depends(require_internal_subject),
) -> JSONResponse:
    trace = build_trace_context(request)
    try:
        claims = get_token_codec().decode(token)
        _ensure_token_is_current(claims)
    except TokenError as exc:
        raise ServiceError(401, "AUTH_UNAUTHORIZED", str(exc), public=False) from exc
    response = InternalTokenValidationResponseData(
        subject_type=claims.get("subject_type", "user"),
        subject_id=claims.get("subject_id") or claims.get("sub") or "",
        tenant_id=claims.get("tenant_id"),
        roles=list(claims.get("roles") or []),
        permissions=list(claims.get("permissions") or []),
        expired_at=_epoch_to_iso(claims.get("exp")),
    )
    return _internal_success(trace.request_id, trace, response.model_dump(mode="json"))


@internal_router.post("/auth/check-permission")
def check_permission(
    payload: PermissionCheckRequest,
    request: Request,
    _: CurrentSubject = Depends(require_internal_subject),
) -> JSONResponse:
    trace = build_trace_context(request)
    permissions = _lookup_subject_permissions(payload.subject_type, payload.subject_id)
    denied = [permission for permission in payload.permissions if permission not in permissions]
    response = PermissionCheckResponseData(allowed=not denied, denied_permissions=denied)
    return _internal_success(trace.request_id, trace, response.model_dump(mode="json"))


@internal_router.post("/auth/invalidate-subject-cache")
def invalidate_subject_cache(
    payload: InvalidateSubjectCacheRequest,
    request: Request,
    _: CurrentSubject = Depends(require_internal_subject),
) -> JSONResponse:
    trace = build_trace_context(request)
    get_auth_store().record_cache_invalidation(
        subject_type=payload.subject_type,
        subject_ids=payload.subject_ids,
    )
    response = InvalidateSubjectCacheResponseData(invalidated_subject_ids=payload.subject_ids)
    return _internal_success(trace.request_id, trace, response.model_dump(mode="json"))


def _canonical_success(request_id: str, data: dict, *, message: str = "ok", status_code: int = 200) -> JSONResponse:
    payload = CanonicalSuccessEnvelope(
        message=message,
        data=data,
        request_id=request_id,
        timestamp=now_timestamp_ms(),
    ).model_dump(mode="json")
    return JSONResponse(status_code=status_code, content=payload)


def _internal_success(request_id: str | None, trace, data: dict, *, status_code: int = 200) -> JSONResponse:
    payload = ApiEnvelope(success=True, data=data, requestId=request_id, trace=trace).model_dump(
        mode="json",
        by_alias=True,
    )
    return JSONResponse(status_code=status_code, content=payload)


def _lookup_subject_permissions(subject_type: str, subject_id: str) -> list[str]:
    store = get_auth_store()
    if subject_type == "user":
        user = store.get_user_by_id(subject_id)
        return user.permissions if user else []
    if subject_type == "admin":
        admin = store.get_admin_by_id(subject_id)
        return admin.permissions if admin else []
    if subject_type == "service" and subject_id in _settings.allowed_internal_callers:
        return ["service:internal.call"]
    return []


def _ensure_token_is_current(claims: dict) -> None:
    subject_type = str(claims.get("subject_type") or "user")
    subject_id = str(claims.get("subject_id") or claims.get("sub") or "")
    token_type = str(claims.get("token_type") or "access")
    token_version = int(claims.get("ver") or 1)
    token_id = str(claims.get("jti") or "")
    store = get_auth_store()

    if subject_type == "user":
        user = store.get_user_by_id(subject_id)
        if user is None or user.token_version != token_version:
            raise ServiceError(401, "AUTH_UNAUTHORIZED", "token is no longer valid", public=False)
        if token_type == "refresh":
            _ensure_refresh_session_is_current(
                subject_type=subject_type,
                subject_id=subject_id,
                token_id=token_id,
                token_version=token_version,
            )
        elif store.is_access_token_revoked(
            token_id=token_id,
            subject_type=subject_type,
            subject_id=subject_id,
        ):
            raise ServiceError(401, "AUTH_UNAUTHORIZED", "token is no longer valid", public=False)
        return

    if subject_type == "admin":
        admin = store.get_admin_by_id(subject_id)
        if admin is None or admin.token_version != token_version:
            raise ServiceError(401, "AUTH_UNAUTHORIZED", "token is no longer valid", public=False)
        if token_type == "refresh":
            _ensure_refresh_session_is_current(
                subject_type=subject_type,
                subject_id=subject_id,
                token_id=token_id,
                token_version=token_version,
            )
        elif store.is_access_token_revoked(
            token_id=token_id,
            subject_type=subject_type,
            subject_id=subject_id,
        ):
            raise ServiceError(401, "AUTH_UNAUTHORIZED", "token is no longer valid", public=False)
        return

    if token_type != "access":
        raise ServiceError(401, "AUTH_UNAUTHORIZED", "token is no longer valid", public=False)


def _ensure_refresh_session_is_current(
    *,
    subject_type: str,
    subject_id: str,
    token_id: str,
    token_version: int,
) -> None:
    if not token_id:
        raise ServiceError(401, "AUTH_UNAUTHORIZED", "token is no longer valid", public=False)
    session = get_auth_store().get_refresh_session(token_id)
    if session is None or session.revoked:
        raise ServiceError(401, "AUTH_UNAUTHORIZED", "token is no longer valid", public=False)
    if (
        session.subject_type != subject_type
        or session.subject_id != subject_id
        or session.token_version != token_version
    ):
        raise ServiceError(401, "AUTH_UNAUTHORIZED", "token is no longer valid", public=False)


def _mask_account(account: str, account_type: str) -> str:
    if account_type == "email" and "@" in account:
        local, domain = account.split("@", 1)
        return f"{local[:1]}***@{domain}"
    if len(account) >= 7:
        return f"{account[:3]}****{account[-4:]}"
    return f"{account[:1]}***"


def _parse_iso(value: str):
    return __import__("datetime").datetime.fromisoformat(value)


def _epoch_to_iso(value) -> str:
    try:
        return __import__("datetime").datetime.fromtimestamp(int(value), tz=__import__("datetime").UTC).isoformat()
    except Exception:
        return ""
