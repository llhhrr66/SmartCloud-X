from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import HTTPException, Request, status

from app.services.request_context import get_request_identity


@dataclass(slots=True)
class GatewaySubject:
    subject_type: str
    subject_id: str
    account_id: str | None = None
    tenant_id: str | None = None
    roles: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    expired_at: str | None = None


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": 4010002, "message": "missing bearer token"},
        )
    return token.strip()


def bind_subject_context(request: Request, subject: GatewaySubject) -> GatewaySubject:
    request.state.subject_type = subject.subject_type
    request.state.subject_id = subject.subject_id
    request.state.tenant_id = subject.tenant_id or getattr(request.state, "tenant_id", None)
    return subject


async def require_user_subject(request: Request) -> GatewaySubject:
    _bearer_token(request)
    services = request.app.state.gateway_services
    response = await services.http.request_json(
        "auth-user-service",
        "GET",
        "/api/v1/auth/me",
        headers={
            "Authorization": request.headers["Authorization"],
            services.settings.request_id_header: request.state.request_id,
            services.settings.trace_id_header: request.state.trace_id,
        },
        request_identity=get_request_identity(request),
    )
    payload = response.get("data") if isinstance(response.get("data"), dict) else response
    compatibility_account_id = payload.get("account_id") or payload.get("user_id") or payload.get("subject_id")
    return bind_subject_context(
        request,
        GatewaySubject(
            subject_type="user",
            subject_id=str(payload.get("user_id") or payload.get("subject_id") or ""),
            account_id=str(compatibility_account_id) if compatibility_account_id else None,
            tenant_id=payload.get("tenant_id"),
            roles=list(payload.get("roles") or ["user"]),
            permissions=list(payload.get("permissions") or []),
        ),
    )


async def require_admin_subject(request: Request) -> GatewaySubject:
    _bearer_token(request)
    services = request.app.state.gateway_services
    response = await services.http.request_json(
        "auth-user-service",
        "GET",
        "/api/v1/admin/auth/me",
        headers={
            "Authorization": request.headers["Authorization"],
            services.settings.request_id_header: request.state.request_id,
            services.settings.trace_id_header: request.state.trace_id,
        },
        request_identity=get_request_identity(request),
    )
    payload = response.get("data") if isinstance(response.get("data"), dict) else response
    return bind_subject_context(
        request,
        GatewaySubject(
            subject_type="admin",
            subject_id=str(payload.get("admin_id") or payload.get("subject_id") or ""),
            tenant_id=payload.get("tenant_id"),
            roles=list(payload.get("roles") or []),
            permissions=list(payload.get("permissions") or []),
        ),
    )


def ensure_permission(subject: GatewaySubject, permission: str) -> None:
    if permission in subject.permissions:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": 4030001, "message": f"missing permission: {permission}"},
    )
