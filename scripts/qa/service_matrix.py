from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class OpenApiSpec:
    name: str
    path: Path
    required_operations: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class ResponseContractCheck:
    spec_name: str
    path: str
    method: str
    status_code: int


@dataclass(frozen=True)
class ServiceRuntime:
    name: str
    module: str
    cwd: Path
    pythonpath: tuple[Path, ...]
    health_path: str = "/healthz"
    require_ready: bool = False


OPENAPI_SPECS: dict[str, OpenApiSpec] = {
    "admin-api": OpenApiSpec(
        name="admin-api",
        path=REPO_ROOT / "openapi" / "admin-api.openapi.yaml",
        required_operations={
            "/api/v1/admin/dashboard/summary": ("get",),
            "/api/v1/admin/knowledge-bases": ("get", "post"),
            "/api/v1/admin/knowledge-bases/{kb_id}/documents": ("get", "post"),
            "/api/v1/admin/knowledge-documents/{doc_id}": ("get",),
            "/api/v1/admin/knowledge-documents/{doc_id}/chunks": ("get",),
            "/api/v1/admin/jobs/{job_id}": ("get",),
            "/api/v1/admin/knowledge-documents/{doc_id}/reindex": ("post",),
            "/api/v1/admin/retrieval/search-preview": ("post",),
            "/api/v1/admin/retrieval/diagnostics": ("post",),
        },
    ),
    "auth-user-service": OpenApiSpec(
        name="auth-user-service",
        path=REPO_ROOT / "openapi" / "auth-user-service.openapi.yaml",
        required_operations={
            "/healthz": ("get",),
            "/api/v1/auth/login": ("post",),
            "/api/v1/auth/send-code": ("post",),
            "/api/v1/auth/refresh": ("post",),
            "/api/v1/auth/me": ("get",),
            "/api/v1/auth/logout": ("post",),
            "/api/v1/auth/password/forgot": ("post",),
            "/api/v1/auth/password/reset": ("post",),
            "/api/v1/users/me": ("patch",),
            "/api/v1/users/me/change-password": ("post",),
            "/api/v1/admin/auth/login": ("post",),
            "/api/v1/admin/auth/me": ("get",),
            "/api/v1/admin/auth/action-confirmations": ("post",),
            "/internal/v1/auth/validate-token": ("get",),
            "/internal/v1/auth/check-permission": ("post",),
            "/internal/v1/auth/invalidate-subject-cache": ("post",),
        },
    ),
    "business-tools-service": OpenApiSpec(
        name="business-tools-service",
        path=REPO_ROOT / "openapi" / "business-tools-service.openapi.yaml",
        required_operations={
            "/healthz": ("get",),
            "/internal/v1/tools": ("get",),
            "/internal/v1/tools/{tool_name}": ("get",),
            "/internal/v1/execute/{tool_name}": ("post",),
            "/internal/v1/preflight/{tool_name}": ("post",),
            "/internal/v1/compensations/execute": ("post",),
        },
    ),
    "knowledge-service": OpenApiSpec(
        name="knowledge-service",
        path=REPO_ROOT / "openapi" / "knowledge-service.openapi.yaml",
        required_operations={
            "/healthz": ("get",),
            "/metrics": ("get",),
            "/api/knowledge/v1/sources": ("get", "post"),
            "/api/knowledge/v1/documents": ("get",),
            "/api/knowledge/v1/chunks": ("get",),
            "/api/knowledge/v1/ingestions": ("get",),
            "/api/knowledge/v1/overview": ("get",),
            "/api/knowledge/v1/imports:preview": ("get",),
            "/api/knowledge/v1/documents:ingest": ("post",),
            "/api/knowledge/v1/files:ingest": ("post",),
            "/api/knowledge/v1/catalog:bootstrap": ("post",),
            "/api/knowledge/v1/search": ("post",),
        },
    ),
    "marketing-service": OpenApiSpec(
        name="marketing-service",
        path=REPO_ROOT / "openapi" / "marketing-service.openapi.yaml",
        required_operations={
            "/healthz": ("get",),
            "/api/v1/marketing/campaigns": ("get",),
            "/api/v1/marketing/copy/generate": ("post",),
            "/api/v1/marketing/promotion-links/generate": ("post",),
            "/api/v1/marketing/posters": ("get", "post"),
            "/api/v1/marketing/posters/{task_id}": ("get",),
        },
    ),
    "orchestrator-service": OpenApiSpec(
        name="orchestrator-service",
        path=REPO_ROOT / "openapi" / "orchestrator-service.openapi.yaml",
        required_operations={
            "/healthz": ("get",),
            "/api/v1/agents": ("get",),
            "/api/v1/route": ("post",),
            "/api/v1/chat/sessions": ("get", "post"),
            "/api/v1/chat/sessions/{conversation_id}": ("get", "patch"),
            "/api/v1/chat/sessions/{conversation_id}/messages": ("get",),
            "/api/v1/chat/sessions/{conversation_id}/archive": ("post",),
            "/api/v1/chat/sessions/{conversation_id}/restore": ("post",),
            "/api/v1/chat/sessions/{conversation_id}/retry": ("post",),
            "/api/v1/chat/sessions/{conversation_id}/continue": ("post",),
            "/api/v1/chat/sessions/{conversation_id}/cancel": ("post",),
            "/api/v1/chat/completions": ("post",),
            "/api/v1/sessions/{conversation_id}/messages": ("post",),
            "/api/v1/sessions/{conversation_id}/messages/stream": ("post",),
            "/api/v1/sessions/{conversation_id}/state": ("get",),
            "/api/v1/sessions/{conversation_id}/rollback": ("post",),
            "/internal/v1/orchestrator/chat": ("post",),
        },
    ),
    "rag-service": OpenApiSpec(
        name="rag-service",
        path=REPO_ROOT / "openapi" / "rag-service.openapi.yaml",
        required_operations={
            "/healthz": ("get",),
            "/metrics": ("get",),
            "/api/rag/v1/capabilities": ("get",),
            "/api/rag/v1/retrieve": ("post",),
            "/api/rag/v1/diagnose": ("post",),
            "/api/rag/v1/answer": ("post",),
        },
    ),
    "research-service": OpenApiSpec(
        name="research-service",
        path=REPO_ROOT / "openapi" / "research-service.openapi.yaml",
        required_operations={
            "/healthz": ("get",),
            "/api/v1/research/tasks": ("get", "post"),
            "/api/v1/research/tasks/{task_id}": ("get",),
        },
    ),
    "tool-hub-service": OpenApiSpec(
        name="tool-hub-service",
        path=REPO_ROOT / "openapi" / "tool-hub-service.openapi.yaml",
        required_operations={
            "/healthz": ("get",),
            "/api/v1/tools": ("get",),
            "/api/v1/tools/{tool_name}": ("get",),
            "/internal/v1/tool-compensations/call": ("post",),
            "/api/v1/tools/{tool_name}/invoke": ("post",),
            "/api/v1/tools/call": ("post",),
            "/api/v1/tools/preflight": ("post",),
            "/api/v1/tool-calls": ("get",),
            "/api/v1/tool-calls/{tool_call_id}": ("get",),
            "/tools/list": ("get",),
            "/tools/call": ("post",),
        },
    ),
}


REPRESENTATIVE_RESPONSE_CONTRACTS: tuple[ResponseContractCheck, ...] = (
    ResponseContractCheck("auth-user-service", "/api/v1/auth/login", "post", 200),
    ResponseContractCheck("auth-user-service", "/api/v1/auth/me", "get", 200),
    ResponseContractCheck("marketing-service", "/api/v1/marketing/campaigns", "get", 200),
    ResponseContractCheck("marketing-service", "/api/v1/marketing/copy/generate", "post", 200),
    ResponseContractCheck("marketing-service", "/api/v1/marketing/posters", "post", 202),
    ResponseContractCheck("research-service", "/api/v1/research/tasks", "post", 202),
    ResponseContractCheck("research-service", "/api/v1/research/tasks/{task_id}", "get", 200),
    ResponseContractCheck("knowledge-service", "/api/knowledge/v1/catalog:bootstrap", "post", 200),
    ResponseContractCheck("knowledge-service", "/api/knowledge/v1/search", "post", 200),
    ResponseContractCheck("admin-api", "/api/v1/admin/knowledge-bases", "post", 201),
    ResponseContractCheck("admin-api", "/api/v1/admin/knowledge-documents/{doc_id}", "get", 200),
    ResponseContractCheck("admin-api", "/api/v1/admin/retrieval/diagnostics", "post", 200),
    ResponseContractCheck("rag-service", "/api/rag/v1/diagnose", "post", 200),
    ResponseContractCheck("rag-service", "/api/rag/v1/answer", "post", 200),
    ResponseContractCheck("business-tools-service", "/internal/v1/tools/{tool_name}", "get", 200),
    ResponseContractCheck("business-tools-service", "/internal/v1/preflight/{tool_name}", "post", 200),
    ResponseContractCheck("tool-hub-service", "/api/v1/tools", "get", 200),
    ResponseContractCheck("tool-hub-service", "/api/v1/tools/preflight", "post", 200),
    ResponseContractCheck("tool-hub-service", "/api/v1/tools/call", "post", 200),
    ResponseContractCheck("tool-hub-service", "/api/v1/tools/{tool_name}/invoke", "post", 200),
    ResponseContractCheck("tool-hub-service", "/api/v1/tool-calls", "get", 200),
    ResponseContractCheck("orchestrator-service", "/api/v1/chat/sessions", "post", 200),
    ResponseContractCheck("orchestrator-service", "/api/v1/chat/completions", "post", 200),
    ResponseContractCheck("orchestrator-service", "/api/v1/sessions/{conversation_id}/state", "get", 200),
)


SERVICE_RUNTIMES: dict[str, ServiceRuntime] = {
    "auth-user-service": ServiceRuntime(
        name="auth-user-service",
        module="app.main:app",
        cwd=REPO_ROOT / "apps" / "auth-user-service",
        pythonpath=(REPO_ROOT / "apps" / "auth-user-service",),
    ),
    "marketing-service": ServiceRuntime(
        name="marketing-service",
        module="app.main:app",
        cwd=REPO_ROOT / "apps" / "marketing-service",
        pythonpath=(REPO_ROOT / "apps" / "marketing-service",),
    ),
    "research-service": ServiceRuntime(
        name="research-service",
        module="app.main:app",
        cwd=REPO_ROOT / "apps" / "research-service",
        pythonpath=(REPO_ROOT / "apps" / "research-service",),
    ),
    "knowledge-service": ServiceRuntime(
        name="knowledge-service",
        module="app.main:app",
        cwd=REPO_ROOT / "apps" / "knowledge-service",
        pythonpath=(REPO_ROOT / "apps" / "knowledge-service",),
        require_ready=True,
    ),
    "rag-service": ServiceRuntime(
        name="rag-service",
        module="app.main:app",
        cwd=REPO_ROOT / "apps" / "rag-service",
        pythonpath=(REPO_ROOT / "apps" / "rag-service",),
        require_ready=True,
    ),
    "business-tools-service": ServiceRuntime(
        name="business-tools-service",
        module="business_tools_service.main:app",
        cwd=REPO_ROOT / "apps" / "business-tools",
        pythonpath=(REPO_ROOT / "apps" / "business-tools" / "src",),
    ),
    "tool-hub-service": ServiceRuntime(
        name="tool-hub-service",
        module="app.main:app",
        cwd=REPO_ROOT / "apps" / "tool-hub-service",
        pythonpath=(REPO_ROOT / "apps" / "tool-hub-service",),
    ),
    "orchestrator-service": ServiceRuntime(
        name="orchestrator-service",
        module="app.main:app",
        cwd=REPO_ROOT / "apps" / "orchestrator-service",
        pythonpath=(REPO_ROOT / "apps" / "orchestrator-service",),
    ),
}


SMOKE_SCENARIOS: dict[str, str] = {
    "auth-marketing-research": "Validate bearer-token compatibility and representative user flows.",
    "knowledge-rag-admin": "Validate knowledge ingestion/search plus admin and RAG diagnostics surfaces.",
    "business-tools-tool-hub": "Validate direct provider and tool-hub HTTP dispatch/preflight/audit flows.",
    "orchestrator-billing": "Validate orchestrator HTTP integration through tool-hub into business-tools.",
}
