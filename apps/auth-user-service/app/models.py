from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Generic, Literal, TypeVar
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, model_validator


class CanonicalErrorDetail(BaseModel):
    type: str | None = None
    field: str | None = None
    reason: str | None = None
    details: dict[str, Any] | None = None


class CanonicalSuccessEnvelope(BaseModel):
    code: int = 0
    message: str
    data: Any
    request_id: str
    timestamp: int


class CanonicalErrorEnvelope(BaseModel):
    code: int
    message: str
    request_id: str
    timestamp: int
    data: None = None
    error: CanonicalErrorDetail | None = None


class ErrorInfo(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None
    retryable: bool = False


T = TypeVar("T")


class TraceContext(BaseModel):
    request_id: str | None = Field(default=None, alias="requestId")
    trace_id: str | None = Field(default=None, alias="traceId")
    conversation_id: str | None = Field(default=None, alias="conversationId")
    tenant_id: str | None = Field(default=None, alias="tenantId")
    caller_service: str | None = Field(default=None, alias="callerService")

    model_config = {"populate_by_name": True}


class ApiEnvelope(BaseModel, Generic[T]):
    success: bool = True
    data: T | None = None
    request_id: str | None = Field(default=None, alias="requestId")
    trace: TraceContext | None = None
    error: ErrorInfo | None = None
    meta: dict[str, Any] | None = None

    model_config = {"populate_by_name": True}


class ServiceError(Exception):
    def __init__(
        self,
        status_code: int,
        code: int | str,
        message: str,
        *,
        public: bool,
        field: str | None = None,
        error_type: str | None = None,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.public = public
        self.field = field
        self.error_type = error_type
        self.details = details
        self.retryable = retryable


class AuthUserProfile(BaseModel):
    user_id: str
    tenant_id: str
    name: str
    email: str
    mobile: str | None = None
    avatar_url: str | None = None
    locale: str
    time_zone: str
    permissions: list[str] = Field(default_factory=list)
    account_id: str | None = None


class LoginRequest(BaseModel):
    login_type: Literal["password", "sms", "email_code"]
    account: str = Field(min_length=1)
    password: str | None = Field(default=None, min_length=1)
    sms_code: str | None = Field(default=None, min_length=1)
    email_code: str | None = Field(default=None, min_length=1)
    captcha_token: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_credentials(self) -> "LoginRequest":
        if self.login_type == "password" and not self.password:
            raise ValueError("password is required for password login")
        if self.login_type == "sms" and not self.sms_code:
            raise ValueError("sms_code is required for sms login")
        if self.login_type == "email_code" and not self.email_code:
            raise ValueError("email_code is required for email code login")
        return self


class LoginResponseData(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    user: AuthUserProfile


class SendCodeRequest(BaseModel):
    scene: Literal["login", "reset_password"]
    account: str = Field(min_length=1)
    account_type: Literal["mobile", "email"]
    captcha_token: str | None = Field(default=None, min_length=1)


class SendCodeResponseData(BaseModel):
    scene: Literal["login", "reset_password"]
    masked_account: str
    expire_in: int


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class RefreshTokenResponseData(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    user: AuthUserProfile | None = None


class LogoutRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=1)


class UserProfileUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    avatar_url: str | None = Field(default=None, min_length=1, max_length=2048)
    locale: str | None = Field(default=None, min_length=2, max_length=32)
    time_zone: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="before")
    @classmethod
    def reject_null_text_fields(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        for field_name in ("name", "locale", "time_zone"):
            if field_name in value and value[field_name] is None:
                raise ValueError(f"{field_name} cannot be null")
        return value

    @model_validator(mode="after")
    def validate_non_empty(self) -> "UserProfileUpdateRequest":
        has_text_update = any(getattr(self, field_name) is not None for field_name in ("name", "locale", "time_zone"))
        has_avatar_update = "avatar_url" in self.model_fields_set
        if not has_text_update and not has_avatar_update:
            raise ValueError("at least one mutable profile field is required")
        return self

    @model_validator(mode="after")
    def validate_trimmed_text_values(self) -> "UserProfileUpdateRequest":
        normalized_locale = _normalize_locale(self.locale) if self.locale is not None else None
        normalized_time_zone = self.time_zone.strip() if self.time_zone is not None else None
        normalized_avatar_url = self.avatar_url.strip() if self.avatar_url is not None else None

        for field_name in ("name", "avatar_url", "locale", "time_zone"):
            if field_name not in self.model_fields_set:
                continue
            value = getattr(self, field_name)
            if value is None:
                continue
            if not value.strip():
                raise ValueError(f"{field_name} cannot be blank")

        if normalized_avatar_url is not None:
            _validate_avatar_url(normalized_avatar_url)
        if normalized_locale is not None:
            _validate_locale(normalized_locale)
        if normalized_time_zone is not None:
            _validate_time_zone(normalized_time_zone)
        return self


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8)
    confirm_password: str = Field(min_length=8)

    @model_validator(mode="after")
    def validate_match(self) -> "ChangePasswordRequest":
        if self.new_password != self.confirm_password:
            raise ValueError("new_password and confirm_password must match")
        return self


class ForgotPasswordRequest(BaseModel):
    account: str = Field(min_length=1)
    account_type: Literal["mobile", "email"]
    verification_code: str = Field(min_length=1)


class ForgotPasswordResponseData(BaseModel):
    challenge_id: str
    expire_in: int


class ResetPasswordRequest(BaseModel):
    challenge_id: str = Field(min_length=1)
    account: str = Field(min_length=1)
    verification_code: str = Field(min_length=1)
    new_password: str = Field(min_length=8)
    confirm_password: str = Field(min_length=8)

    @model_validator(mode="after")
    def validate_match(self) -> "ResetPasswordRequest":
        if self.new_password != self.confirm_password:
            raise ValueError("new_password and confirm_password must match")
        return self


class OperationStatusData(BaseModel):
    success: Literal[True] = True


class AdminMenuItem(BaseModel):
    code: str
    name: str
    path: str
    icon: str | None = None
    children: list["AdminMenuItem"] = Field(default_factory=list)


class AdminSessionProfile(BaseModel):
    admin_id: str
    name: str
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    menus: list[AdminMenuItem] = Field(default_factory=list)


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    captcha_token: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_captcha_token(self) -> "AdminLoginRequest":
        if self.captcha_token is not None and not self.captcha_token.strip():
            raise ValueError("captcha_token cannot be blank")
        return self


class AdminLoginResponseData(BaseModel):
    access_token: str
    refresh_token: str
    admin: AdminSessionProfile


class AdminActionConfirmationRequest(BaseModel):
    action: str = Field(min_length=1)
    resource_scope: str = Field(min_length=1)
    verification_method: Literal["password", "sms", "totp", "webauthn"]
    verification_payload: dict[str, Any] = Field(default_factory=dict)


class AdminActionConfirmationResponseData(BaseModel):
    confirm_token: str
    expired_at: str
    action: str
    resource_scope: str


class InternalTokenValidationResponseData(BaseModel):
    subject_type: Literal["user", "admin", "service", "agent"]
    subject_id: str
    tenant_id: str | None = None
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    expired_at: str


class PermissionCheckRequest(BaseModel):
    subject_type: Literal["user", "admin", "service", "agent"]
    subject_id: str = Field(min_length=1)
    permissions: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_permissions(self) -> "PermissionCheckRequest":
        normalized_permissions = []
        for permission in self.permissions:
            permission_text = permission.strip()
            if not permission_text:
                raise ValueError("permissions entries cannot be blank")
            normalized_permissions.append(permission_text)
        self.permissions = normalized_permissions
        return self


class PermissionCheckResponseData(BaseModel):
    allowed: bool
    denied_permissions: list[str] = Field(default_factory=list)


class InvalidateSubjectCacheRequest(BaseModel):
    subject_type: Literal["user", "admin", "service", "agent"]
    subject_ids: list[str] = Field(min_length=1)


class InvalidateSubjectCacheResponseData(BaseModel):
    invalidated_subject_ids: list[str] = Field(default_factory=list)


class CurrentSubject(BaseModel):
    subject_type: Literal["user", "admin", "service", "agent"]
    subject_id: str
    tenant_id: str | None = None
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    token_type: str
    token_id: str
    token_version: int = 1
    expires_at: str
    caller_service: str | None = None


class StoredUser(BaseModel):
    user_id: str
    tenant_id: str
    name: str
    email: str
    mobile: str | None = None
    password_hash: str
    avatar_url: str | None = None
    locale: str
    time_zone: str
    roles: list[str] = Field(default_factory=lambda: ["user"])
    permissions: list[str] = Field(default_factory=list)
    token_version: int = 1
    account_id: str | None = None

    def to_public_profile(self) -> AuthUserProfile:
        return AuthUserProfile(
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            name=self.name,
            email=self.email,
            mobile=self.mobile,
            avatar_url=self.avatar_url,
            locale=self.locale,
            time_zone=self.time_zone,
            permissions=self.permissions,
            account_id=self.account_id,
        )


class StoredAdmin(BaseModel):
    admin_id: str
    username: str
    name: str
    password_hash: str
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    menus: list[AdminMenuItem] = Field(default_factory=list)
    token_version: int = 1

    def to_session_profile(self) -> AdminSessionProfile:
        return AdminSessionProfile(
            admin_id=self.admin_id,
            name=self.name,
            roles=self.roles,
            permissions=self.permissions,
            menus=self.menus,
        )


class StoredVerificationCode(BaseModel):
    scene: Literal["login", "reset_password"]
    account: str
    account_type: Literal["mobile", "email"]
    code: str
    created_at: str
    expires_at: str


class StoredPasswordChallenge(BaseModel):
    challenge_id: str
    account: str
    account_type: Literal["mobile", "email"]
    verification_code: str
    created_at: str
    expires_at: str


class StoredRefreshSession(BaseModel):
    token_id: str
    subject_type: Literal["user", "admin", "service", "agent"]
    subject_id: str
    token_version: int
    expires_at: str
    revoked: bool = False


class StoredRevokedAccessToken(BaseModel):
    token_id: str
    subject_type: Literal["user", "admin", "service", "agent"]
    subject_id: str
    expires_at: str
    revoked_at: str


class StoredAdminConfirmation(BaseModel):
    confirm_token: str
    admin_id: str
    action: str
    resource_scope: str
    created_at: str
    expired_at: str


class StoredInvalidationEvent(BaseModel):
    subject_type: Literal["user", "admin", "service", "agent"]
    subject_ids: list[str] = Field(default_factory=list)
    created_at: str


class AuthStoreSnapshot(BaseModel):
    users: list[StoredUser] = Field(default_factory=list)
    admins: list[StoredAdmin] = Field(default_factory=list)
    verification_codes: list[StoredVerificationCode] = Field(default_factory=list)
    password_challenges: list[StoredPasswordChallenge] = Field(default_factory=list)
    refresh_sessions: list[StoredRefreshSession] = Field(default_factory=list)
    revoked_access_tokens: list[StoredRevokedAccessToken] = Field(default_factory=list)
    admin_confirmations: list[StoredAdminConfirmation] = Field(default_factory=list)
    invalidation_log: list[StoredInvalidationEvent] = Field(default_factory=list)


def utc_now() -> datetime:
    return datetime.now(UTC)


def now_iso() -> str:
    return utc_now().isoformat()


def now_timestamp_ms() -> int:
    return int(utc_now().timestamp() * 1000)


def _normalize_locale(value: str) -> str:
    return value.strip().replace("_", "-")


def _validate_locale(value: str) -> None:
    if not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", value):
        raise ValueError("locale must use BCP 47 style tags")


def _validate_time_zone(value: str) -> None:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("time_zone must be a valid IANA time zone") from exc


def _validate_avatar_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("avatar_url must be an absolute http(s) URL")


AdminMenuItem.model_rebuild()
