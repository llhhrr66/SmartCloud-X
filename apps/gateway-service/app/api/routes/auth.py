from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.services.auth import require_admin_subject, require_user_subject


router = APIRouter(prefix="/api/v1", tags=["auth"])


@router.post("/auth/login")
async def auth_login(request: Request):
    return await request.app.state.gateway_services.http.proxy(request, "auth-user-service")


@router.post("/auth/send-code")
async def auth_send_code(request: Request):
    return await request.app.state.gateway_services.http.proxy(request, "auth-user-service")


@router.post("/auth/password/forgot")
async def auth_password_forgot(request: Request):
    return await request.app.state.gateway_services.http.proxy(request, "auth-user-service")


@router.post("/auth/password/reset")
async def auth_password_reset(request: Request):
    return await request.app.state.gateway_services.http.proxy(request, "auth-user-service")


@router.post("/auth/refresh")
async def auth_refresh(request: Request):
    return await request.app.state.gateway_services.http.proxy(request, "auth-user-service")


@router.get("/auth/me")
async def auth_me(request: Request, _=Depends(require_user_subject)):
    return await request.app.state.gateway_services.http.proxy(request, "auth-user-service")


@router.post("/auth/logout")
async def auth_logout(request: Request, _=Depends(require_user_subject)):
    return await request.app.state.gateway_services.http.proxy(request, "auth-user-service")


@router.patch("/users/me")
async def update_me(request: Request, _=Depends(require_user_subject)):
    return await request.app.state.gateway_services.http.proxy(request, "auth-user-service")


@router.post("/users/me/change-password")
async def change_password(request: Request, _=Depends(require_user_subject)):
    return await request.app.state.gateway_services.http.proxy(request, "auth-user-service")


@router.post("/admin/auth/login")
async def admin_login(request: Request):
    return await request.app.state.gateway_services.http.proxy(request, "auth-user-service")


@router.get("/admin/auth/me")
async def admin_me(request: Request, _=Depends(require_admin_subject)):
    return await request.app.state.gateway_services.http.proxy(request, "auth-user-service")


@router.post("/admin/auth/action-confirmations")
async def admin_action_confirmations(request: Request, _=Depends(require_admin_subject)):
    return await request.app.state.gateway_services.http.proxy(request, "auth-user-service")
