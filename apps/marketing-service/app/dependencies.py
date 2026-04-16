from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest
from urllib.request import urlopen
from uuid import uuid4

from fastapi import Request

from app.core.config import get_settings
from app.models import CurrentUserContext, ServiceError, TraceContext
from app.security import TokenError, get_token_codec


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


def require_user_permissions(*required_permissions: str) -> Callable[[Request], CurrentUserContext]:
    def dependency(request: Request) -> CurrentUserContext:
        settings = get_settings()
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            raise ServiceError(401, 4010002, "user login required")
        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            raise ServiceError(401, 4010002, "user login required")
        try:
            claims = get_token_codec().decode(token)
        except TokenError as exc:
            raise ServiceError(401, 4010002, str(exc)) from exc
        if claims.get("subject_type") != "user" or claims.get("token_type") != "access":
            raise ServiceError(401, 4010002, "user login required")
        current_state = _validate_token_current_state(request, token, claims, settings=settings)
        permissions = list(current_state.get("permissions") or [])
        missing = [permission for permission in required_permissions if permission not in permissions]
        if missing:
            raise ServiceError(
                403,
                4030001,
                "missing required permissions",
                details={"missing_permissions": missing},
            )
        return CurrentUserContext(
            user_id=current_state.get("subject_id") or current_state.get("sub") or "",
            tenant_id=current_state.get("tenant_id"),
            roles=list(current_state.get("roles") or []),
            permissions=permissions,
            expires_at=str(current_state.get("expired_at") or _epoch_to_iso(current_state.get("exp"))),
        )

    return dependency


def _validate_token_current_state(
    request: Request,
    token: str,
    claims: dict[str, Any],
    *,
    settings,
) -> dict[str, Any]:
    if settings.auth_validation_mode != "strict":
        return claims
    validated = _validate_token_with_auth_service(request, token, settings=settings)
    if validated.get("subject_type") != claims.get("subject_type"):
        raise ServiceError(401, 4010002, "token subject is no longer valid")
    validated_subject_id = str(validated.get("subject_id") or "")
    claim_subject_id = str(claims.get("subject_id") or claims.get("sub") or "")
    if validated_subject_id != claim_subject_id:
        raise ServiceError(401, 4010002, "token subject is no longer valid")
    current_state = dict(claims)
    current_state.update(
        {
            "subject_type": validated.get("subject_type") or claims.get("subject_type"),
            "subject_id": validated_subject_id or claim_subject_id,
            "tenant_id": validated.get("tenant_id"),
            "roles": _coerce_claim_list(validated, "roles", claims),
            "permissions": _coerce_claim_list(validated, "permissions", claims),
            "expired_at": validated.get("expired_at"),
        }
    )
    return current_state


def _validate_token_with_auth_service(
    request: Request,
    token: str,
    *,
    settings,
) -> dict[str, Any]:
    if not settings.auth_validate_token_url:
        raise ServiceError(
            503,
            5030001,
            "strict auth validation is enabled but auth validate URL is missing",
            error_type="misconfiguration",
            details={"setting": "MARKETING_SERVICE_AUTH_VALIDATE_TOKEN_URL"},
        )
    trace = build_trace_context(request)
    service_token = get_token_codec().issue_service_token(settings.internal_service_name).token
    headers = {
        "Authorization": f"Bearer {service_token}",
        settings.caller_service_header: settings.internal_service_name,
        settings.request_id_header: trace.request_id or "",
        settings.trace_id_header: trace.trace_id or "",
    }
    if trace.tenant_id:
        headers[settings.tenant_id_header] = trace.tenant_id
    url = f"{settings.auth_validate_token_url}?{urlencode({'token': token})}"
    upstream_request = UrlRequest(url, headers=headers, method="GET")
    try:
        with urlopen(upstream_request, timeout=settings.auth_validate_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        error_payload = _read_upstream_error_payload(exc)
        if exc.code == 401:
            raise ServiceError(401, 4010002, "token is no longer valid") from exc
        if exc.code == 403:
            raise ServiceError(
                503,
                5030001,
                "auth validation caller was rejected",
                error_type="upstream_forbidden",
                details={"upstream": error_payload},
            ) from exc
        raise ServiceError(
            503,
            5030001,
            "auth validation service is unavailable",
            error_type="upstream_http_error",
            details={"status_code": exc.code, "upstream": error_payload},
        ) from exc
    except URLError as exc:
        raise ServiceError(
            503,
            5030001,
            "auth validation service is unavailable",
            error_type="upstream_unavailable",
            details={"reason": str(exc.reason)},
        ) from exc

    if payload.get("success") is not True:
        raise ServiceError(
            503,
            5030001,
            "auth validation service returned an unsuccessful response",
            error_type="upstream_invalid_response",
            details={"payload": payload},
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ServiceError(
            503,
            5030001,
            "auth validation service returned an invalid response payload",
            error_type="upstream_invalid_response",
            details={"payload": payload},
        )
    return data


def _read_upstream_error_payload(exc: HTTPError) -> Any:
    try:
        raw_body = exc.read().decode("utf-8")
    except Exception:
        return {"status_code": exc.code}
    try:
        return json.loads(raw_body)
    except json.JSONDecodeError:
        return {"status_code": exc.code, "body": raw_body}


def _coerce_claim_list(validated: dict[str, Any], key: str, claims: dict[str, Any]) -> list[str]:
    if key in validated and validated.get(key) is not None:
        return [str(item) for item in list(validated.get(key) or [])]
    return [str(item) for item in list(claims.get(key) or [])]


def _epoch_to_iso(value: Any) -> str:
    try:
        return __import__("datetime").datetime.fromtimestamp(int(value), tz=__import__("datetime").UTC).isoformat()
    except Exception:
        return ""
