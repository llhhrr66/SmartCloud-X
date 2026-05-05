from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.services.auth import ensure_permission, require_admin_subject


router = APIRouter(tags=["owner-local"])


@router.api_route("/api/knowledge/v1/sources", methods=["GET", "POST"])
async def knowledge_sources(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.read" if request.method == "GET" else "admin:kb.write")
    return await request.app.state.gateway_services.http.proxy(request, "knowledge-service")


@router.api_route("/api/knowledge/v1/documents", methods=["GET"])
async def knowledge_documents(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.read")
    return await request.app.state.gateway_services.http.proxy(request, "knowledge-service")


@router.api_route("/api/knowledge/v1/chunks", methods=["GET"])
async def knowledge_chunks(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.read")
    return await request.app.state.gateway_services.http.proxy(request, "knowledge-service")


@router.api_route("/api/knowledge/v1/ingestions", methods=["GET"])
async def knowledge_ingestions(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.read")
    return await request.app.state.gateway_services.http.proxy(request, "knowledge-service")


@router.api_route("/api/knowledge/v1/admin/audit-records", methods=["GET"])
async def knowledge_admin_audit_records(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.read")
    return await request.app.state.gateway_services.http.proxy(request, "knowledge-service")


@router.api_route("/api/knowledge/v1/overview", methods=["GET"])
async def knowledge_overview(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.read")
    return await request.app.state.gateway_services.http.proxy(request, "knowledge-service")


@router.api_route("/api/knowledge/v1/snapshot", methods=["GET"])
async def knowledge_snapshot(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.read")
    return await request.app.state.gateway_services.http.proxy(request, "knowledge-service")


@router.api_route("/api/knowledge/v1/imports:preview", methods=["GET"])
async def knowledge_imports_preview(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.read")
    return await request.app.state.gateway_services.http.proxy(request, "knowledge-service")


@router.api_route("/api/knowledge/v1/documents/{doc_id}", methods=["GET"])
async def knowledge_document_detail(request: Request, doc_id: str, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.read")
    return await request.app.state.gateway_services.http.proxy(request, "knowledge-service")


@router.api_route("/api/knowledge/v1/documents:ingest", methods=["POST"])
async def knowledge_documents_ingest(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.write")
    return await request.app.state.gateway_services.http.proxy(request, "knowledge-service")


@router.api_route("/api/knowledge/v1/files:ingest", methods=["POST"])
async def knowledge_files_ingest(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.write")
    return await request.app.state.gateway_services.http.proxy(request, "knowledge-service")


@router.api_route("/api/knowledge/v1/catalog:bootstrap", methods=["POST"])
async def knowledge_catalog_bootstrap(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.write")
    return await request.app.state.gateway_services.http.proxy(request, "knowledge-service")


@router.api_route("/api/knowledge/v1/search", methods=["POST"])
async def knowledge_search(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.read")
    return await request.app.state.gateway_services.http.proxy(request, "knowledge-service")


@router.api_route("/api/rag/v1/capabilities", methods=["GET"])
async def rag_capabilities(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.read")
    return await request.app.state.gateway_services.http.proxy(request, "rag-service")


@router.api_route("/api/rag/v1/retrieve", methods=["POST"])
async def rag_retrieve(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.read")
    return await request.app.state.gateway_services.http.proxy(request, "rag-service")


@router.api_route("/api/rag/v1/diagnose", methods=["POST"])
async def rag_diagnose(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.read")
    return await request.app.state.gateway_services.http.proxy(request, "rag-service")


@router.api_route("/api/rag/v1/answer", methods=["POST"])
async def rag_answer(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.read")
    return await request.app.state.gateway_services.http.proxy(request, "rag-service")
