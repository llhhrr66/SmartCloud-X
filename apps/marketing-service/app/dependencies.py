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
from app.core.metrics import marketing_auth_validation_total, marketing_upstream_errors_total
from app.core.telemetry import set_span_attributes, start_span
from app.models import CurrentUserContext, ServiceError, TraceContext
from app.security import TokenError, get_token_codec


def build_trace_context(request: Request) -> TraceContext:
    existing = getattr(request.state, 'trace_context', None)
    if existing is not None:
        return existing
    settings = get_settings()
    request_id = request.headers.get(settings.request_id_header) or str(uuid4())
    incoming_trace_id = request.headers.get(settings.trace_id_header)
    traceparent = request.headers.get('traceparent')
    trace_id = incoming_trace_id or request_id
    if traceparent:
        parts = traceparent.split('-')
        if len(parts) >= 4 and parts[1]:
            trace_id = parts[1]
    trace = TraceContext(requestId=request_id, traceId=trace_id, conversationId=request.headers.get(settings.conversation_id_header), tenantId=request.headers.get(settings.tenant_id_header), callerService=request.headers.get(settings.caller_service_header), idempotencyKey=request.headers.get('Idempotency-Key'))
    request.state.trace_context = trace
    return trace


def require_user_permissions(*required_permissions: str) -> Callable[[Request], CurrentUserContext]:
    def dependency(request: Request) -> CurrentUserContext:
        trace = build_trace_context(request)
        with start_span('marketing.auth_validate', attributes={'operation': 'auth_validation', 'trace_id': trace.trace_id}) as span:
            settings = get_settings()
            authorization = request.headers.get('Authorization', '')
            if not authorization.startswith('Bearer '):
                marketing_auth_validation_total.labels(status='missing_header').inc()
                set_span_attributes(span, {'status': 'error', 'error_type': 'missing_header'})
                raise ServiceError(401, 4010002, 'user login required')
            token = authorization.removeprefix('Bearer ').strip()
            if not token:
                marketing_auth_validation_total.labels(status='missing_token').inc()
                set_span_attributes(span, {'status': 'error', 'error_type': 'missing_token'})
                raise ServiceError(401, 4010002, 'user login required')
            try:
                claims = get_token_codec().decode(token)
            except TokenError as exc:
                marketing_auth_validation_total.labels(status='invalid_token').inc()
                marketing_upstream_errors_total.labels(backend='auth-local', error_type=exc.__class__.__name__).inc()
                set_span_attributes(span, {'status': 'error', 'error_type': exc.__class__.__name__})
                raise ServiceError(401, 4010002, str(exc)) from exc
            requires_admin = any(permission.startswith('admin:') for permission in required_permissions)
            allowed_subject_types = {'admin'} if requires_admin else {'user'}
            if claims.get('subject_type') not in allowed_subject_types or claims.get('token_type') != 'access':
                marketing_auth_validation_total.labels(status='subject_mismatch').inc()
                set_span_attributes(span, {'status': 'error', 'error_type': 'subject_mismatch', 'subject_type': claims.get('subject_type')})
                raise ServiceError(401, 4010002, 'user login required')
            current_state = _validate_token_current_state(request, token, claims, settings=settings)
            permissions = list(current_state.get('permissions') or [])
            subject_id = current_state.get('subject_id') or current_state.get('sub') or ''
            tenant_id = current_state.get('tenant_id')
            subject_type = current_state.get('subject_type')
            missing = [permission for permission in required_permissions if permission not in permissions]
            if missing:
                marketing_auth_validation_total.labels(status='missing_permissions').inc()
                set_span_attributes(span, {'status': 'error', 'error_type': 'missing_permissions', 'subject_id': subject_id, 'tenant_id': tenant_id, 'subject_type': subject_type, 'missing_permissions': ','.join(missing)})
                raise ServiceError(403, 4030001, 'missing required permissions', details={'missing_permissions': missing})
            marketing_auth_validation_total.labels(status='success').inc()
            set_span_attributes(span, {'status': 'ok', 'subject_id': subject_id, 'tenant_id': tenant_id, 'subject_type': subject_type})
            return CurrentUserContext(user_id=subject_id, tenant_id=tenant_id, roles=list(current_state.get('roles') or []), permissions=permissions, expires_at=str(current_state.get('expired_at') or _epoch_to_iso(current_state.get('exp'))))
    return dependency


def _validate_token_current_state(request: Request, token: str, claims: dict[str, Any], *, settings) -> dict[str, Any]:
    if settings.auth_validation_mode != 'strict':
        return claims
    with start_span('marketing.auth_validate_upstream', attributes={'operation': 'auth_validation_upstream', 'trace_id': build_trace_context(request).trace_id, 'auth_validation_mode': settings.auth_validation_mode, 'backend': 'auth-user-service'}) as span:
        try:
            validated = _validate_token_with_auth_service(request, token, settings=settings)
            set_span_attributes(span, {'status': 'ok'})
        except Exception as exc:
            set_span_attributes(span, {'status': 'error', 'error_type': exc.__class__.__name__})
            raise
    if validated.get('subject_type') != claims.get('subject_type'):
        marketing_auth_validation_total.labels(status='subject_invalidated').inc()
        raise ServiceError(401, 4010002, 'token subject is no longer valid')
    validated_subject_id = str(validated.get('subject_id') or '')
    claim_subject_id = str(claims.get('subject_id') or claims.get('sub') or '')
    if validated_subject_id != claim_subject_id:
        marketing_auth_validation_total.labels(status='subject_invalidated').inc()
        raise ServiceError(401, 4010002, 'token subject is no longer valid')
    current_state = dict(claims)
    current_state.update({'subject_type': validated.get('subject_type') or claims.get('subject_type'), 'subject_id': validated_subject_id or claim_subject_id, 'tenant_id': validated.get('tenant_id'), 'roles': _coerce_claim_list(validated, 'roles', claims), 'permissions': _coerce_claim_list(validated, 'permissions', claims), 'expired_at': validated.get('expired_at')})
    return current_state


def _validate_token_with_auth_service(request: Request, token: str, *, settings) -> dict[str, Any]:
    if not settings.auth_validate_token_url:
        marketing_auth_validation_total.labels(status='misconfigured').inc()
        raise ServiceError(503, 5030001, 'strict auth validation is enabled but auth validate URL is missing', error_type='misconfiguration', details={'setting': 'MARKETING_SERVICE_AUTH_VALIDATE_TOKEN_URL'})
    trace = build_trace_context(request)
    service_token = get_token_codec().issue_service_token(settings.internal_service_name).token
    headers = {'Authorization': f'Bearer {service_token}', settings.caller_service_header: settings.internal_service_name, settings.request_id_header: trace.request_id or '', settings.trace_id_header: trace.trace_id or ''}
    if trace.tenant_id:
        headers[settings.tenant_id_header] = trace.tenant_id
    url = f"{settings.auth_validate_token_url}?{urlencode({'token': token})}"
    upstream_request = UrlRequest(url, headers=headers, method='GET')
    try:
        with urlopen(upstream_request, timeout=settings.auth_validate_timeout_seconds) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        marketing_auth_validation_total.labels(status='upstream_http_error').inc()
        marketing_upstream_errors_total.labels(backend='auth-user-service', error_type='http_error').inc()
        error_payload = _read_upstream_error_payload(exc)
        if exc.code == 401:
            raise ServiceError(401, 4010002, 'token is no longer valid') from exc
        if exc.code == 403:
            raise ServiceError(503, 5030001, 'auth validation caller was rejected', error_type='upstream_forbidden', details={'upstream': error_payload}) from exc
        raise ServiceError(503, 5030001, 'auth validation service is unavailable', error_type='upstream_http_error', details={'status_code': exc.code, 'upstream': error_payload}) from exc
    except URLError as exc:
        marketing_auth_validation_total.labels(status='upstream_unavailable').inc()
        marketing_upstream_errors_total.labels(backend='auth-user-service', error_type='unavailable').inc()
        raise ServiceError(503, 5030001, 'auth validation service is unavailable', error_type='upstream_unavailable', details={'reason': str(exc.reason)}) from exc
    if payload.get('success') is not True:
        marketing_auth_validation_total.labels(status='invalid_response').inc()
        marketing_upstream_errors_total.labels(backend='auth-user-service', error_type='invalid_response').inc()
        raise ServiceError(503, 5030001, 'auth validation service returned an unsuccessful response', error_type='upstream_invalid_response', details={'payload': payload})
    data = payload.get('data')
    if not isinstance(data, dict):
        marketing_auth_validation_total.labels(status='invalid_payload').inc()
        marketing_upstream_errors_total.labels(backend='auth-user-service', error_type='invalid_payload').inc()
        raise ServiceError(503, 5030001, 'auth validation service returned an invalid response payload', error_type='upstream_invalid_response', details={'payload': payload})
    return data


def _read_upstream_error_payload(exc: HTTPError) -> Any:
    try:
        raw_body = exc.read().decode('utf-8')
    except Exception:
        return {'status_code': exc.code}
    try:
        return json.loads(raw_body)
    except json.JSONDecodeError:
        return {'status_code': exc.code, 'body': raw_body}


def _coerce_claim_list(validated: dict[str, Any], key: str, claims: dict[str, Any]) -> list[str]:
    if key in validated and validated.get(key) is not None:
        return [str(item) for item in list(validated.get(key) or [])]
    return [str(item) for item in list(claims.get(key) or [])]


def _epoch_to_iso(value: Any) -> str:
    try:
        return __import__('datetime').datetime.fromtimestamp(int(value), tz=__import__('datetime').UTC).isoformat()
    except Exception:
        return ''
