from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from fastapi import Request

from app.core.config import get_settings
from app.models import CurrentSubject, ServiceError, TraceContext
from app.security import TokenError, get_token_codec
from app.store import get_auth_store


def build_trace_context(request: Request) -> TraceContext:
    existing = getattr(request.state, "trace_context", None)
    if existing is not None:
        return existing
    settings = get_settings()
    request_id = request.headers.get(settings.request_id_header) or str(uuid4())
    trace = TraceContext(
        requestId=request_id,
        traceId=request.headers.get(settings.trace_id_header) or request_id,
        conversationId=request.headers.get(settings.conversation_id_header),
        tenantId=request.headers.get(settings.tenant_id_header),
        callerService=request.headers.get(settings.caller_service_header),
    )
    request.state.trace_context = trace
    return trace


def require_user_subject(*required_permissions: str) -> Callable[[Request], CurrentSubject]:
    def dependency(request: Request) -> CurrentSubject:
        subject = _decode_subject(
            request,
            expected_audience=get_settings().auth_audience,
            unauthorized_code=4010002,
            unauthorized_message="user login required",
            public=True,
        )
        if subject.subject_type != "user" or subject.token_type != "access":
            raise ServiceError(401, 4010002, "user login required", public=True)
        store = get_auth_store()
        user = store.get_user_by_id(subject.subject_id)
        if user is None or user.token_version != subject.token_version:
            raise ServiceError(401, 4010002, "token is no longer valid", public=True)
        if store.is_access_token_revoked(
            token_id=subject.token_id,
            subject_type=subject.subject_type,
            subject_id=subject.subject_id,
        ):
            raise ServiceError(401, 4010002, "token is no longer valid", public=True)
        _ensure_permissions(subject.permissions, required_permissions, public=True)
        return subject

    return dependency


def require_admin_subject(*required_permissions: str) -> Callable[[Request], CurrentSubject]:
    def dependency(request: Request) -> CurrentSubject:
        subject = _decode_subject(
            request,
            expected_audience=get_settings().auth_audience,
            unauthorized_code=4010001,
            unauthorized_message="admin login required",
            public=True,
        )
        if subject.subject_type != "admin" or subject.token_type != "access":
            raise ServiceError(401, 4010001, "admin login required", public=True)
        store = get_auth_store()
        admin = store.get_admin_by_id(subject.subject_id)
        if admin is None or admin.token_version != subject.token_version:
            raise ServiceError(401, 4010001, "token is no longer valid", public=True)
        if store.is_access_token_revoked(
            token_id=subject.token_id,
            subject_type=subject.subject_type,
            subject_id=subject.subject_id,
        ):
            raise ServiceError(401, 4010001, "token is no longer valid", public=True)
        _ensure_permissions(subject.permissions, required_permissions, public=True)
        return subject

    return dependency


def require_internal_subject(request: Request) -> CurrentSubject:
    settings = get_settings()
    caller = request.headers.get(settings.caller_service_header)
    if not caller:
        raise ServiceError(
            403,
            "AUTH_CALLER_FORBIDDEN",
            "X-Caller-Service header is required",
            public=False,
            details={
                "header": settings.caller_service_header,
                "allowed_callers": settings.allowed_internal_callers,
            },
        )
    if caller not in settings.allowed_internal_callers:
        raise ServiceError(
            403,
            "AUTH_CALLER_FORBIDDEN",
            f"caller '{caller}' is not allowed",
            public=False,
            details={"allowed_callers": settings.allowed_internal_callers},
        )
    subject = _decode_subject(
        request,
        expected_audience=settings.internal_auth_audience,
        unauthorized_code="AUTH_UNAUTHORIZED",
        unauthorized_message="internal service token required",
        public=False,
    )
    if subject.subject_type != "service" or subject.subject_id != caller:
        raise ServiceError(401, "AUTH_UNAUTHORIZED", "service token subject must match caller", public=False)
    if "service:internal.call" not in subject.permissions:
        raise ServiceError(403, "AUTH_FORBIDDEN", "service:internal.call is required", public=False)
    subject.caller_service = caller
    return subject


def _decode_subject(
    request: Request,
    *,
    expected_audience: str,
    unauthorized_code: int | str,
    unauthorized_message: str,
    public: bool,
) -> CurrentSubject:
    token = _extract_bearer_token(request, unauthorized_code=unauthorized_code, public=public, message=unauthorized_message)
    try:
        claims = get_token_codec().decode(token, audience=expected_audience)
    except TokenError as exc:
        raise ServiceError(401, unauthorized_code, str(exc), public=public) from exc
    return CurrentSubject(
        subject_type=claims.get("subject_type", "user"),
        subject_id=claims.get("subject_id") or claims.get("sub") or "",
        tenant_id=claims.get("tenant_id"),
        roles=list(claims.get("roles") or []),
        permissions=list(claims.get("permissions") or []),
        token_type=str(claims.get("token_type") or "access"),
        token_id=str(claims.get("jti") or ""),
        token_version=int(claims.get("ver") or 1),
        expires_at=_epoch_to_iso(claims.get("exp")),
    )


def _extract_bearer_token(
    request: Request,
    *,
    unauthorized_code: int | str,
    public: bool,
    message: str,
) -> str:
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise ServiceError(401, unauthorized_code, message, public=public)
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise ServiceError(401, unauthorized_code, message, public=public)
    return token


def _ensure_permissions(actual_permissions: list[str], required_permissions: tuple[str, ...], *, public: bool) -> None:
    missing = [permission for permission in required_permissions if permission not in actual_permissions]
    if missing:
        code: int | str = 4030001 if public else "AUTH_FORBIDDEN"
        raise ServiceError(
            403,
            code,
            "missing required permissions",
            public=public,
            details={"missing_permissions": missing},
        )


def _epoch_to_iso(value: Any) -> str:
    try:
        return __import__("datetime").datetime.fromtimestamp(int(value), tz=__import__("datetime").UTC).isoformat()
    except Exception:
        return ""
