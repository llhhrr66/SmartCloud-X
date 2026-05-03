from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.services.auth import require_user_subject


router = APIRouter(prefix="/api/v1", tags=["marketing-research"])


@router.get("/marketing/campaigns")
async def list_campaigns(request: Request, _=Depends(require_user_subject)):
    return await request.app.state.gateway_services.http.proxy(request, "marketing-service")


@router.post("/marketing/copy/generate")
async def generate_copy(request: Request, _=Depends(require_user_subject)):
    return await request.app.state.gateway_services.http.proxy(request, "marketing-service")


@router.get("/marketing/posters")
async def list_posters(request: Request, _=Depends(require_user_subject)):
    return await request.app.state.gateway_services.http.proxy(request, "marketing-service")


@router.post("/marketing/posters")
async def create_poster(request: Request, _=Depends(require_user_subject)):
    return await request.app.state.gateway_services.http.proxy(request, "marketing-service")


@router.get("/marketing/posters/{task_id}")
async def get_poster(request: Request, task_id: str, _=Depends(require_user_subject)):
    return await request.app.state.gateway_services.http.proxy(request, "marketing-service")


@router.get("/research/tasks")
async def list_research_tasks(request: Request, _=Depends(require_user_subject)):
    return await request.app.state.gateway_services.http.proxy(request, "research-service")


@router.post("/research/tasks")
async def create_research_task(request: Request, _=Depends(require_user_subject)):
    body = await request.body()
    request._body = body  # type: ignore[attr-defined]
    return await request.app.state.gateway_services.http.proxy(request, "research-service")


@router.get("/research/tasks/{task_id}")
async def get_research_task(request: Request, task_id: str, _=Depends(require_user_subject)):
    return await request.app.state.gateway_services.http.proxy(request, "research-service")
