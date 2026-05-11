from __future__ import annotations

from fastapi import APIRouter, Request


router = APIRouter(prefix="/api/public/knowledge", tags=["public-knowledge"])


@router.get("/documents/{doc_id}")
async def public_knowledge_document(request: Request, doc_id: str):
    return await request.app.state.gateway_services.http.proxy(
        request,
        "knowledge-service",
        path=f"/api/knowledge/v1/documents/{doc_id}",
    )
