from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scripts.qa.openapi_contracts import ContractValidationError, OpenApiContract


@dataclass(frozen=True)
class DocumentedContractDrift:
    spec_name: str
    path: str
    method: str
    status_code: int
    change_request: str
    summary: str


KNOWN_CONTRACT_DRIFTS: dict[tuple[str, str, str, int], DocumentedContractDrift] = {
    (
        "auth-user-service",
        "/api/v1/auth/login",
        "post",
        200,
    ): DocumentedContractDrift(
        spec_name="auth-user-service",
        path="/api/v1/auth/login",
        method="post",
        status_code=200,
        change_request=(
            "docs/contracts/change-requests/2026-04-16-auth-user-profile-avatar-nullability-alignment.md"
        ),
        summary="Live auth responses allow null avatar_url for the demo user profile, but the frozen profile schema still requires a non-empty string.",
    ),
    (
        "auth-user-service",
        "/api/v1/auth/me",
        "get",
        200,
    ): DocumentedContractDrift(
        spec_name="auth-user-service",
        path="/api/v1/auth/me",
        method="get",
        status_code=200,
        change_request=(
            "docs/contracts/change-requests/2026-04-16-auth-user-profile-avatar-nullability-alignment.md"
        ),
        summary="Live auth responses allow null avatar_url for the demo user profile, but the frozen profile schema still requires a non-empty string.",
    ),
    (
        "orchestrator-service",
        "/api/v1/chat/sessions",
        "post",
        200,
    ): DocumentedContractDrift(
        spec_name="orchestrator-service",
        path="/api/v1/chat/sessions",
        method="post",
        status_code=200,
        change_request=(
            "docs/contracts/change-requests/2026-04-16-api-envelope-null-error-alignment.md"
        ),
        summary="Successful orchestrator envelopes emit error=null, but the frozen ApiEnvelope schema still requires an object when the field is present.",
    ),
    (
        "orchestrator-service",
        "/api/v1/chat/completions",
        "post",
        200,
    ): DocumentedContractDrift(
        spec_name="orchestrator-service",
        path="/api/v1/chat/completions",
        method="post",
        status_code=200,
        change_request=(
            "docs/contracts/change-requests/2026-04-16-api-envelope-null-error-alignment.md"
        ),
        summary="Successful orchestrator envelopes emit error=null, but the frozen ApiEnvelope schema still requires an object when the field is present.",
    ),
    (
        "orchestrator-service",
        "/api/v1/sessions/{conversation_id}/state",
        "get",
        200,
    ): DocumentedContractDrift(
        spec_name="orchestrator-service",
        path="/api/v1/sessions/{conversation_id}/state",
        method="get",
        status_code=200,
        change_request=(
            "docs/contracts/change-requests/2026-04-16-api-envelope-null-error-alignment.md"
        ),
        summary="Successful orchestrator envelopes emit error=null, but the frozen ApiEnvelope schema still requires an object when the field is present.",
    ),
    (
        "research-service",
        "/api/v1/research/tasks/{task_id}",
        "get",
        200,
    ): DocumentedContractDrift(
        spec_name="research-service",
        path="/api/v1/research/tasks/{task_id}",
        method="get",
        status_code=200,
        change_request=(
            "docs/contracts/change-requests/2026-04-16-research-task-null-error-message-alignment.md"
        ),
        summary="Completed research task detail responses allow error_message=null, but the frozen contract still requires a string when the field is present.",
    ),
    (
        "admin-api",
        "/api/v1/admin/knowledge-documents/{doc_id}",
        "get",
        200,
    ): DocumentedContractDrift(
        spec_name="admin-api",
        path="/api/v1/admin/knowledge-documents/{doc_id}",
        method="get",
        status_code=200,
        change_request=(
            "docs/contracts/change-requests/2026-04-16-admin-document-detail-null-error-message-alignment.md"
        ),
        summary="Admin knowledge document detail responses allow document.error_message=null, but the frozen admin contract still requires a string when the field is present.",
    ),
    (
        "tool-hub-service",
        "/api/v1/tools/{tool_name}/invoke",
        "post",
        200,
    ): DocumentedContractDrift(
        spec_name="tool-hub-service",
        path="/api/v1/tools/{tool_name}/invoke",
        method="post",
        status_code=200,
        change_request=(
            "docs/contracts/change-requests/2026-04-16-tool-hub-invoke-response-metadata-alignment.md"
        ),
        summary="Direct invoke responses expose additive auth_requirements and downstream_target metadata, but the frozen response schema currently rejects those fields.",
    ),
    (
        "tool-hub-service",
        "/api/v1/tool-calls",
        "get",
        200,
    ): DocumentedContractDrift(
        spec_name="tool-hub-service",
        path="/api/v1/tool-calls",
        method="get",
        status_code=200,
        change_request=(
            "docs/contracts/change-requests/2026-04-16-tool-hub-audit-status-completed-alignment.md"
        ),
        summary="Tool-hub audit records emit status=completed for successful calls, but the frozen audit status enum still excludes that value.",
    ),
}


def validate_live_response_contract(
    contracts: dict[str, OpenApiContract],
    spec_name: str,
    path: str,
    method: str,
    status_code: int,
    payload: Any,
) -> DocumentedContractDrift | None:
    try:
        contracts[spec_name].validate_response(path, method, status_code, payload)
        return None
    except ContractValidationError as exc:
        drift = KNOWN_CONTRACT_DRIFTS.get((spec_name, path, method.lower(), status_code))
        if drift is None and isinstance(payload, dict):
            message = str(exc)
            if (
                payload.get("error") is None
                and "error: None is not of type 'object'" in message
            ) or (
                payload.get("meta") is None
                and "meta: None is not of type 'object'" in message
            ):
                drift = DocumentedContractDrift(
                    spec_name=spec_name,
                    path=path,
                    method=method.lower(),
                    status_code=status_code,
                    change_request=(
                        "docs/contracts/change-requests/2026-04-16-api-envelope-null-error-alignment.md"
                    ),
                    summary=(
                        "Successful shared ApiEnvelope responses emit null optional object fields, but the frozen "
                        "shared envelope schema still requires objects when those fields are present."
                    ),
                )
        if drift is None:
            raise RuntimeError(str(exc)) from exc
        return drift
