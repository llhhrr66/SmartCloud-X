from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.common import canonical_success
from app.services.auth import ensure_permission, require_admin_subject
from app.services.dashboard import build_admin_dashboard_summary
from app.services.request_context import get_request_identity
from app.api.routes.business import _execute_business_tool


router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/dashboard/summary")
async def dashboard_summary(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:ops.read")
    services = request.app.state.gateway_services
    upstream_statuses = {
        name: await services.http.probe(name)
        for name in ("knowledge-service", "rag-service", "orchestrator-service")
    }
    sessions = await services.http.request_json(
        "orchestrator-service",
        "GET",
        "/api/v1/chat/sessions",
        headers={
            services.settings.request_id_header: request.state.request_id,
            services.settings.trace_id_header: request.state.trace_id,
        },
        params={"page": 1, "page_size": 1},
        request_identity=get_request_identity(request),
    )
    session_data = sessions.get("data") if isinstance(sessions.get("data"), dict) else sessions

    # Query billing cost from business-tools
    billing_total_cost = 0.0
    try:
        billing_result = await _execute_business_tool(
            request,
            subject,
            tool_name="billing.query_statement",
            payload={"range": "this_month"},
        )
        billing_data = billing_result.get("result") if isinstance(billing_result.get("result"), dict) else billing_result.get("data", {})
        billing_total_cost = float(billing_data.get("total_amount") or 0)
    except Exception:
        pass

    summary = build_admin_dashboard_summary(
        conversation_total=int(session_data.get("total") or 0),
        upstream_statuses=upstream_statuses,
        total_cost=billing_total_cost,
    )
    return canonical_success(summary, request.state.request_id)


@router.api_route("/knowledge-bases", methods=["GET", "POST"])
async def knowledge_bases(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.read" if request.method == "GET" else "admin:kb.write")
    return await request.app.state.gateway_services.http.proxy(request, "knowledge-service")


@router.patch("/knowledge-bases/{kb_id}")
async def update_knowledge_base(request: Request, kb_id: str, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.write")
    return await request.app.state.gateway_services.http.proxy(request, "knowledge-service")


@router.api_route("/knowledge-bases/{kb_id}/documents", methods=["GET", "POST"])
async def knowledge_base_documents(request: Request, kb_id: str, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.read" if request.method == "GET" else "admin:kb.write")
    return await request.app.state.gateway_services.http.proxy(request, "knowledge-service")


@router.get("/knowledge-documents/{doc_id}")
async def knowledge_document_detail(request: Request, doc_id: str, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.read")
    return await request.app.state.gateway_services.http.proxy(request, "knowledge-service")


@router.get("/knowledge-documents/{doc_id}/chunks")
async def knowledge_document_chunks(request: Request, doc_id: str, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.read")
    return await request.app.state.gateway_services.http.proxy(request, "knowledge-service")


@router.post("/knowledge-documents/{doc_id}/reindex")
async def reindex_knowledge_document(request: Request, doc_id: str, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.write")
    return await request.app.state.gateway_services.http.proxy(request, "knowledge-service")


@router.get("/jobs/{job_id}")
async def admin_job(request: Request, job_id: str, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:job.read")
    return await request.app.state.gateway_services.http.proxy(request, "knowledge-service")


@router.post("/retrieval/search-preview")
async def search_preview(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.read")
    return await request.app.state.gateway_services.http.proxy(request, "knowledge-service")


@router.post("/retrieval/diagnostics")
async def retrieval_diagnostics(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.read")
    return await request.app.state.gateway_services.http.proxy(request, "rag-service")


@router.api_route("/files/uploads", methods=["POST"])
async def admin_file_uploads(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.write")
    return await request.app.state.gateway_services.http.proxy(request, "knowledge-service")


@router.put("/files/uploads/{upload_id}/content")
async def admin_file_upload_content(request: Request, upload_id: str, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.write")
    return await request.app.state.gateway_services.http.proxy(request, "knowledge-service")


@router.post("/files/uploads/{upload_id}:complete")
async def admin_file_upload_complete(request: Request, upload_id: str, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.write")
    return await request.app.state.gateway_services.http.proxy(request, "knowledge-service")


@router.post("/dify/datasets/sync/{kb_id}")
async def sync_dify_dataset(request: Request, kb_id: str, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:kb.write")
    return await request.app.state.gateway_services.http.proxy(request, "knowledge-service")


@router.api_route("/agents", methods=["GET"])
async def admin_agents(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:ops.read")
    return await request.app.state.gateway_services.http.proxy(request, "orchestrator-service")


@router.patch("/agents/{agent_code}")
async def update_admin_agent(request: Request, agent_code: str, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:ops.write")
    return await request.app.state.gateway_services.http.proxy(request, "orchestrator-service")


@router.api_route("/marketing/campaigns", methods=["GET", "POST"])
async def admin_marketing_campaigns(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:marketing.read" if request.method == "GET" else "admin:marketing.write")
    return await request.app.state.gateway_services.http.proxy(
        request,
        "marketing-service",
        path="/api/v1/marketing/admin/campaigns",
    )


@router.api_route("/marketing/campaigns/{campaign_id}", methods=["PUT", "DELETE"])
async def admin_marketing_campaign(request: Request, campaign_id: str, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:marketing.write")
    return await request.app.state.gateway_services.http.proxy(
        request,
        "marketing-service",
        path=f"/api/v1/marketing/admin/campaigns/{campaign_id}",
    )


@router.api_route("/llm-providers", methods=["GET", "POST"])
async def admin_llm_providers(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:ops.read" if request.method == "GET" else "admin:ops.write")
    return await request.app.state.gateway_services.http.proxy(request, "orchestrator-service", path="/internal/v1/llm-providers")


@router.api_route("/llm-providers/{provider_id}", methods=["GET", "PATCH", "DELETE"])
async def admin_llm_provider(request: Request, provider_id: str, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:ops.read" if request.method == "GET" else "admin:ops.write")
    return await request.app.state.gateway_services.http.proxy(request, "orchestrator-service", path=f"/internal/v1/llm-providers/{provider_id}")


@router.post("/llm-providers/test")
async def admin_llm_provider_test(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:ops.read")
    return await request.app.state.gateway_services.http.proxy(request, "orchestrator-service", path="/internal/v1/llm-providers/test")


@router.post("/llm-providers/models")
async def admin_llm_provider_models(request: Request, subject=Depends(require_admin_subject)):
    ensure_permission(subject, "admin:ops.read")
    return await request.app.state.gateway_services.http.proxy(request, "orchestrator-service", path="/internal/v1/llm-providers/models")
