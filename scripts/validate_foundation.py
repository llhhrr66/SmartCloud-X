#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - fallback for minimal runtimes
    yaml = None


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_ROOT = ROOT / 'packages/common-schemas/src/schemas'
OPENAPI_ROOT = ROOT / 'openapi'

REQUIRED_FILES = [
    ROOT / '.env.example',
    ROOT / 'README.md',
    ROOT / 'docs/contracts/change-requests/CHANGE_REQUEST_TEMPLATE.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-orchestrator-chat-compat-delete-baseline.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-orchestrator-admin-agent-config-baseline.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-orchestrator-streaming-tool-audit-idempotency.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-orchestrator-session-context-patch-promotion.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-business-tools-execute-tool-result-alignment.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-orchestrator-session-continue-baseline.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-orchestrator-cancel-tool-policy-baseline.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-tool-preflight-clarification-contract-baseline.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-tool-query-cache-audit-tag-promotion.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-tool-hub-internal-tool-call-result-fidelity.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-orchestrator-response-review-baseline.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-tool-user-action-hint-continuation-metadata.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-api-envelope-null-error-alignment.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-admin-document-detail-null-error-message-alignment.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-admin-kb-document-detail-job-query-promotion.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-admin-kb-update-promotion.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-agent-tool-metadata-contract-promotion.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-orchestrator-agent-route-journal-internal-caller-policy.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-provider-backed-tool-contract-discovery-baseline.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-research-task-null-error-message-alignment.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-runtime-readiness-health-baseline.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-tool-hub-audit-status-completed-alignment.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-tool-hub-invoke-response-metadata-alignment.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-tool-session-context-dependency-metadata-promotion.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-auth-marketing-research-marketing-copy-promotion-link-baseline.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-auth-marketing-research-marketing-generated-artifact-history.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-auth-marketing-research-alias-status-result-routes.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-auth-user-profile-avatar-nullability-alignment.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-auth-marketing-research-runtime-backend-health-baseline.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-business-tools-redis-namespace-alignment.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-frontend-sdk-foundation-error-code-export-alignment.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-frontend-sdk-chat-stream-events-not-found-promotion.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-frontend-sdk-icp-application-list-contract-promotion.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-orchestrator-auth-continuation-user-profile-patch.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-persistence-backend-contract-baseline.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-runtime-mysql-redis-config-promotion.md',
    ROOT / 'docs/contracts/change-requests/2026-04-16-trace-context-nullability-alignment.md',
    ROOT / 'docs/contracts/foundation-baseline.md',
    ROOT / 'docs/contracts/shared/admin-api-baseline.md',
    ROOT / 'docs/contracts/shared/api-conventions.md',
    ROOT / 'docs/contracts/shared/auth-contract.md',
    ROOT / 'docs/contracts/shared/persistence-backends.md',
    ROOT / 'docs/contracts/shared/runtime-config.md',
    ROOT / 'docs/contracts/shared/runtime-health.md',
    ROOT / 'docs/contracts/shared/schema-catalog.md',
    ROOT / 'docs/status/supervisor-foundation-status.md',
    ROOT / 'logs/supervisor-foundation/blockers.log',
    ROOT / 'logs/supervisor-foundation/decisions.log',
    ROOT / 'logs/supervisor-foundation/progress.log',
    ROOT / 'logs/supervisor-foundation/state.json',
    ROOT / 'openapi/admin-api.openapi.yaml',
    ROOT / 'openapi/auth-user-service.openapi.yaml',
    ROOT / 'openapi/business-tools-service.openapi.yaml',
    ROOT / 'openapi/components.openapi.yaml',
    ROOT / 'openapi/marketing-service.openapi.yaml',
    ROOT / 'openapi/research-service.openapi.yaml',
    ROOT / 'packages/common/README.md',
    ROOT / 'packages/common-auth/src/index.ts',
    ROOT / 'packages/common-schemas/errors/error_codes.yaml',
    ROOT / 'packages/common-schemas/src/index.ts',
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/chat-usage.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/chat-completion-request.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/chat-completion-response.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/compensation-execution-record.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/conversation-record.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/pending-user-action.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/response-review-issue.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/response-review.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/session-delete-response.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/session-cancel-request.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/session-cancel-response.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/admin/admin-action-confirmation-request.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/admin/admin-action-confirmation-response-data.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/admin/admin-agent-config-update-request.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/admin/admin-agent-list-data.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/admin/admin-agent-record.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/admin/admin-audit-list-data.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/admin/admin-audit-record.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/admin/admin-login-request.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/admin/admin-login-response-data.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/admin/admin-menu-item.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/admin/admin-session-profile.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/admin/dashboard-summary-data.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/admin/knowledge-base.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/admin/knowledge-chunk-stats.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/admin/knowledge-document-detail-data.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/admin/retrieval-diagnostics-data.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/auth/auth-user-profile.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/auth/change-password-request.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/auth/forgot-password-request.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/auth/forgot-password-response-data.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/auth/login-request.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/auth/login-response-data.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/auth/logout-request.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/auth/operation-status-data.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/auth/refresh-token-request.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/auth/refresh-token-response-data.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/auth/reset-password-request.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/auth/send-code-request.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/auth/send-code-response-data.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/auth/user-profile-update-request.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/canonical-success-envelope.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/user/marketing-copy-request.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/user/marketing-copy-list-data.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/user/marketing-copy-result.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/user/poster-result-data.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/user/promotion-link-request.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/user/promotion-link-list-data.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/user/promotion-link-result.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/user/research-task-result-data.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/external/user/research-task-status-data.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/runtime-dependency-readiness.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/runtime-health-status.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/runtime-readiness-status.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/auth/invalidate-subject-cache-request.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/auth/invalidate-subject-cache-response-data.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/auth/permission-check-request.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/auth/permission-check-response-data.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/auth/token-validation-response-data.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/business-tools/business-compensation-execute-request.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/business-tools/business-compensation-execute-response.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/knowledge/knowledge-runtime-snapshot.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/agent-task.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/agent-execution-risk-flag.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/handoff-step.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/session-continue-request.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/session-list-response.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/session-rollback-response.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/session-state-snapshot.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/stream-event.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/stream-event-page.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/stream-event-record.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/tool-plan-item.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/tool-context-item.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/user-profile-patch.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/tool-hub/compensation-call-request.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/tool-hub/compensation-call-response.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/tool-hub/tool-compensation-action.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/tool-hub/tool-call-audit-record.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/tool-hub/tool-preflight-result.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/tool-hub/tool-preflight-response.schema.json',
    ROOT / 'packages/common-schemas/src/schemas/internal/tool-hub/tool-user-action-hint.schema.json',
    ROOT / 'packages/common/src/index.ts',
    ROOT / 'scripts/check_foundation_done.sh',
    ROOT / 'scripts/run_supervisor_foundation.sh',
    ROOT / 'scripts/run_supervisor_web_user.sh',
    ROOT / 'scripts/run_supervisor_orchestrator.sh',
    ROOT / 'scripts/run_supervisor_knowledge_rag.sh',
    ROOT / 'scripts/run_supervisor_auth_marketing_research.sh',
    ROOT / 'scripts/run_supervisor_frontend_sdk.sh',
    ROOT / 'scripts/run_supervisor_integration_qa.sh',
    ROOT / 'scripts/prompts/supervisor-foundation.md',
    ROOT / 'scripts/prompts/supervisor-web-user.md',
    ROOT / 'scripts/prompts/supervisor-orchestrator.md',
    ROOT / 'scripts/prompts/supervisor-knowledge-rag.md',
    ROOT / 'scripts/prompts/supervisor-auth-marketing-research.md',
    ROOT / 'scripts/prompts/supervisor-frontend-sdk.md',
    ROOT / 'scripts/prompts/supervisor-integration-qa.md',
]

OPENAPI_REQUIRED_KEYS = ('openapi', 'info', 'paths', 'components', 'x-owner-service')
REQUIRED_STATE_KEYS = ('supervisor', 'status', 'updatedAt', 'ownedPaths', 'deliverables', 'validations')
REQUIRED_ERROR_CODES = {
    'CHAT_CONVERSATION_ARCHIVED',
    'CHAT_CONVERSATION_NOT_FOUND',
    'CHAT_CONTINUATION_NOT_AVAILABLE',
    'CHAT_CONVERSATION_RUNNING',
    'CHAT_CONVERSATION_RESTORE_INVALID',
    'CHAT_MESSAGE_CANCELLED',
    'CHAT_MESSAGE_NOT_FOUND',
    'CHAT_MESSAGE_NOT_RUNNING',
    'CHAT_STREAM_EVENTS_NOT_FOUND',
    'IDEMPOTENCY_CONFLICT',
    'ORCH_AGENT_NOT_FOUND',
    'ORCH_SESSION_STATE_NOT_FOUND',
    'ORCH_TOOL_CALL_NOT_FOUND',
}
KNOWN_OPENAPI_OWNER_SERVICES = {
    'auth-user-service',
    'business-tools-service',
    'gateway-service',
    'knowledge-service',
    'marketing-service',
    'orchestrator-service',
    'rag-service',
    'research-service',
    'supervisor-foundation',
    'tool-hub-service',
}
REQUIRED_COMMON_STRINGS = {
    "'auth-user-service'",
    "'marketing-service'",
    "'research-service'",
    "'gateway-service'",
    "'supervisor-auth-marketing-research'",
    "'supervisor-frontend-sdk'",
    "'supervisor-integration-qa'",
    'platformServiceDescriptors',
    'serviceOwningSupervisorNames',
    'sharedScopeSupervisorNames',
    'PlatformServiceName',
    'getPlatformServiceDescriptor',
    'isPlatformServiceName',
    'supervisorNames',
    'isServiceOwningSupervisorName',
    'isSharedScopeSupervisorName',
    'isSupervisorName',
}
README_REQUIRED_STRINGS = {
    '7 个 supervisor 启动脚本模板',
    '5. auth + marketing + research',
    '6. frontend-sdk',
    '7. integration + qa',
}
COMMON_README_REQUIRED_STRINGS = {
    'seven-supervisor workspace model',
    'serviceOwningSupervisorNames',
    'sharedScopeSupervisorNames',
}
API_CONVENTIONS_REQUIRED_STRINGS = {
    'pending_user_actions[]',
    'user_action_hint',
    'user_profile_bindings',
    'user_profile_patch',
    'clarify-tool-input',
    'collect-auth-context',
    'user-confirmation',
    'XCallerServiceHeader',
}
FOUNDATION_BASELINE_REQUIRED_STRINGS = {
    'full seven-supervisor workspace registry',
    '`packages/frontend-sdk/` adoption is still being rolled out by its assigned owner',
    'all seven supervisor run/prompt entrypoints',
    '`review_result` execution-event variant',
    '`review-answer` checkpoint marker',
    '`FoundationErrorCode` / `foundationErrorCodes`',
    '`user_profile_patch` continuation input',
    'explicit `null` optional scope members',
    'shared persistence/backend matrix',
    '`CHAT_STREAM_EVENTS_NOT_FOUND`',
}
ORCHESTRATOR_OPENAPI_REQUIRED_STRINGS = {
    'review_result',
    'review-answer',
    'lightweight `review` metadata',
    'pending_user_actions',
    'user_profile_patch',
}
TOOL_HUB_OPENAPI_REQUIRED_STRINGS = {
    'user_action_hint',
    'user_profile_bindings',
}
BUSINESS_TOOLS_OPENAPI_REQUIRED_STRINGS = {
    'user_action_hint',
    'user_profile_bindings',
}
COMMON_OWNER_ASSIGNMENT_CHECKS = {
    'auth-user-service': 'supervisor-auth-marketing-research',
    'marketing-service': 'supervisor-auth-marketing-research',
    'research-service': 'supervisor-auth-marketing-research',
}
REQUIRED_OPENAPI_PATHS = {
    'admin-api.openapi.yaml': (
        '/api/v1/admin/dashboard/summary',
        '/api/v1/admin/knowledge-bases',
        '/api/v1/admin/knowledge-bases/{kb_id}',
        '/api/v1/admin/knowledge-bases/{kb_id}/documents',
        '/api/v1/admin/knowledge-documents/{doc_id}',
        '/api/v1/admin/knowledge-documents/{doc_id}/chunks',
        '/api/v1/admin/jobs/{job_id}',
        '/api/v1/admin/knowledge-documents/{doc_id}/reindex',
        '/api/v1/admin/retrieval/search-preview',
        '/api/v1/admin/retrieval/diagnostics',
    ),
    'auth-user-service.openapi.yaml': (
        '/api/v1/auth/login',
        '/api/v1/auth/forgot-password',
        '/api/v1/auth/send-code',
        '/api/v1/auth/refresh',
        '/api/v1/auth/reset-password',
        '/api/v1/auth/me',
        '/api/v1/auth/profile',
        '/api/v1/auth/logout',
        '/api/v1/auth/change-password',
        '/api/v1/users/me',
        '/api/v1/users/me/change-password',
        '/api/v1/admin/auth/login',
        '/api/v1/admin/auth/me',
        '/api/v1/admin/auth/action-confirmations',
        '/internal/v1/auth/validate-token',
        '/internal/v1/auth/check-permission',
        '/internal/v1/auth/invalidate-subject-cache',
    ),
    'business-tools-service.openapi.yaml': (
        '/readyz',
        '/internal/v1/tools/{tool_name}',
        '/internal/v1/execute/{tool_name}',
        '/internal/v1/preflight/{tool_name}',
        '/internal/v1/compensations/execute',
    ),
    'marketing-service.openapi.yaml': (
        '/api/v1/marketing/campaigns',
        '/api/v1/marketing/copy/generate',
        '/api/v1/marketing/copies',
        '/api/v1/marketing/copies/{copy_id}',
        '/api/v1/marketing/promotion-links/generate',
        '/api/v1/marketing/promotion-links',
        '/api/v1/marketing/promotion-links/{link_id}',
        '/api/v1/marketing/posters',
        '/api/v1/marketing/posters/{task_id}',
        '/api/v1/marketing/posters/{task_id}/result',
    ),
    'knowledge-service.openapi.yaml': (
        '/api/knowledge/v1/admin/audit-records',
        '/api/knowledge/v1/imports:preview',
        '/api/knowledge/v1/files:ingest',
        '/api/knowledge/v1/ingestions',
        '/api/knowledge/v1/overview',
        '/api/knowledge/v1/snapshot',
        '/api/knowledge/v1/catalog:bootstrap',
    ),
    'orchestrator-service.openapi.yaml': (
        '/readyz',
        '/api/v1/chat/completions',
        '/api/v1/chat/sessions',
        '/api/v1/chat/sessions/{conversation_id}',
        '/api/v1/chat/sessions/{conversation_id}/agent-routes',
        '/api/v1/chat/sessions/{conversation_id}/cancel',
        '/api/v1/chat/sessions/{conversation_id}/continue',
        '/api/v1/chat/sessions/{conversation_id}/messages',
        '/api/v1/chat/sessions/{conversation_id}/messages/{message_id}/events',
        '/api/v1/chat/sessions/{conversation_id}/messages/{message_id}/events/stream',
        '/api/v1/chat/sessions/{conversation_id}/retry',
        '/api/v1/sessions/{conversation_id}/messages/stream',
        '/api/v1/sessions/{conversation_id}/rollback',
        '/api/v1/sessions/{conversation_id}/state',
    ),
    'rag-service.openapi.yaml': ('/api/rag/v1/diagnose',),
    'research-service.openapi.yaml': (
        '/api/v1/research/tasks',
        '/api/v1/research/tasks/{task_id}',
        '/api/v1/research/tasks/{task_id}/status',
        '/api/v1/research/tasks/{task_id}/result',
    ),
    'tool-hub-service.openapi.yaml': (
        '/readyz',
        '/api/v1/tool-calls',
        '/api/v1/tool-calls/{tool_call_id}',
        '/api/v1/tools/{tool_name}/invoke',
        '/api/v1/tools/call',
        '/api/v1/tools/preflight',
        '/internal/v1/tool-compensations/call',
    ),
}
REQUIRED_OPENAPI_OPERATIONS = {
    'admin-api.openapi.yaml': {
        '/api/v1/admin/knowledge-bases/{kb_id}': {'patch'},
    },
    'orchestrator-service.openapi.yaml': {
        '/readyz': {'get'},
        '/api/v1/chat/completions': {'post'},
        '/api/v1/chat/sessions/{conversation_id}': {'delete', 'get', 'patch'},
        '/api/v1/chat/sessions/{conversation_id}/agent-routes': {'get'},
        '/api/v1/chat/sessions/{conversation_id}/cancel': {'post'},
        '/api/v1/chat/sessions/{conversation_id}/continue': {'post'},
        '/api/v1/chat/sessions/{conversation_id}/messages/{message_id}/events': {'get'},
        '/api/v1/chat/sessions/{conversation_id}/messages/{message_id}/events/stream': {'get'},
    },
    'business-tools-service.openapi.yaml': {
        '/readyz': {'get'},
        '/internal/v1/tools/{tool_name}': {'get'},
        '/internal/v1/preflight/{tool_name}': {'post'},
    },
    'auth-user-service.openapi.yaml': {
        '/api/v1/auth/forgot-password': {'post'},
        '/api/v1/auth/reset-password': {'post'},
        '/api/v1/auth/profile': {'get', 'patch'},
        '/api/v1/auth/change-password': {'post'},
    },
    'marketing-service.openapi.yaml': {
        '/api/v1/marketing/copy/generate': {'post'},
        '/api/v1/marketing/copies': {'get'},
        '/api/v1/marketing/copies/{copy_id}': {'get'},
        '/api/v1/marketing/promotion-links/generate': {'post'},
        '/api/v1/marketing/promotion-links': {'get'},
        '/api/v1/marketing/promotion-links/{link_id}': {'get'},
        '/api/v1/marketing/posters/{task_id}/result': {'get'},
    },
    'research-service.openapi.yaml': {
        '/api/v1/research/tasks/{task_id}/status': {'get'},
        '/api/v1/research/tasks/{task_id}/result': {'get'},
    },
    'knowledge-service.openapi.yaml': {
        '/api/knowledge/v1/admin/audit-records': {'get'},
        '/api/knowledge/v1/snapshot': {'get'},
    },
    'tool-hub-service.openapi.yaml': {
        '/readyz': {'get'},
        '/api/v1/tool-calls': {'get'},
        '/api/v1/tools/{tool_name}/invoke': {'post'},
        '/api/v1/tools/call': {'post'},
        '/api/v1/tools/preflight': {'post'},
    },
}
REQUIRED_OPENAPI_QUERY_PARAMS = {
    ('knowledge-service.openapi.yaml', '/api/knowledge/v1/admin/audit-records', 'get'): {
        'page',
        'pageSize',
        'resourceType',
        'action',
        'operatorId',
    },
    ('knowledge-service.openapi.yaml', '/api/knowledge/v1/snapshot', 'get'): {
        'auditLimit',
    },
    ('marketing-service.openapi.yaml', '/api/v1/marketing/copies', 'get'): {
        'campaign_id',
        'page',
        'page_size',
        'sort_by',
        'sort_order',
        'tone',
    },
    ('marketing-service.openapi.yaml', '/api/v1/marketing/promotion-links', 'get'): {
        'campaign_id',
        'channel',
        'page',
        'page_size',
        'sort_by',
        'sort_order',
    },
    ('orchestrator-service.openapi.yaml', '/api/v1/chat/sessions/{conversation_id}/messages/{message_id}/events', 'get'): {
        'after_event_id',
        'limit',
    },
    ('orchestrator-service.openapi.yaml', '/api/v1/chat/sessions/{conversation_id}/messages/{message_id}/events/stream', 'get'): {
        'after_event_id',
        'limit',
    },
    ('tool-hub-service.openapi.yaml', '/api/v1/tool-calls', 'get'): {
        'audit_tag',
        'conversation_id',
        'idempotency_key',
    },
}
OPENAPI_HTTP_METHODS = {'get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace'}
REQUIRED_OPENAPI_PARAMETER_ENUM_VALUES = {
    ('tool-hub-service.openapi.yaml', '/api/v1/tool-calls', 'get', 'status'): {
        'completed',
        'invalid-payload',
    },
}
REQUIRED_SCHEMA_PROPERTIES = {
    ROOT / 'packages/common-schemas/src/schemas/runtime-dependency-readiness.schema.json': {
        'ready',
        'status',
        'mode',
        'service',
        'httpStatus',
        'notReadyComponents',
        'error',
    },
    ROOT / 'packages/common-schemas/src/schemas/runtime-health-status.schema.json': {
        'status',
        'service',
        'degraded_components',
        'runtime',
    },
    ROOT / 'packages/common-schemas/src/schemas/runtime-readiness-status.schema.json': {
        'status',
        'service',
        'not_ready_components',
        'runtime',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/chat-completion-request.schema.json': {
        'context',
        'options',
        'context_control',
        'client_meta',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/chat-completion-response.schema.json': {
        'answer',
        'citations',
        'tool_calls',
        'pending_user_actions',
        'usage',
        'finish_reason',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/pending-user-action.schema.json': {
        'tool_name',
        'tool_call_id',
        'action',
        'message',
        'session_context_bindings',
        'user_profile_bindings',
        'confirm_tool_names',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/response-review-issue.schema.json': {
        'code',
        'severity',
        'message',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/response-review.schema.json': {
        'status',
        'summary',
        'issues',
        'requires_escalation',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/session-delete-response.schema.json': {
        'status',
        'deleted',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/session-cancel-request.schema.json': {
        'message_id',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/session-cancel-response.schema.json': {
        'conversation_id',
        'message_id',
        'status',
        'cancelled',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/session-continue-request.schema.json': {
        'message_id',
        'user_input',
        'field_values',
        'confirm_tool_names',
        'session_context_patch',
        'user_profile_patch',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/stream-event-record.schema.json': {
        'event_id',
        'sequence',
        'event',
        'data',
        'created_at',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/stream-event-page.schema.json': {
        'conversation_id',
        'message_id',
        'items',
        'next_event_id',
        'has_more',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/session-state-snapshot.schema.json': {
        'agent_routes',
        'pending_user_actions',
        'review',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/orchestrator-response.schema.json': {
        'pending_user_actions',
        'review',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/internal-chat-response.schema.json': {
        'pending_user_actions',
        'review',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/tool-hub/tool-call-response.schema.json': {
        'status',
        'summary',
        'result',
        'citations',
        'audit_tags',
        'user_action_hint',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/tool-hub/tool-call-audit-record.schema.json': {
        'summary',
        'citations',
        'audit_tags',
        'user_action_hint',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/tool-hub/tool-execution-result.schema.json': {
        'user_action_hint',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/tool-hub/tool-invoke-response.schema.json': {
        'downstream_target',
        'auth_requirements',
        'user_action_hint',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/agent-descriptor.schema.json': {
        'version',
        'owner',
        'input_schema_version',
        'output_schema_version',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/agent-execution-result.schema.json': {
        'risk_flags',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/agent-route-record.schema.json': {
        'status',
        'handoff_received_from',
        'handoff_to',
        'handoff_reason',
        'action_required',
        'tool_names',
        'tool_call_ids',
        'tool_statuses',
        'depends_on_tool_call_ids',
        'session_context_inputs',
        'session_context_outputs',
        'context_highlights',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/agent-task.schema.json': {
        'depends_on_tool_call_ids',
        'session_context_inputs',
        'session_context_outputs',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/handoff-step.schema.json': {
        'depends_on_tool_call_ids',
        'session_context_inputs',
        'session_context_outputs',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/tool-plan-item.schema.json': {
        'required_payload_fields',
        'missing_payload_fields',
        'deferred_payload_fields',
        'missing_payload_hints',
        'depends_on_tool_call_ids',
        'session_context_input_keys',
        'session_context_output_keys',
        'readiness',
        'tool_mode',
        'timeout_ms',
        'idempotent',
        'cache_ttl_seconds',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/tool-hub/tool-definition.schema.json': {
        'version',
        'input_schema',
        'input_field_hints',
        'output_schema',
        'session_context_bindings',
        'session_context_output_keys',
        'prerequisite_tool_names',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/tool-hub/tool-preflight-result.schema.json': {
        'ready',
        'available',
        'tool_mode',
        'timeout_ms',
        'idempotent',
        'cache_ttl_seconds',
        'missing_payload_fields',
        'missing_payload_hints',
        'missing_auth_context',
        'confirmation_required',
        'session_context_bindings',
        'user_action_hint',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/tool-hub/tool-preflight-response.schema.json': {
        'user_action_hint',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/tool-hub/tool-user-action-hint.schema.json': {
        'action',
        'message',
        'missing_fields',
        'missing_payload_hints',
        'missing_auth_context',
        'required_permissions',
        'requires_account_context',
        'confirmation_required',
        'session_context_bindings',
        'user_profile_bindings',
        'confirm_tool_names',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/user-profile.schema.json': {
        'locale',
        'channel',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/user-profile-patch.schema.json': {
        'user_id',
        'roles',
        'permissions',
        'account_id',
        'tenant_id',
        'locale',
        'channel',
        'vip_level',
    },
    ROOT / 'packages/common-schemas/src/schemas/external/admin/admin-audit-record.schema.json': {
        'audit_id',
        'operator_type',
        'operator_id',
        'resource_type',
        'resource_id',
        'action',
        'reason',
        'created_at',
    },
    ROOT / 'packages/common-schemas/src/schemas/external/admin/admin-agent-record.schema.json': {
        'name',
        'code',
        'display_name',
        'domain',
        'description',
        'tool_whitelist',
        'enabled',
        'timeout_seconds',
    },
    ROOT / 'packages/common-schemas/src/schemas/external/admin/admin-agent-list-data.schema.json': {
        'items',
        'total',
    },
    ROOT / 'packages/common-schemas/src/schemas/external/admin/admin-agent-config-update-request.schema.json': {
        'enabled',
        'max_tool_calls',
        'fallback_agent',
        'timeout_seconds',
    },
    ROOT / 'packages/common-schemas/src/schemas/external/admin/admin-audit-list-data.schema.json': {
        'items',
        'page',
        'page_size',
        'total',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/knowledge/knowledge-runtime-snapshot.schema.json': {
        'exportedAt',
        'dataPath',
        'auditPath',
        'importRoot',
        'knowledgeBases',
        'adminJobs',
        'recentAuditRecords',
        'integrations',
    },
    ROOT / 'packages/common-schemas/src/schemas/external/user/marketing-copy-request.schema.json': {
        'campaign_id',
        'topic',
        'audience',
        'tone',
        'keywords',
    },
    ROOT / 'packages/common-schemas/src/schemas/external/user/marketing-copy-list-data.schema.json': {
        'items',
        'page',
        'page_size',
        'total',
        'total_pages',
        'sort_by',
        'sort_order',
    },
    ROOT / 'packages/common-schemas/src/schemas/external/user/marketing-copy-result.schema.json': {
        'copy_id',
        'campaign_id',
        'campaign_name',
        'topic',
        'audience',
        'tone',
        'headline',
        'summary',
        'body',
        'call_to_action',
        'keywords',
        'landing_page_url',
        'created_at',
    },
    ROOT / 'packages/common-schemas/src/schemas/external/user/promotion-link-request.schema.json': {
        'campaign_id',
        'channel',
        'source',
        'content_tag',
    },
    ROOT / 'packages/common-schemas/src/schemas/external/user/promotion-link-list-data.schema.json': {
        'items',
        'page',
        'page_size',
        'total',
        'total_pages',
        'sort_by',
        'sort_order',
    },
    ROOT / 'packages/common-schemas/src/schemas/external/user/promotion-link-result.schema.json': {
        'link_id',
        'campaign_id',
        'campaign_name',
        'channel',
        'short_url',
        'landing_page_url',
        'tracking_code',
        'created_at',
        'note',
    },
    ROOT / 'packages/common-schemas/src/schemas/external/user/poster-result-data.schema.json': {
        'result_ready',
        'campaign_id',
        'preview_url',
        'download_url',
        'mime_type',
        'generated_at',
    },
    ROOT / 'packages/common-schemas/src/schemas/external/user/research-task-status-data.schema.json': {
        'progress',
        'result_ready',
        'report_file_id',
    },
    ROOT / 'packages/common-schemas/src/schemas/external/user/research-task-result-data.schema.json': {
        'result_ready',
        'output_format',
        'download_url',
        'preview_text',
        'citations',
        'generated_at',
    },
    ROOT / 'packages/common-schemas/src/schemas/external/admin/knowledge-base-update-request.schema.json': {
        'name',
        'description',
        'retrieval_mode',
        'status',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/business-tools/business-tool-execute-response.schema.json': {
        'tool_name',
        'operation',
        'status',
        'summary',
        'result',
        'citations',
        'audit_tags',
        'user_action_hint',
    },
    ROOT / 'packages/common-schemas/src/schemas/external/admin/knowledge-document-detail-data.schema.json': {
        'document',
        'chunk_stats',
        'error_message',
    },
    ROOT / 'packages/common-schemas/src/schemas/external/admin/knowledge-chunk-stats.schema.json': {
        'chunk_count',
        'token_count',
        'average_tokens_per_chunk',
        'latest_job_id',
    },
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/tool-invocation.schema.json': {
        'user_action_hint',
    },
}
REQUIRED_NULLABLE_SCHEMA_PROPERTIES = {
    (ROOT / 'packages/common-schemas/src/schemas/api-envelope.schema.json', 'error'),
    (ROOT / 'packages/common-schemas/src/schemas/api-envelope.schema.json', 'meta'),
    (ROOT / 'packages/common-schemas/src/schemas/external/admin/knowledge-document.schema.json', 'error_message'),
    (ROOT / 'packages/common-schemas/src/schemas/external/auth/auth-user-profile.schema.json', 'avatar_url'),
    (ROOT / 'packages/common-schemas/src/schemas/external/user/research-task.schema.json', 'error_message'),
}
REQUIRED_SCHEMA_ROOT_ENUM_VALUES = {
    ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/agent-execution-risk-flag.schema.json': {
        'missing_tool_input',
        'missing_auth_context',
        'confirmation_required',
        'idempotency_conflict',
        'tool_failure',
        'human_handoff_requested',
    },
}
REQUIRED_SCHEMA_PROPERTY_ENUM_VALUES = {
    (ROOT / 'packages/common-schemas/src/schemas/runtime-dependency-readiness.schema.json', 'mode'): {
        'transport-local',
        'http',
    },
    (ROOT / 'packages/common-schemas/src/schemas/runtime-health-status.schema.json', 'status'): {
        'ok',
        'degraded',
    },
    (ROOT / 'packages/common-schemas/src/schemas/runtime-readiness-status.schema.json', 'status'): {
        'ready',
        'not_ready',
    },
    (ROOT / 'packages/common-schemas/src/schemas/internal/tool-hub/tool-call-audit-record.schema.json', 'status'): {
        'completed',
        'invalid-payload',
    },
    (ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/execution-event.schema.json', 'event'): {
        'review_result',
    },
    (ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/pending-user-action.schema.json', 'action'): {
        'clarify-tool-input',
        'collect-auth-context',
        'user-confirmation',
    },
    (ROOT / 'packages/common-schemas/src/schemas/internal/tool-hub/tool-preflight-result.schema.json', 'status'): {
        'missing-tool',
        'missing-payload',
        'auth-required',
        'confirmation-required',
        'invalid-operation',
        'ready',
    },
    (ROOT / 'packages/common-schemas/src/schemas/internal/tool-hub/tool-user-action-hint.schema.json', 'action'): {
        'clarify-tool-input',
        'collect-auth-context',
        'user-confirmation',
    },
    (ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/tool-plan-item.schema.json', 'readiness'): {
        'ready',
        'ready_after_dependencies',
        'needs_user_input',
    },
}
REQUIRED_SCHEMA_NESTED_PROPERTIES = {
    (ROOT / 'packages/common-schemas/src/schemas/internal/tool-hub/tool-call-error.schema.json', 'details'): {
        'missing_fields',
    },
    (ROOT / 'packages/common-schemas/src/schemas/internal/tool-hub/tool-execution-result.schema.json', 'error_detail'): {
        'missing_fields',
    },
    (ROOT / 'packages/common-schemas/src/schemas/internal/orchestrator/tool-invocation.schema.json', 'error_detail'): {
        'missing_fields',
    },
    (ROOT / 'packages/common-schemas/src/schemas/internal/business-tools/business-tool-execute-response.schema.json', 'error_detail'): {
        'missing_fields',
    },
}
REQUIRED_SCHEMA_PROPERTY_TYPE_MEMBERS = {
    (ROOT / 'packages/common-schemas/src/schemas/trace-context.schema.json', 'conversationId'): {
        'string',
        'null',
    },
    (ROOT / 'packages/common-schemas/src/schemas/trace-context.schema.json', 'userId'): {
        'string',
        'null',
    },
    (ROOT / 'packages/common-schemas/src/schemas/trace-context.schema.json', 'tenantId'): {
        'string',
        'null',
    },
    (ROOT / 'packages/common-schemas/src/schemas/trace-context.schema.json', 'callerService'): {
        'string',
        'null',
    },
    (ROOT / 'packages/common-schemas/src/schemas/trace-context.schema.json', 'toolCallId'): {
        'string',
        'null',
    },
    (ROOT / 'packages/common-schemas/src/schemas/trace-context.schema.json', 'idempotencyKey'): {
        'string',
        'null',
    },
    (ROOT / 'packages/common-schemas/src/schemas/trace-context.schema.json', 'operatorReason'): {
        'string',
        'null',
    },
}
CHANGE_REQUEST_RESULT_MARKERS = ('Foundation Processing Result', 'Foundation 处理结果')
IGNORED_CHANGE_REQUEST_FILES = {'CHANGE_REQUEST_TEMPLATE.md', 'README.md'}
CHANGE_REQUEST_PENDING_PATTERNS = (
    re.compile(r'(?im)^-\s*pending\s*$'),
    re.compile(r'(?im)^-\s*processed at:\s*pending\s*$'),
    re.compile(r'(?im)^-\s*decision:\s*pending\s*$'),
    re.compile(r'(?im)^-\s*implemented:\s*pending\s*$'),
)
CHANGE_REQUEST_REQUIRED_RESULT_FIELDS = ('processed at', 'decision')
DISALLOWED_GENERATED_SOURCE_ARTIFACTS = (
    ROOT / 'packages/common-schemas/src/index.js',
)
X_CALLER_SERVICE_HEADER_NAME = 'X-Caller-Service'


def assert_exists(path: Path) -> None:
    if not path.exists():
        raise ValueError(f'Missing required file: {path.relative_to(ROOT)}')


def validate_json_file(path: Path) -> Any:
    assert_exists(path)
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise ValueError(f'Invalid JSON in {path.relative_to(ROOT)}: {exc}') from exc


def validate_yaml_file(path: Path) -> Any:
    assert_exists(path)
    if yaml is None:
        raise ValueError(
            f'PyYAML is required to validate YAML files such as {path.relative_to(ROOT)}'
        )
    try:
        return yaml.safe_load(path.read_text(encoding='utf-8'))
    except yaml.YAMLError as exc:  # type: ignore[union-attr]
        raise ValueError(f'Invalid YAML in {path.relative_to(ROOT)}: {exc}') from exc


def extract_exported_string_map(text: str, export_name: str) -> dict[str, str]:
    pattern = rf'export const {re.escape(export_name)} = \{{(?P<body>[\s\S]*?)\n\}} as const;'
    match = re.search(pattern, text)
    if not match:
        raise ValueError(f'packages/common/src/index.ts is missing exported const `{export_name}`')
    entries = re.findall(r"^\s*([A-Za-z0-9_]+):\s*'([^']+)'", match.group('body'), flags=re.MULTILINE)
    if not entries:
        raise ValueError(
            f'packages/common/src/index.ts exported const `{export_name}` does not contain string entries'
        )
    return dict(entries)


def extract_exported_const_body(text: str, export_name: str, source_label: str) -> str:
    pattern = rf'export const {re.escape(export_name)} = \{{(?P<body>[\s\S]*?)\n\}} as const;'
    match = re.search(pattern, text)
    if not match:
        raise ValueError(f'{source_label} is missing exported const `{export_name}`')
    return match.group('body')


def openapi_component_key_for_header_name(header_name: str) -> str:
    return re.sub(r'[^A-Za-z0-9]', '', header_name)


def validate_error_catalog(path: Path) -> None:
    content = validate_yaml_file(path)
    if not isinstance(content, dict):
        raise ValueError(f'Error catalog must be a mapping: {path.relative_to(ROOT)}')
    if 'version' not in content or 'codes' not in content:
        raise ValueError(f'Error catalog missing required top-level keys in {path.relative_to(ROOT)}')
    codes = content.get('codes')
    if not isinstance(codes, list) or not codes:
        raise ValueError(f'Error catalog codes list is empty in {path.relative_to(ROOT)}')
    required_code_keys = {'code', 'numeric_code', 'http_status', 'retryable', 'owner', 'category', 'message'}
    seen_codes: set[str] = set()
    for index, item in enumerate(codes):
        if not isinstance(item, dict):
            raise ValueError(f'Error catalog entry #{index} is not a mapping in {path.relative_to(ROOT)}')
        missing = required_code_keys - item.keys()
        if missing:
            raise ValueError(
                f'Error catalog entry `{item.get("code", index)}` missing {sorted(missing)} in {path.relative_to(ROOT)}'
            )
        seen_codes.add(str(item['code']))
    missing_codes = sorted(REQUIRED_ERROR_CODES - seen_codes)
    if missing_codes:
        raise ValueError(f'Error catalog missing promoted codes {missing_codes} in {path.relative_to(ROOT)}')
    validate_foundation_error_code_exports(path, ROOT / 'packages/common-schemas/src/index.ts')


def extract_union_literals(text: str, export_name: str, source_label: str) -> list[str]:
    pattern = (
        rf'export type {re.escape(export_name)} =\n'
        rf'(?P<body>[\s\S]*?);\n\n'
    )
    match = re.search(pattern, text)
    if not match:
        raise ValueError(f'{source_label} is missing exported type `{export_name}`')
    values = re.findall(r"'([^']+)'", match.group('body'))
    if not values:
        raise ValueError(f'{source_label} exported type `{export_name}` does not contain string literals')
    return values


def extract_array_literals(text: str, export_name: str, source_label: str) -> list[str]:
    pattern = (
        rf'export const {re.escape(export_name)}: [A-Za-z0-9_<>\[\]\s|]+ = \['
        rf'(?P<body>[\s\S]*?)\n\];'
    )
    match = re.search(pattern, text)
    if not match:
        raise ValueError(f'{source_label} is missing exported const `{export_name}`')
    values = re.findall(r"'([^']+)'", match.group('body'))
    if not values:
        raise ValueError(f'{source_label} exported const `{export_name}` does not contain string literals')
    return values


def validate_foundation_error_code_exports(catalog_path: Path, index_path: Path) -> None:
    catalog = validate_yaml_file(catalog_path)
    if not isinstance(catalog, dict):
        raise ValueError(f'Error catalog must be a mapping: {catalog_path.relative_to(ROOT)}')
    codes = catalog.get('codes')
    if not isinstance(codes, list) or not codes:
        raise ValueError(f'Error catalog codes list is empty in {catalog_path.relative_to(ROOT)}')
    catalog_codes = [str(item['code']) for item in codes if isinstance(item, dict) and 'code' in item]
    index_text = index_path.read_text(encoding='utf-8')
    union_codes = extract_union_literals(
        index_text,
        'FoundationErrorCode',
        index_path.relative_to(ROOT).as_posix(),
    )
    array_codes = extract_array_literals(
        index_text,
        'foundationErrorCodes',
        index_path.relative_to(ROOT).as_posix(),
    )
    for exported_name, exported_codes in (
        ('FoundationErrorCode', union_codes),
        ('foundationErrorCodes', array_codes),
    ):
        missing = sorted(set(catalog_codes) - set(exported_codes))
        extras = sorted(set(exported_codes) - set(catalog_codes))
        if missing or extras:
            raise ValueError(
                f'{index_path.relative_to(ROOT)} `{exported_name}` is out of sync with '
                f'{catalog_path.relative_to(ROOT)} (missing={missing or []}, extra={extras or []})'
            )


def extract_type_members(property_payload: Any) -> set[str]:
    if not isinstance(property_payload, dict):
        return set()
    members: set[str] = set()
    type_value = property_payload.get('type')
    if isinstance(type_value, str):
        members.add(type_value)
    elif isinstance(type_value, list):
        members.update(str(item) for item in type_value if isinstance(item, str))
    for keyword in ('oneOf', 'anyOf'):
        variants = property_payload.get(keyword)
        if not isinstance(variants, list):
            continue
        for variant in variants:
            if isinstance(variant, dict):
                variant_type = variant.get('type')
                if isinstance(variant_type, str):
                    members.add(variant_type)
                elif isinstance(variant_type, list):
                    members.update(str(item) for item in variant_type if isinstance(item, str))
    return members


def iter_json_refs(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == '$ref' and isinstance(item, str):
                yield item
            else:
                yield from iter_json_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_json_refs(item)


def validate_schema_refs(path: Path, payload: Any) -> None:
    for ref in iter_json_refs(payload):
        if ref.startswith('#') or '://' in ref:
            continue
        file_ref = ref.split('#', 1)[0]
        target = (path.parent / file_ref).resolve()
        if not target.exists():
            raise ValueError(
                f'Broken $ref `{ref}` in {path.relative_to(ROOT)} -> {target.relative_to(ROOT)}'
            )


def validate_schema_properties(path: Path, payload: Any) -> None:
    required_properties = REQUIRED_SCHEMA_PROPERTIES.get(path)
    if required_properties:
        if not isinstance(payload, dict):
            raise ValueError(
                f'Schema must parse to an object for property validation: {path.relative_to(ROOT)}'
            )
        properties = payload.get('properties')
        if not isinstance(properties, dict):
            raise ValueError(f'Schema missing `properties` object in {path.relative_to(ROOT)}')
        missing = sorted(required_properties - properties.keys())
        if missing:
            raise ValueError(f'Schema missing promoted properties {missing} in {path.relative_to(ROOT)}')
    else:
        properties = payload.get('properties') if isinstance(payload, dict) else None

    required_root_enum_values = REQUIRED_SCHEMA_ROOT_ENUM_VALUES.get(path)
    if required_root_enum_values:
        if not isinstance(payload, dict):
            raise ValueError(f'Schema must parse to an object for enum validation: {path.relative_to(ROOT)}')
        enum_values = payload.get('enum')
        if not isinstance(enum_values, list):
            raise ValueError(f'Schema missing root enum list in {path.relative_to(ROOT)}')
        missing_root_values = sorted(required_root_enum_values - set(enum_values))
        if missing_root_values:
            raise ValueError(
                f'Schema root enum missing values {missing_root_values} in {path.relative_to(ROOT)}'
            )

    for (schema_path, property_name), required_values in REQUIRED_SCHEMA_PROPERTY_ENUM_VALUES.items():
        if schema_path != path:
            continue
        if not isinstance(properties, dict):
            raise ValueError(f'Schema missing `properties` object in {path.relative_to(ROOT)}')
        property_payload = properties.get(property_name)
        if not isinstance(property_payload, dict):
            raise ValueError(
                f'Schema missing promoted property `{property_name}` in {path.relative_to(ROOT)}'
            )
        enum_values = property_payload.get('enum')
        if not isinstance(enum_values, list):
            raise ValueError(
                f'Schema property `{property_name}` missing enum list in {path.relative_to(ROOT)}'
            )
        missing_values = sorted(required_values - set(enum_values))
        if missing_values:
            raise ValueError(
                f'Schema property `{property_name}` missing enum values {missing_values} in {path.relative_to(ROOT)}'
            )
    for (schema_path, property_name), nested_required in REQUIRED_SCHEMA_NESTED_PROPERTIES.items():
        if schema_path != path:
            continue
        if not isinstance(properties, dict):
            raise ValueError(f'Schema missing `properties` object in {path.relative_to(ROOT)}')
        property_payload = properties.get(property_name)
        if not isinstance(property_payload, dict):
            raise ValueError(
                f'Schema missing promoted property `{property_name}` in {path.relative_to(ROOT)}'
            )
        nested_properties = property_payload.get('properties')
        if not isinstance(nested_properties, dict):
            raise ValueError(
                f'Schema property `{property_name}` missing nested properties in {path.relative_to(ROOT)}'
            )
        missing_nested = sorted(nested_required - nested_properties.keys())
        if missing_nested:
            raise ValueError(
                f'Schema property `{property_name}` missing nested properties {missing_nested} in {path.relative_to(ROOT)}'
            )
    for (schema_path, property_name), required_type_members in REQUIRED_SCHEMA_PROPERTY_TYPE_MEMBERS.items():
        if schema_path != path:
            continue
        if not isinstance(properties, dict):
            raise ValueError(f'Schema missing `properties` object in {path.relative_to(ROOT)}')
        property_payload = properties.get(property_name)
        if not isinstance(property_payload, dict):
            raise ValueError(
                f'Schema missing promoted property `{property_name}` in {path.relative_to(ROOT)}'
            )
        actual_members = extract_type_members(property_payload)
        missing_type_members = sorted(required_type_members - actual_members)
        if missing_type_members:
            raise ValueError(
                f'Schema property `{property_name}` missing type members {missing_type_members} in {path.relative_to(ROOT)}'
            )


def collect_openapi_parameters(route_item: dict[str, Any], operation: dict[str, Any]) -> list[dict[str, Any]]:
    parameters: list[dict[str, Any]] = []
    for source in (route_item.get('parameters'), operation.get('parameters')):
        if not isinstance(source, list):
            continue
        parameters.extend(parameter for parameter in source if isinstance(parameter, dict))
    return parameters


def has_header_parameter(parameters: list[dict[str, Any]], header_name: str) -> bool:
    normalized_header_name = header_name.lower()
    for parameter in parameters:
        ref = parameter.get('$ref')
        if isinstance(ref, str) and ref.endswith('#/components/parameters/XCallerServiceHeader'):
            return True
        if (
            parameter.get('in') == 'header'
            and isinstance(parameter.get('name'), str)
            and parameter['name'].lower() == normalized_header_name
        ):
            return True
    return False


def resolve_openapi_parameter_name(
    parameter: dict[str, Any],
    local_parameters: dict[str, Any],
    shared_parameters: dict[str, Any],
) -> str | None:
    ref = parameter.get('$ref')
    if isinstance(ref, str):
        if ref.startswith('#/components/parameters/'):
            target = local_parameters.get(ref.rsplit('/', 1)[-1])
            if isinstance(target, dict):
                name = target.get('name')
                if isinstance(name, str):
                    return name
        if ref.startswith('./components.openapi.yaml#/components/parameters/'):
            target = shared_parameters.get(ref.rsplit('/', 1)[-1])
            if isinstance(target, dict):
                name = target.get('name')
                if isinstance(name, str):
                    return name
    name = parameter.get('name')
    if isinstance(name, str):
        return name
    return None


def validate_openapi_file(path: Path) -> None:
    content = validate_yaml_file(path)
    if not isinstance(content, dict):
        raise ValueError(f'OpenAPI file must parse to a mapping: {path.relative_to(ROOT)}')
    for key in OPENAPI_REQUIRED_KEYS:
        if key not in content:
            raise ValueError(f'OpenAPI baseline missing `{key}` in {path.relative_to(ROOT)}')
    top_level_owner = content.get('x-owner-service')
    if top_level_owner not in KNOWN_OPENAPI_OWNER_SERVICES:
        raise ValueError(
            f'OpenAPI baseline uses unknown top-level x-owner-service `{top_level_owner}` in {path.relative_to(ROOT)}'
        )
    required_paths = REQUIRED_OPENAPI_PATHS.get(path.name, ())
    declared_paths = content.get('paths')
    local_parameters = {}
    components = content.get('components')
    if isinstance(components, dict) and isinstance(components.get('parameters'), dict):
        local_parameters = components['parameters']
    shared_parameters: dict[str, Any] = {}
    if path.name != 'components.openapi.yaml':
        shared_components = validate_yaml_file(ROOT / 'openapi/components.openapi.yaml')
        shared_components_root = shared_components.get('components') if isinstance(shared_components, dict) else None
        if isinstance(shared_components_root, dict) and isinstance(shared_components_root.get('parameters'), dict):
            shared_parameters = shared_components_root['parameters']
    if required_paths and not isinstance(declared_paths, dict):
        raise ValueError(f'OpenAPI baseline missing `paths` mapping in {path.relative_to(ROOT)}')
    for required_path in required_paths:
        if required_path not in declared_paths:
            raise ValueError(f'OpenAPI baseline missing required path `{required_path}` in {path.relative_to(ROOT)}')
    for route, route_item in declared_paths.items():
        if not isinstance(route_item, dict):
            continue
        for method, operation in route_item.items():
            if method not in OPENAPI_HTTP_METHODS:
                continue
            if not isinstance(operation, dict):
                continue
            operation_owner = operation.get('x-owner-service')
            if operation_owner not in KNOWN_OPENAPI_OWNER_SERVICES:
                raise ValueError(
                    f'OpenAPI operation `{method.upper()} {route}` uses unknown x-owner-service `{operation_owner}` in {path.relative_to(ROOT)}'
                )
            if operation.get('x-permission-code') == 'service:internal.call':
                parameters = collect_openapi_parameters(route_item, operation)
                if not has_header_parameter(parameters, X_CALLER_SERVICE_HEADER_NAME):
                    raise ValueError(
                        'OpenAPI operation '
                        f'`{method.upper()} {route}` is missing `{X_CALLER_SERVICE_HEADER_NAME}` '
                        f'in {path.relative_to(ROOT)}'
                    )
    required_operations = REQUIRED_OPENAPI_OPERATIONS.get(path.name, {})
    for route, methods in required_operations.items():
        route_item = declared_paths.get(route)
        if not isinstance(route_item, dict):
            raise ValueError(f'OpenAPI baseline missing operation container `{route}` in {path.relative_to(ROOT)}')
        missing_methods = sorted(method for method in methods if method not in route_item)
        if missing_methods:
            raise ValueError(
                f'OpenAPI baseline missing methods {missing_methods} for `{route}` in {path.relative_to(ROOT)}'
            )
    for (file_name, route, method), param_names in REQUIRED_OPENAPI_QUERY_PARAMS.items():
        if file_name != path.name:
            continue
        route_item = declared_paths.get(route)
        if not isinstance(route_item, dict):
            raise ValueError(f'OpenAPI baseline missing operation container `{route}` in {path.relative_to(ROOT)}')
        operation = route_item.get(method)
        if not isinstance(operation, dict):
            raise ValueError(
                f'OpenAPI baseline missing `{method}` operation for `{route}` in {path.relative_to(ROOT)}'
            )
        parameters = collect_openapi_parameters(route_item, operation)
        declared_param_names = {
            resolve_openapi_parameter_name(parameter, local_parameters, shared_parameters)
            for parameter in parameters
            if isinstance(parameter, dict)
        }
        missing_params = sorted(param_names - declared_param_names)
        if missing_params:
            raise ValueError(
                f'OpenAPI baseline missing query parameters {missing_params} for `{method.upper()} {route}` in {path.relative_to(ROOT)}'
            )
    for (file_name, route, method, parameter_name), required_values in REQUIRED_OPENAPI_PARAMETER_ENUM_VALUES.items():
        if file_name != path.name:
            continue
        route_item = declared_paths.get(route)
        if not isinstance(route_item, dict):
            raise ValueError(f'OpenAPI baseline missing operation container `{route}` in {path.relative_to(ROOT)}')
        operation = route_item.get(method)
        if not isinstance(operation, dict):
            raise ValueError(
                f'OpenAPI baseline missing `{method}` operation for `{route}` in {path.relative_to(ROOT)}'
            )
        parameters = collect_openapi_parameters(route_item, operation)
        parameter_payload = next(
            (
                parameter
                for parameter in parameters
                if isinstance(parameter, dict) and parameter.get('name') == parameter_name
            ),
            None,
        )
        if not isinstance(parameter_payload, dict):
            raise ValueError(
                f'OpenAPI baseline missing parameter `{parameter_name}` for `{method.upper()} {route}` in {path.relative_to(ROOT)}'
            )
        schema_payload = parameter_payload.get('schema')
        if not isinstance(schema_payload, dict):
            raise ValueError(
                f'OpenAPI parameter `{parameter_name}` missing schema in `{method.upper()} {route}` in {path.relative_to(ROOT)}'
            )
        enum_values = schema_payload.get('enum')
        if not isinstance(enum_values, list):
            raise ValueError(
                f'OpenAPI parameter `{parameter_name}` missing enum list in `{method.upper()} {route}` in {path.relative_to(ROOT)}'
            )
        missing_values = sorted(required_values - set(enum_values))
        if missing_values:
            raise ValueError(
                f'OpenAPI parameter `{parameter_name}` missing enum values {missing_values} in `{method.upper()} {route}` in {path.relative_to(ROOT)}'
            )
    validate_schema_refs(path, content)


def validate_shared_runtime_and_headers(
    common_index_path: Path,
    env_example_path: Path,
    runtime_doc_path: Path,
    openapi_components_path: Path,
) -> None:
    common_text = common_index_path.read_text(encoding='utf-8')
    env_example_text = env_example_path.read_text(encoding='utf-8')
    runtime_doc_text = runtime_doc_path.read_text(encoding='utf-8')
    components = validate_yaml_file(openapi_components_path)

    runtime_env_keys = extract_exported_string_map(common_text, 'sharedRuntimeEnvKeys')
    request_headers = extract_exported_string_map(common_text, 'sharedRequestHeaderNames')
    response_headers = extract_exported_string_map(common_text, 'sharedResponseHeaderNames')

    missing_env_example_keys = sorted(
        key
        for key in runtime_env_keys.values()
        if not re.search(rf'(?m)^{re.escape(key)}=', env_example_text)
    )
    if missing_env_example_keys:
        raise ValueError(
            f'.env.example is missing shared runtime keys {missing_env_example_keys}'
        )

    missing_runtime_doc_keys = sorted(
        key for key in runtime_env_keys.values() if key not in runtime_doc_text
    )
    if missing_runtime_doc_keys:
        raise ValueError(
            'docs/contracts/shared/runtime-config.md is missing shared runtime keys '
            f'{missing_runtime_doc_keys}'
        )

    component_section = components.get('components')
    if not isinstance(component_section, dict):
        raise ValueError('openapi/components.openapi.yaml is missing the `components` mapping')

    parameter_components = component_section.get('parameters')
    if not isinstance(parameter_components, dict):
        raise ValueError('openapi/components.openapi.yaml is missing shared parameter components')
    declared_request_header_names = {
        parameter.get('name')
        for parameter in parameter_components.values()
        if isinstance(parameter, dict) and parameter.get('in') == 'header'
    }
    missing_request_headers = sorted(
        header_name
        for header_name in request_headers.values()
        if header_name not in declared_request_header_names
    )
    if missing_request_headers:
        raise ValueError(
            'openapi/components.openapi.yaml is missing shared header parameters '
            f'{missing_request_headers}'
        )

    response_header_components = component_section.get('headers')
    if not isinstance(response_header_components, dict):
        raise ValueError('openapi/components.openapi.yaml is missing shared response-header components')
    missing_response_headers = sorted(
        header_name
        for header_name in response_headers.values()
        if openapi_component_key_for_header_name(header_name) not in response_header_components
    )
    if missing_response_headers:
        raise ValueError(
            'openapi/components.openapi.yaml is missing shared response headers '
            f'{missing_response_headers}'
        )


def validate_state_file(path: Path) -> None:
    content = validate_json_file(path)
    missing = [key for key in REQUIRED_STATE_KEYS if key not in content]
    if missing:
        raise ValueError(f'state.json missing required keys {missing}')


def validate_common_index(path: Path) -> None:
    text = path.read_text(encoding='utf-8')
    missing = sorted(required for required in REQUIRED_COMMON_STRINGS if required not in text)
    if missing:
        raise ValueError(
            f'packages/common/src/index.ts is missing required platform-registry markers {missing}'
        )
    for service_name, owner in COMMON_OWNER_ASSIGNMENT_CHECKS.items():
        pattern = (
            rf"name: '{re.escape(service_name)}'[\s\S]*?"
            rf"ownerSupervisor: '{re.escape(owner)}'[\s\S]*?"
            r"lifecycle: 'contract-placeholder'"
        )
        if not re.search(pattern, text):
            raise ValueError(
                'packages/common/src/index.ts is missing the expected owner/lifecycle '
                f'baseline for `{service_name}`'
            )


def validate_schema_registry(path: Path, schema_root: Path) -> None:
    text = path.read_text(encoding='utf-8')
    registry_body = extract_exported_const_body(
        text,
        'schemaRegistry',
        'packages/common-schemas/src/index.ts',
    )
    declared_paths = set(re.findall(r"'([^']+\.schema\.json)'", registry_body))
    actual_paths = {
        str(schema_path.relative_to(schema_root))
        for schema_path in sorted(schema_root.rglob('*.schema.json'))
    }

    missing_paths = sorted(actual_paths - declared_paths)
    if missing_paths:
        raise ValueError(
            'packages/common-schemas/src/index.ts schemaRegistry is missing schema paths '
            f'{missing_paths}'
        )

    extra_paths = sorted(declared_paths - actual_paths)
    if extra_paths:
        raise ValueError(
            'packages/common-schemas/src/index.ts schemaRegistry references missing schema files '
            f'{extra_paths}'
        )


def validate_root_readme(path: Path) -> None:
    text = path.read_text(encoding='utf-8')
    missing = sorted(required for required in README_REQUIRED_STRINGS if required not in text)
    if missing:
        raise ValueError(f'README.md is missing required workspace-baseline markers {missing}')


def validate_required_strings(path: Path, required_strings: set[str], label: str) -> None:
    text = path.read_text(encoding='utf-8')
    missing = sorted(required for required in required_strings if required not in text)
    if missing:
        raise ValueError(f'{label} is missing required baseline markers {missing}')


def validate_change_requests(root: Path) -> None:
    assert_exists(root)
    for path in sorted(root.glob('*.md')):
        if path.name in IGNORED_CHANGE_REQUEST_FILES:
            continue
        text = path.read_text(encoding='utf-8')
        marker_positions = [text.find(marker) for marker in CHANGE_REQUEST_RESULT_MARKERS if marker in text]
        if not marker_positions:
            raise ValueError(
                f'Change request is missing a foundation processing result marker: {path.relative_to(ROOT)}'
            )
        result_section = text[min(marker_positions):]
        for pattern in CHANGE_REQUEST_PENDING_PATTERNS:
            if pattern.search(result_section):
                raise ValueError(
                    f'Change request still contains a pending foundation result: {path.relative_to(ROOT)}'
                )
        for field in CHANGE_REQUEST_REQUIRED_RESULT_FIELDS:
            blank_pattern = re.compile(rf'(?im)^-\s*{re.escape(field)}:\s*$')
            value_pattern = re.compile(rf'(?im)^-\s*{re.escape(field)}:\s*(?P<value>\S.*)$')
            if blank_pattern.search(result_section):
                raise ValueError(
                    f'Change request has a blank foundation `{field}` result: {path.relative_to(ROOT)}'
                )
            if not value_pattern.search(result_section):
                raise ValueError(
                    f'Change request is missing foundation `{field}` result text: {path.relative_to(ROOT)}'
                )


def validate_disallowed_generated_source_artifacts(paths: tuple[Path, ...]) -> None:
    for path in paths:
        if path.exists():
            raise ValueError(
                f'Stale generated source artifact must be removed from frozen baseline: '
                f'{path.relative_to(ROOT)}'
            )


def main() -> int:
    parser = argparse.ArgumentParser(description='Validate the supervisor-foundation baseline.')
    parser.add_argument('--quiet', action='store_true', help='Only print failures.')
    args = parser.parse_args()

    try:
        for path in REQUIRED_FILES:
            assert_exists(path)

        validate_disallowed_generated_source_artifacts(DISALLOWED_GENERATED_SOURCE_ARTIFACTS)

        schema_files = sorted(SCHEMA_ROOT.rglob('*.schema.json'))
        if not schema_files:
            raise ValueError('No schema files found under packages/common-schemas/src/schemas')
        for path in schema_files:
            payload = validate_json_file(path)
            validate_schema_refs(path, payload)
            validate_schema_properties(path, payload)

        openapi_files = sorted(OPENAPI_ROOT.glob('*.yaml'))
        if not openapi_files:
            raise ValueError('No OpenAPI files found under openapi/')
        for path in openapi_files:
            validate_openapi_file(path)

        validate_common_index(ROOT / 'packages/common/src/index.ts')
        validate_schema_registry(
            ROOT / 'packages/common-schemas/src/index.ts',
            ROOT / 'packages/common-schemas/src/schemas',
        )
        validate_shared_runtime_and_headers(
            ROOT / 'packages/common/src/index.ts',
            ROOT / '.env.example',
            ROOT / 'docs/contracts/shared/runtime-config.md',
            ROOT / 'openapi/components.openapi.yaml',
        )
        validate_required_strings(
            ROOT / 'packages/common/README.md',
            COMMON_README_REQUIRED_STRINGS,
            'packages/common/README.md',
        )
        validate_required_strings(
            ROOT / 'docs/contracts/shared/api-conventions.md',
            API_CONVENTIONS_REQUIRED_STRINGS,
            'docs/contracts/shared/api-conventions.md',
        )
        validate_required_strings(
            ROOT / 'docs/contracts/foundation-baseline.md',
            FOUNDATION_BASELINE_REQUIRED_STRINGS,
            'docs/contracts/foundation-baseline.md',
        )
        validate_required_strings(
            ROOT / 'openapi/orchestrator-service.openapi.yaml',
            ORCHESTRATOR_OPENAPI_REQUIRED_STRINGS,
            'openapi/orchestrator-service.openapi.yaml',
        )
        validate_required_strings(
            ROOT / 'openapi/tool-hub-service.openapi.yaml',
            TOOL_HUB_OPENAPI_REQUIRED_STRINGS,
            'openapi/tool-hub-service.openapi.yaml',
        )
        validate_required_strings(
            ROOT / 'openapi/business-tools-service.openapi.yaml',
            BUSINESS_TOOLS_OPENAPI_REQUIRED_STRINGS,
            'openapi/business-tools-service.openapi.yaml',
        )
        validate_root_readme(ROOT / 'README.md')
        validate_state_file(ROOT / 'logs/supervisor-foundation/state.json')
        validate_error_catalog(ROOT / 'packages/common-schemas/errors/error_codes.yaml')
        validate_change_requests(ROOT / 'docs/contracts/change-requests')
    except ValueError as exc:
        print(f'foundation-validate: FAIL - {exc}', file=sys.stderr)
        return 1

    if not args.quiet:
        print('foundation-validate: OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
