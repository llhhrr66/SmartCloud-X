from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from scripts.qa.infra_persistence_matrix import build_report as build_infra_persistence_report


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class PathExpectation:
    category: str
    rel_path: str
    note: str


@dataclass(frozen=True)
class CheckFailure:
    path: str
    reason: str


@dataclass(frozen=True)
class SafeResult:
    value: Any = None
    failures: tuple[CheckFailure, ...] = ()


KEY_SERVICE_EXPECTATIONS: tuple[PathExpectation, ...] = (
    PathExpectation("auth", "apps/auth-user-service/app", "auth service package root"),
    PathExpectation("auth", "apps/auth-user-service/app/main.py", "auth FastAPI entrypoint"),
    PathExpectation("auth", "apps/auth-user-service/app/routes.py", "auth route handlers"),
    PathExpectation("auth", "openapi/auth-user-service.openapi.yaml", "auth published OpenAPI"),
    PathExpectation("marketing", "apps/marketing-service/app/main.py", "marketing FastAPI entrypoint"),
    PathExpectation("marketing", "apps/marketing-service/app/routes.py", "marketing route handlers"),
    PathExpectation("marketing", "openapi/marketing-service.openapi.yaml", "marketing published OpenAPI"),
    PathExpectation("research", "apps/research-service/app/main.py", "research FastAPI entrypoint"),
    PathExpectation("research", "apps/research-service/app/routes.py", "research route handlers"),
    PathExpectation("research", "openapi/research-service.openapi.yaml", "research published OpenAPI"),
    PathExpectation(
        "orchestrator",
        "apps/orchestrator-service/app/api/routes/health.py",
        "orchestrator health/runtime route",
    ),
    PathExpectation(
        "orchestrator",
        "apps/orchestrator-service/app/api/routes/orchestration.py",
        "orchestrator API routes",
    ),
    PathExpectation(
        "orchestrator",
        "apps/orchestrator-service/app/services/runtime_mysql.py",
        "orchestrator MySQL runtime helper",
    ),
    PathExpectation(
        "orchestrator",
        "apps/orchestrator-service/app/services/runtime_redis.py",
        "orchestrator Redis runtime helper",
    ),
    PathExpectation(
        "orchestrator",
        "apps/orchestrator-service/app/services/router.py",
        "orchestrator routing service",
    ),
    PathExpectation(
        "orchestrator",
        "apps/orchestrator-service/app/services/state_store.py",
        "orchestrator session state store",
    ),
    PathExpectation(
        "orchestrator",
        "openapi/orchestrator-service.openapi.yaml",
        "orchestrator published OpenAPI",
    ),
    PathExpectation("tool-hub", "apps/tool-hub-service/app/main.py", "tool-hub FastAPI entrypoint"),
    PathExpectation(
        "tool-hub",
        "apps/tool-hub-service/app/api/routes/health.py",
        "tool-hub health/runtime route",
    ),
    PathExpectation(
        "tool-hub",
        "apps/tool-hub-service/app/api/routes/tools.py",
        "tool-hub tool invocation routes",
    ),
    PathExpectation(
        "tool-hub",
        "apps/tool-hub-service/app/services/runtime_mysql.py",
        "tool-hub MySQL runtime helper",
    ),
    PathExpectation(
        "tool-hub",
        "apps/tool-hub-service/app/services/audit_store.py",
        "tool-hub audit persistence",
    ),
    PathExpectation("tool-hub", "openapi/tool-hub-service.openapi.yaml", "tool-hub published OpenAPI"),
    PathExpectation(
        "business-tools",
        "apps/business-tools/src/business_tools/runtime_backend.py",
        "business-tools Redis runtime helper",
    ),
    PathExpectation(
        "business-tools",
        "apps/business-tools/src/business_tools/catalog.py",
        "business-tools catalog implementation",
    ),
    PathExpectation(
        "business-tools",
        "apps/business-tools/src/business_tools_service/api/routes/health.py",
        "business-tools health/runtime route",
    ),
    PathExpectation(
        "business-tools",
        "apps/business-tools/src/business_tools_service/main.py",
        "business-tools service entrypoint",
    ),
    PathExpectation(
        "business-tools",
        "apps/business-tools/docs/tool-catalog.md",
        "business-tools catalog documentation",
    ),
    PathExpectation(
        "business-tools",
        "openapi/business-tools-service.openapi.yaml",
        "business-tools published OpenAPI",
    ),
    PathExpectation(
        "knowledge",
        "apps/knowledge-service/app/api/routes/health.py",
        "knowledge health/runtime route",
    ),
    PathExpectation(
        "knowledge",
        "apps/knowledge-service/app/api/routes/knowledge.py",
        "knowledge public routes",
    ),
    PathExpectation(
        "knowledge",
        "apps/knowledge-service/app/api/routes/admin.py",
        "knowledge admin routes",
    ),
    PathExpectation(
        "knowledge",
        "apps/knowledge-service/app/services/metadata_backend.py",
        "knowledge MySQL metadata backend helper",
    ),
    PathExpectation(
        "knowledge",
        "apps/knowledge-service/data/starter-catalog.json",
        "knowledge starter catalog",
    ),
    PathExpectation(
        "knowledge",
        "openapi/knowledge-service.openapi.yaml",
        "knowledge published OpenAPI",
    ),
    PathExpectation("rag", "apps/rag-service/app/api/routes/health.py", "rag health/runtime route"),
    PathExpectation("rag", "apps/rag-service/app/api/routes/rag.py", "rag public routes"),
    PathExpectation(
        "rag",
        "apps/rag-service/app/services/retrieval.py",
        "rag retrieval implementation",
    ),
    PathExpectation(
        "rag",
        "apps/rag-service/app/services/knowledge_client.py",
        "rag knowledge-service adapter",
    ),
    PathExpectation("rag", "openapi/rag-service.openapi.yaml", "rag published OpenAPI"),
    PathExpectation("web-user", "apps/web-user/package.json", "web-user package manifest"),
    PathExpectation("web-user", "apps/web-user/src/pages/ChatPage.tsx", "web-user chat page"),
    PathExpectation("web-user", "apps/web-user/src/api/services/auth.ts", "web-user auth adapter"),
    PathExpectation(
        "web-user",
        "apps/web-user/public/runtime-config.js",
        "web-user runtime config asset",
    ),
    PathExpectation(
        "web-user",
        "apps/web-user/docker-entrypoint.d/40-runtime-config.sh",
        "web-user runtime config entrypoint script",
    ),
    PathExpectation(
        "web-user",
        "apps/web-user/tests/e2e/mock-api-server.mjs",
        "web-user browser mock API server",
    ),
    PathExpectation(
        "web-user",
        "apps/web-user/tests/e2e/specs/error-recovery.spec.ts",
        "web-user browser error-path coverage",
    ),
    PathExpectation(
        "web-user",
        "apps/web-user/tests/e2e/specs/chat-citation.spec.ts",
        "web-user browser SSE and citation coverage",
    ),
    PathExpectation("web-admin", "apps/web-admin/package.json", "web-admin package manifest"),
    PathExpectation("web-admin", "apps/web-admin/src/App.tsx", "web-admin React app entry"),
    PathExpectation(
        "web-admin",
        "apps/web-admin/src/shared-sdk.ts",
        "web-admin shared frontend-sdk bridge",
    ),
    PathExpectation("web-admin", "openapi/admin-api.openapi.yaml", "admin published OpenAPI"),
    PathExpectation(
        "frontend-sdk",
        "packages/frontend-sdk/package.json",
        "frontend-sdk package manifest",
    ),
    PathExpectation(
        "frontend-sdk",
        "packages/frontend-sdk/src/core/http.ts",
        "frontend-sdk core HTTP helper",
    ),
    PathExpectation(
        "frontend-sdk",
        "packages/frontend-sdk/src/web-user/api.ts",
        "frontend-sdk web-user API surface",
    ),
    PathExpectation(
        "frontend-sdk",
        "packages/frontend-sdk/src/web-admin/api.ts",
        "frontend-sdk web-admin API surface",
    ),
)

FOUNDATION_CONTRACT_EXPECTATIONS: tuple[PathExpectation, ...] = (
    PathExpectation("contracts", "docs/contracts/foundation-baseline.md", "foundation baseline contract"),
    PathExpectation("contracts", "docs/contracts/shared/api-conventions.md", "shared API conventions"),
    PathExpectation("contracts", "docs/contracts/shared/auth-contract.md", "shared auth contract"),
    PathExpectation(
        "contracts",
        "docs/contracts/shared/runtime-config.md",
        "shared runtime-config contract",
    ),
    PathExpectation("contracts", "docs/contracts/shared/schema-catalog.md", "shared schema catalog"),
    PathExpectation(
        "contracts",
        "docs/contracts/supervisor-ownership.md",
        "supervisor ownership contract",
    ),
)

STATUS_DOC_EXPECTATIONS: tuple[PathExpectation, ...] = (
    PathExpectation("status", "docs/status/supervisor-foundation-status.md", "foundation status doc"),
    PathExpectation(
        "status",
        "docs/status/supervisor-auth-marketing-research-status.md",
        "auth/marketing/research status doc",
    ),
    PathExpectation(
        "status",
        "docs/status/supervisor-orchestrator-status.md",
        "orchestrator status doc",
    ),
    PathExpectation(
        "status",
        "docs/status/supervisor-knowledge-rag-status.md",
        "knowledge/rag status doc",
    ),
    PathExpectation("status", "docs/status/supervisor-web-user-status.md", "web-user status doc"),
    PathExpectation(
        "status",
        "docs/status/supervisor-frontend-sdk-status.md",
        "frontend-sdk status doc",
    ),
    PathExpectation(
        "status",
        "docs/status/supervisor-integration-qa-status.md",
        "integration QA status doc",
    ),
)

QA_BASELINE_EXPECTATIONS: tuple[PathExpectation, ...] = (
    PathExpectation("qa", "tests/integration/test_service_smoke.py", "integration smoke baseline"),
    PathExpectation(
        "qa",
        "tests/integration/test_contract_presence.py",
        "integration contract/presence baseline",
    ),
    PathExpectation(
        "qa",
        "tests/integration/test_error_path_smoke.py",
        "integration error-path smoke baseline",
    ),
    PathExpectation(
        "qa",
        "tests/integration/test_orchestrator_smoke.py",
        "integration orchestrator behavior smoke baseline",
    ),
    PathExpectation("qa", "tests/e2e", "repo browser E2E staging directory"),
    PathExpectation("qa", "tests/e2e/package.json", "repo-level browser smoke module boundary"),
    PathExpectation(
        "qa",
        "tests/e2e/playwright.root.config.ts",
        "repo-level Playwright smoke config",
    ),
    PathExpectation(
        "qa",
        "tests/e2e/test_browser_entry.spec.ts",
        "repo-level browser smoke entry",
    ),
    PathExpectation(
        "qa",
        "tests/e2e/app-smoke.spec.ts",
        "repo-level browser happy-path smoke entry",
    ),
    PathExpectation(
        "qa",
        "tests/e2e/playwright_smoke.spec.ts",
        "repo-level browser reload-persistence smoke entry",
    ),
    PathExpectation(
        "qa",
        "tests/e2e/test_ui_smoke.py",
        "no-browser root browser wiring smoke",
    ),
    PathExpectation("qa", "tests/e2e/README.md", "repo-level browser smoke runbook"),
    PathExpectation("qa", "scripts/qa/qa_env.sh", "shared QA runner bootstrap"),
    PathExpectation("qa", "scripts/qa/run_smoke.sh", "focused baseline runner"),
    PathExpectation(
        "qa",
        "scripts/qa/run_full_stack_validation.sh",
        "full stack QA validation runner",
    ),
    PathExpectation(
        "qa",
        "scripts/qa/check_release_readiness.py",
        "release-readiness checker",
    ),
    PathExpectation(
        "qa",
        "scripts/qa/infra_persistence_matrix.py",
        "infra-backed persistence readiness matrix",
    ),
    PathExpectation(
        "qa",
        "scripts/qa/baseline_expectations.py",
        "shared QA expectations matrix",
    ),
    PathExpectation("qa", "docs/runbooks/local-validation.md", "local validation runbook"),
    PathExpectation(
        "qa",
        "docs/reviews/integration-qa-baseline.md",
        "integration QA review doc",
    ),
    PathExpectation(
        "qa",
        "docs/reviews/known-issues.md",
        "integration QA known issues register",
    ),
    PathExpectation("qa", "logs/supervisor-integration-qa/progress.log", "progress log"),
    PathExpectation("qa", "logs/supervisor-integration-qa/blockers.log", "blockers log"),
    PathExpectation("qa", "logs/supervisor-integration-qa/decisions.log", "decisions log"),
    PathExpectation("qa", "logs/supervisor-integration-qa/state.json", "QA state snapshot"),
)

ALL_PATH_EXPECTATIONS: tuple[PathExpectation, ...] = (
    *KEY_SERVICE_EXPECTATIONS,
    *FOUNDATION_CONTRACT_EXPECTATIONS,
    *STATUS_DOC_EXPECTATIONS,
    *QA_BASELINE_EXPECTATIONS,
)

WEB_USER_REQUIRED_SCRIPTS = ("dev", "build", "typecheck", "test:e2e", "docker:build")
WEB_ADMIN_REQUIRED_SCRIPTS = ("dev", "build", "preview")
FRONTEND_SDK_REQUIRED_EXPORTS = (".", "./core", "./web-user", "./web-admin")
REPO_E2E_REQUIRED_SCRIPTS = ("test:browser", "test:browser:headed", "install:browsers")
BROWSER_ROOT_REQUIRED_MARKERS = (
    "billing_summary_requires_refresh_once",
    "billing happy path without injected failures",
    "limited_marketing",
    "stream_disconnect_once",
    "citation_detail_forbidden",
    "marketing_copy_rate_limited",
    "research_report_file_missing",
)
BROWSER_APP_SMOKE_REQUIRED_MARKERS = (
    "用户工作台总览",
    "会话历史",
    "GPU 挂载排障",
    "Product_Tech_Agent",
    "消息数：2",
)
BROWSER_PLAYWRIGHT_SMOKE_REQUIRED_MARKERS = (
    "research_task_completes_with_report",
    "工业级上云活动",
    "Repo 根浏览器持久化回放",
    "smartcloud-x:web-user:task-registry",
    "查看报告文件",
    "billing_summary_requires_refresh_once",
    "账单结果页",
)
BROWSER_UI_SMOKE_REQUIRED_MARKERS = (
    "test_browser_entry.spec.ts",
    "app-smoke.spec.ts",
    "playwright_smoke.spec.ts",
    "playwright.root.config.ts",
    "npm --prefix tests/e2e run test:browser",
    "mock-api-server.mjs",
)
ORCHESTRATOR_SMOKE_REQUIRED_MARKERS = (
    "collect-auth-context",
    "Last-Event-ID",
    "messages/asst_msg-replay-1/events",
    "marketing.generate_copy",
)
ERROR_PATH_SMOKE_REQUIRED_MARKERS = (
    "4010002",
    "4030001",
    "4090001",
    "4291001",
    "marketing copy generation rate limit exceeded",
    "test_rag_retrieve_diagnose_and_answer_handle_empty_and_degraded_fallbacks",
    "/api/rag/v1/retrieve",
    "/api/rag/v1/diagnose",
    "ReadTimeout",
    "knowledge-service unavailable: ReadTimeout",
)
FULL_STACK_RUNNER_REQUIRED_MARKERS = (
    "qa_env.sh",
    "scripts/qa/run_smoke.sh",
    "scripts/qa/project_smoke.py",
    "smartcloud_qa_configure_live_infra_env",
    "SMARTCLOUD_QA_RUN_SERVICE_PROCESS_BASELINE=0",
    "SMARTCLOUD_QA_RUN_BROWSER",
    "npm --prefix tests/e2e run test:browser",
    "deploy/docker-compose/trace-smoke.py",
    "deploy/docker-compose/smoke-test.py",
    "scripts/qa/release_readiness.py --strict",
)
LOCAL_VALIDATION_REQUIRED_MARKERS = (
    "qa_env.sh",
    "smartcloud_qa_assert_python_runtime",
    "smartcloud_qa_configure_live_infra_env",
    "scripts/qa/verify_openapi_contracts.py",
    "scripts/qa/run_full_stack_validation.sh",
    "pytest tests -q",
)
QA_ENV_REQUIRED_MARKERS = (
    "SMARTCLOUD_QA_UV_WITH",
    "QA_PYTHON",
    "QA_PYTEST",
    "QA_RUNTIME_LABEL",
    "smartcloud_qa_assert_python_runtime",
    "smartcloud_qa_configure_live_infra_env",
    "smartcloud_qa_require_playwright",
    "smartcloud_qa_configure_browser_ports",
    "smartcloud_qa_find_free_port",
    "SMARTCLOUD_QA_USE_LIVE_INFRA",
    "SMARTCLOUD_QA_SHARED_MYSQL_DSN",
    "SMARTCLOUD_QA_SHARED_REDIS_URL",
)
LIVE_INFRA_COMPOSE_REQUIRED_MARKERS = (
    "mysql:",
    "redis:",
    "qdrant:",
    "opensearch:",
    "minio:",
    "SMARTCLOUD_MINIO_ENDPOINT: ${SMARTCLOUD_MINIO_ENDPOINT:-http://minio:9000}",
    "SMARTCLOUD_MYSQL_DSN: ${SMARTCLOUD_MYSQL_DSN:-mysql+pymysql://smartcloud:smartcloud@mysql:3306/smartcloud}",
    "SMARTCLOUD_QDRANT_URL: ${SMARTCLOUD_QDRANT_URL:-http://qdrant:6333}",
    "SMARTCLOUD_OPENSEARCH_URL: ${SMARTCLOUD_OPENSEARCH_URL:-http://opensearch:9200}",
    "SMARTCLOUD_REDIS_URL: ${SMARTCLOUD_REDIS_URL:-redis://redis:6379/0}",
    '"${SMARTCLOUD_MINIO_HOST_PORT:-19000}:9000"',
    '"${SMARTCLOUD_MINIO_CONSOLE_HOST_PORT:-19001}:9001"',
)
LIVE_INFRA_RUNBOOK_REQUIRED_MARKERS = (
    "SMARTCLOUD_QA_SHARED_MYSQL_DSN",
    "SMARTCLOUD_QA_SHARED_REDIS_URL",
    "SMARTCLOUD_QA_SHARED_RAG_REDIS_URL",
    "SMARTCLOUD_QA_SHARED_MINIO_ENDPOINT",
    "SMARTCLOUD_QA_SHARED_MINIO_BUCKET",
    "SMARTCLOUD_QA_SHARED_QDRANT_URL",
    "SMARTCLOUD_QA_SHARED_OPENSEARCH_URL",
    "19000/19001",
    "http://127.0.0.1:19000",
    "SMARTCLOUD_MINIO_HOST_PORT",
)
RUN_SMOKE_REQUIRED_MARKERS = (
    "smartcloud_qa_assert_python_runtime",
    "smartcloud_qa_configure_live_infra_env",
    "smartcloud_qa_configure_browser_ports",
    "bash -n",
    "scripts/qa/qa_env.sh",
    "scripts/qa/infra_persistence_matrix.py",
    "scripts/qa/run_full_stack_validation.sh",
    "scripts/qa/run_local_validation.sh",
    "tests/integration/test_contract_presence.py",
    "tests/integration/test_service_smoke.py",
    "scripts/qa/check_release_readiness.py",
    "scripts/qa/project_smoke.py",
    "auth-marketing-research",
    "orchestrator-billing",
    "SMARTCLOUD_QA_RUN_SERVICE_PROCESS_BASELINE",
    "SMARTCLOUD_QA_RUN_STACK",
    "SMARTCLOUD_QA_RUN_BROWSER",
    "QA_BROWSER_APP_PORT",
    "QA_BROWSER_API_PORT",
)
PROJECT_SMOKE_REQUIRED_MARKERS = (
    "SMARTCLOUD_QA_USE_LIVE_INFRA",
    "resolve_backend_mode",
    "backendEvidence",
    "marketingPosterObjectStored",
    "shared-connectors",
    "mysql-and-redis",
    "toolHubAuditStored",
    "conversationStored",
    "timeoutChain",
    "toolHubAuditStatus",
    "timeoutAuditStored",
)
KNOWN_ISSUES_REQUIRED_MARKERS = (
    "QA-001",
    "QA-002",
    "QA-007",
    "QA-008",
    "SMARTCLOUD_QA_USE_LIVE_INFRA",
    "tool-hub",
    "tests/e2e",
)
STATUS_DOC_REQUIRED_MARKERS = (
    "focused baseline",
    "default targeted service-process baseline",
    "root browser smoke",
    "knowledge-rag-admin",
    "business-tools-tool-hub",
    "infra persistence",
    "live shared-backend",
)
REVIEW_DOC_REQUIRED_MARKERS = (
    "tests/e2e/test_browser_entry.spec.ts",
    "scripts/qa/run_smoke.sh",
    "scripts/qa/project_smoke.py",
    "scripts/qa/infra_persistence_matrix.py",
    "knowledge-rag-admin",
    "business-tools-tool-hub",
    "SMARTCLOUD_QA_USE_LIVE_INFRA",
    "docs/reviews/known-issues.md",
)
INFRA_PERSISTENCE_REQUIRED_MARKERS = (
    "auth-user-service",
    "knowledge-service",
    "marketing-service",
    "research-service",
    "orchestrator-service",
    "tool-hub-service",
    "business-tools-service",
    "deploy/docker-compose/smoke-test.py",
)


def repo_path(rel_path: str) -> Path:
    return REPO_ROOT / rel_path


def load_json(rel_path: str) -> dict[str, Any]:
    return json.loads(repo_path(rel_path).read_text(encoding="utf-8"))


def safe_load_json(rel_path: str) -> SafeResult:
    path = repo_path(rel_path)
    if not path.exists():
        return SafeResult(failures=(CheckFailure(rel_path, f"missing {rel_path}"),))
    try:
        return SafeResult(value=json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        return SafeResult(
            failures=(CheckFailure(rel_path, f"invalid JSON in {rel_path}: {exc}"),)
        )


def safe_read_text(rel_path: str) -> SafeResult:
    path = repo_path(rel_path)
    if not path.exists():
        return SafeResult(failures=(CheckFailure(rel_path, f"missing {rel_path}"),))
    try:
        return SafeResult(value=path.read_text(encoding="utf-8"))
    except OSError as exc:
        return SafeResult(failures=(CheckFailure(rel_path, f"unable to read {rel_path}: {exc}"),))


def _failure_check(category: str, failure: CheckFailure) -> dict[str, Any]:
    return {
        "name": f"{category}:{failure.path}",
        "category": category,
        "path": failure.path,
        "passed": False,
        "detail": failure.reason,
    }


def _append_safe_content_check(
    checks: list[dict[str, Any]],
    *,
    category: str,
    rel_path: str,
    name: str,
    detail_when_ok: str,
    missing_markers: tuple[str, ...] | list[str],
    missing_detail_prefix: str,
) -> None:
    read_result = safe_read_text(rel_path)
    if read_result.failures:
        checks.extend(_failure_check(category, failure) for failure in read_result.failures)
        return

    checks.append(
        {
            "name": name,
            "category": category,
            "path": rel_path,
            "passed": not missing_markers,
            "detail": (
                detail_when_ok
                if not missing_markers
                else f"{missing_detail_prefix}{', '.join(missing_markers)}"
            ),
        }
    )


def _prefixed_line(text: str, prefix: str) -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith(prefix):
            return line
    return ""


def _knowledge_rag_live_connector_state() -> str:
    qa_state_result = safe_load_json("logs/supervisor-integration-qa/state.json")
    if qa_state_result.failures:
        return "missing"
    qa_state = qa_state_result.value
    validation = qa_state.get("validation", {})
    if not isinstance(validation, dict):
        return "missing"
    scenario_status = validation.get("scenarioStatus", {})
    if not isinstance(scenario_status, dict):
        return "missing"
    knowledge_rag = scenario_status.get("knowledge-rag-admin", {})
    if not isinstance(knowledge_rag, dict):
        return "missing"
    status = str(knowledge_rag.get("status", "")).strip()
    return status or "missing"


def collect_path_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for expectation in ALL_PATH_EXPECTATIONS:
        path = repo_path(expectation.rel_path)
        exists = path.exists()
        checks.append(
            {
                "name": f"{expectation.category}:{expectation.rel_path}",
                "category": expectation.category,
                "path": expectation.rel_path,
                "passed": exists,
                "detail": expectation.note if exists else f"missing {expectation.rel_path} ({expectation.note})",
            }
        )
    return checks


def collect_package_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    web_user_package_result = safe_load_json("apps/web-user/package.json")
    if web_user_package_result.failures:
        checks.extend(_failure_check("web-user", failure) for failure in web_user_package_result.failures)
    else:
        web_user_package = web_user_package_result.value
        web_user_scripts = web_user_package.get("scripts", {})
        missing_web_user_scripts = sorted(set(WEB_USER_REQUIRED_SCRIPTS) - set(web_user_scripts))
        checks.append(
            {
                "name": "web-user:package-scripts",
                "category": "web-user",
                "path": "apps/web-user/package.json",
                "passed": not missing_web_user_scripts,
                "detail": (
                    f"web-user scripts present: {', '.join(WEB_USER_REQUIRED_SCRIPTS)}"
                    if not missing_web_user_scripts
                    else f"missing web-user scripts: {', '.join(missing_web_user_scripts)}"
                ),
            }
        )

    web_admin_package_result = safe_load_json("apps/web-admin/package.json")
    if web_admin_package_result.failures:
        checks.extend(_failure_check("web-admin", failure) for failure in web_admin_package_result.failures)
    else:
        web_admin_package = web_admin_package_result.value
        web_admin_scripts = web_admin_package.get("scripts", {})
        missing_web_admin_scripts = sorted(set(WEB_ADMIN_REQUIRED_SCRIPTS) - set(web_admin_scripts))
        checks.append(
            {
                "name": "web-admin:package-scripts",
                "category": "web-admin",
                "path": "apps/web-admin/package.json",
                "passed": not missing_web_admin_scripts,
                "detail": (
                    f"web-admin scripts present: {', '.join(WEB_ADMIN_REQUIRED_SCRIPTS)}"
                    if not missing_web_admin_scripts
                    else f"missing web-admin scripts: {', '.join(missing_web_admin_scripts)}"
                ),
            }
        )

    frontend_sdk_package_result = safe_load_json("packages/frontend-sdk/package.json")
    if frontend_sdk_package_result.failures:
        checks.extend(_failure_check("frontend-sdk", failure) for failure in frontend_sdk_package_result.failures)
    else:
        frontend_sdk_package = frontend_sdk_package_result.value
        frontend_sdk_exports = frontend_sdk_package.get("exports", {})
        missing_frontend_sdk_exports = sorted(
            set(FRONTEND_SDK_REQUIRED_EXPORTS) - set(frontend_sdk_exports)
        )
        checks.append(
            {
                "name": "frontend-sdk:package-exports",
                "category": "frontend-sdk",
                "path": "packages/frontend-sdk/package.json",
                "passed": not missing_frontend_sdk_exports,
                "detail": (
                    f"frontend-sdk exports present: {', '.join(FRONTEND_SDK_REQUIRED_EXPORTS)}"
                    if not missing_frontend_sdk_exports
                    else f"missing frontend-sdk exports: {', '.join(missing_frontend_sdk_exports)}"
                ),
            }
        )

    repo_e2e_package_result = safe_load_json("tests/e2e/package.json")
    if repo_e2e_package_result.failures:
        checks.extend(_failure_check("qa", failure) for failure in repo_e2e_package_result.failures)
    else:
        repo_e2e_package = repo_e2e_package_result.value
        repo_e2e_scripts = repo_e2e_package.get("scripts", {})
        missing_repo_e2e_scripts = sorted(set(REPO_E2E_REQUIRED_SCRIPTS) - set(repo_e2e_scripts))
        checks.append(
            {
                "name": "repo-e2e:package-scripts",
                "category": "qa",
                "path": "tests/e2e/package.json",
                "passed": not missing_repo_e2e_scripts,
                "detail": (
                    f"repo e2e scripts present: {', '.join(REPO_E2E_REQUIRED_SCRIPTS)}"
                    if not missing_repo_e2e_scripts
                    else f"missing repo e2e scripts: {', '.join(missing_repo_e2e_scripts)}"
                ),
            }
        )

    web_user_shared_sdk_source_result = safe_read_text("apps/web-user/src/shared-sdk.ts")
    if web_user_shared_sdk_source_result.failures:
        checks.extend(_failure_check("web-user", failure) for failure in web_user_shared_sdk_source_result.failures)
    else:
        web_user_shared_sdk_source = web_user_shared_sdk_source_result.value
        shared_sdk_uses_frontend_sdk = (
            "packages/frontend-sdk/src/core" in web_user_shared_sdk_source
            and "packages/frontend-sdk/src/web-user" in web_user_shared_sdk_source
        )
        checks.append(
            {
                "name": "web-user:shared-sdk-bridge",
                "category": "web-user",
                "path": "apps/web-user/src/shared-sdk.ts",
                "passed": shared_sdk_uses_frontend_sdk,
                "detail": (
                    "web-user shared SDK shim re-exports frontend-sdk core and web-user surfaces"
                    if shared_sdk_uses_frontend_sdk
                    else "web-user shared SDK shim no longer points at packages/frontend-sdk"
                ),
            }
        )

    web_admin_shared_sdk_source_result = safe_read_text("apps/web-admin/src/shared-sdk.ts")
    if web_admin_shared_sdk_source_result.failures:
        checks.extend(_failure_check("web-admin", failure) for failure in web_admin_shared_sdk_source_result.failures)
    else:
        web_admin_shared_sdk_source = web_admin_shared_sdk_source_result.value
        web_admin_uses_frontend_sdk = (
            "packages/frontend-sdk/src/core" in web_admin_shared_sdk_source
            and "packages/frontend-sdk/src/web-admin" in web_admin_shared_sdk_source
        )
        checks.append(
            {
                "name": "web-admin:shared-sdk-bridge",
                "category": "web-admin",
                "path": "apps/web-admin/src/shared-sdk.ts",
                "passed": web_admin_uses_frontend_sdk,
                "detail": (
                    "web-admin shared SDK shim re-exports frontend-sdk core and web-admin surfaces"
                    if web_admin_uses_frontend_sdk
                    else "web-admin shared SDK shim no longer points at packages/frontend-sdk"
                ),
            }
        )

    qa_state_result = safe_load_json("logs/supervisor-integration-qa/state.json")
    if qa_state_result.failures:
        checks.extend(_failure_check("qa", failure) for failure in qa_state_result.failures)
    else:
        qa_state = qa_state_result.value
        checks.append(
            {
                "name": "qa:state-owner",
                "category": "qa",
                "path": "logs/supervisor-integration-qa/state.json",
                "passed": qa_state.get("owner") == "supervisor-integration-qa",
                "detail": f"state owner={qa_state.get('owner')!r}",
            }
        )

    return checks


def collect_content_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    browser_entry_text = repo_path("tests/e2e/test_browser_entry.spec.ts").read_text(encoding="utf-8")
    missing_browser_markers = [
        marker for marker in BROWSER_ROOT_REQUIRED_MARKERS if marker not in browser_entry_text
    ]
    checks.append(
        {
            "name": "qa:root-browser-entry-error-path-matrix",
            "category": "qa",
            "path": "tests/e2e/test_browser_entry.spec.ts",
            "passed": not missing_browser_markers,
            "detail": (
                "root browser entry covers citation happy path plus 401 refresh, route permission denial, SSE reconnect, citation 403, marketing 429, and research report preview errors"
                if not missing_browser_markers
                else f"root browser entry is missing markers: {', '.join(missing_browser_markers)}"
            ),
        }
    )

    app_smoke_text = repo_path("tests/e2e/app-smoke.spec.ts").read_text(encoding="utf-8")
    missing_app_smoke_markers = [
        marker for marker in BROWSER_APP_SMOKE_REQUIRED_MARKERS if marker not in app_smoke_text
    ]
    checks.append(
        {
            "name": "qa:root-browser-app-smoke-covers-dashboard-and-session-happy-path",
            "category": "qa",
            "path": "tests/e2e/app-smoke.spec.ts",
            "passed": not missing_app_smoke_markers,
            "detail": (
                "root browser app smoke covers login, dashboard metrics, and seeded session history"
                if not missing_app_smoke_markers
                else f"root browser app smoke is missing markers: {', '.join(missing_app_smoke_markers)}"
            ),
        }
    )

    browser_playwright_smoke_text = repo_path("tests/e2e/playwright_smoke.spec.ts").read_text(
        encoding="utf-8"
    )
    missing_browser_playwright_markers = [
        marker
        for marker in BROWSER_PLAYWRIGHT_SMOKE_REQUIRED_MARKERS
        if marker not in browser_playwright_smoke_text
    ]
    checks.append(
        {
            "name": "qa:root-browser-reload-smoke-covers-marketing-and-research-persistence",
            "category": "qa",
            "path": "tests/e2e/playwright_smoke.spec.ts",
            "passed": not missing_browser_playwright_markers,
            "detail": (
                "root browser smoke covers marketing poster and research task cards surviving a reload"
                if not missing_browser_playwright_markers
                else (
                    "root browser reload smoke is missing markers: "
                    f"{', '.join(missing_browser_playwright_markers)}"
                )
            ),
        }
    )

    browser_ui_smoke_text = repo_path("tests/e2e/test_ui_smoke.py").read_text(encoding="utf-8")
    missing_browser_ui_smoke_markers = [
        marker for marker in BROWSER_UI_SMOKE_REQUIRED_MARKERS if marker not in browser_ui_smoke_text
    ]
    checks.append(
        {
            "name": "qa:root-browser-pytest-wiring",
            "category": "qa",
            "path": "tests/e2e/test_ui_smoke.py",
            "passed": not missing_browser_ui_smoke_markers,
            "detail": (
                "no-browser pytest smoke guards the root Playwright package, config, and execution command"
                if not missing_browser_ui_smoke_markers
                else (
                    "root browser pytest smoke is missing markers: "
                    f"{', '.join(missing_browser_ui_smoke_markers)}"
                )
            ),
        }
    )

    orchestrator_smoke_text = repo_path("tests/integration/test_orchestrator_smoke.py").read_text(
        encoding="utf-8"
    )
    missing_orchestrator_markers = [
        marker for marker in ORCHESTRATOR_SMOKE_REQUIRED_MARKERS if marker not in orchestrator_smoke_text
    ]
    checks.append(
        {
            "name": "qa:orchestrator-smoke-covers-auth-follow-up-and-sse-replay",
            "category": "qa",
            "path": "tests/integration/test_orchestrator_smoke.py",
            "passed": not missing_orchestrator_markers,
            "detail": (
                "orchestrator smoke covers collect-auth-context behavior and SSE replay/resume"
                if not missing_orchestrator_markers
                else (
                    "orchestrator smoke is missing markers: "
                    f"{', '.join(missing_orchestrator_markers)}"
                )
            ),
        }
    )

    error_path_smoke_text = repo_path("tests/integration/test_error_path_smoke.py").read_text(
        encoding="utf-8"
    )
    missing_error_path_markers = [
        marker for marker in ERROR_PATH_SMOKE_REQUIRED_MARKERS if marker not in error_path_smoke_text
    ]
    checks.append(
        {
            "name": "qa:error-path-smoke-covers-401-403-409-429-timeout-and-rag-fallbacks",
            "category": "qa",
            "path": "tests/integration/test_error_path_smoke.py",
            "passed": not missing_error_path_markers,
            "detail": (
                "error-path smoke covers structured 401/403/409/429 responses, tool timeout, and retrieve/diagnose/answer degraded-or-empty RAG behavior"
                if not missing_error_path_markers
                else (
                    "error-path smoke is missing markers: "
                    f"{', '.join(missing_error_path_markers)}"
                )
            ),
        }
    )

    run_smoke_text = repo_path("scripts/qa/run_smoke.sh").read_text(encoding="utf-8")
    missing_run_smoke_markers = [
        marker for marker in RUN_SMOKE_REQUIRED_MARKERS if marker not in run_smoke_text
    ]
    checks.append(
        {
            "name": "qa:run-smoke-covers-focused-and-service-process-baseline",
            "category": "qa",
            "path": "scripts/qa/run_smoke.sh",
            "passed": not missing_run_smoke_markers,
            "detail": (
                "run_smoke wires focused pytest, readiness, a default targeted service-process baseline, and optional broader acceptance layers"
                if not missing_run_smoke_markers
                else f"run_smoke is missing markers: {', '.join(missing_run_smoke_markers)}"
            ),
        }
    )

    project_smoke_text = repo_path("scripts/qa/project_smoke.py").read_text(encoding="utf-8")
    missing_project_smoke_markers = [
        marker for marker in PROJECT_SMOKE_REQUIRED_MARKERS if marker not in project_smoke_text
    ]
    checks.append(
        {
            "name": "qa:project-smoke-supports-local-and-live-backend-evidence",
            "category": "qa",
            "path": "scripts/qa/project_smoke.py",
            "passed": not missing_project_smoke_markers,
            "detail": (
                "project_smoke can run in local fallback mode or SMARTCLOUD_QA_USE_LIVE_INFRA mode, emits backend evidence for the exercised services, and keeps a real orchestrator timeout-chain probe"
                if not missing_project_smoke_markers
                else f"project_smoke is missing markers: {', '.join(missing_project_smoke_markers)}"
            ),
        }
    )

    compose_text = repo_path("deploy/docker-compose/docker-compose.yml").read_text(encoding="utf-8")
    missing_live_infra_compose_markers = [
        marker for marker in LIVE_INFRA_COMPOSE_REQUIRED_MARKERS if marker not in compose_text
    ]
    checks.append(
        {
            "name": "qa:compose-live-infra-surfaces-required-backends-and-minio-host-port",
            "category": "qa",
            "path": "deploy/docker-compose/docker-compose.yml",
            "passed": not missing_live_infra_compose_markers,
            "detail": (
                "compose-backed live QA keeps mysql/redis/minio/qdrant/opensearch services plus the MinIO host-port overrides required by shared-backend validation"
                if not missing_live_infra_compose_markers
                else (
                    "compose-backed live QA surface is missing markers: "
                    f"{', '.join(missing_live_infra_compose_markers)}"
                )
            ),
        }
    )

    infra_persistence_text = repo_path("scripts/qa/infra_persistence_matrix.py").read_text(
        encoding="utf-8"
    )
    missing_infra_persistence_markers = [
        marker for marker in INFRA_PERSISTENCE_REQUIRED_MARKERS if marker not in infra_persistence_text
    ]
    checks.append(
        {
            "name": "qa:infra-persistence-matrix-captures-current-backend-split",
            "category": "qa",
            "path": "scripts/qa/infra_persistence_matrix.py",
            "passed": not missing_infra_persistence_markers,
            "detail": (
                "infra persistence matrix distinguishes backend-capable services from current JSON/file-backed gaps"
                if not missing_infra_persistence_markers
                else (
                    "infra persistence matrix is missing markers: "
                    f"{', '.join(missing_infra_persistence_markers)}"
                )
            ),
        }
    )

    full_stack_runner_text = repo_path("scripts/qa/run_full_stack_validation.sh").read_text(
        encoding="utf-8"
    )
    missing_full_stack_markers = [
        marker for marker in FULL_STACK_RUNNER_REQUIRED_MARKERS if marker not in full_stack_runner_text
    ]
    checks.append(
        {
            "name": "qa:full-stack-runner-covers-stack-trace-compose-and-readiness",
            "category": "qa",
            "path": "scripts/qa/run_full_stack_validation.sh",
            "passed": not missing_full_stack_markers,
            "detail": (
                "full stack runner wires smoke, service-process, trace, compose, and strict readiness phases"
                if not missing_full_stack_markers
                else f"full stack runner is missing markers: {', '.join(missing_full_stack_markers)}"
            ),
        }
    )

    local_validation_text = repo_path("scripts/qa/run_local_validation.sh").read_text(encoding="utf-8")
    missing_local_validation_markers = [
        marker for marker in LOCAL_VALIDATION_REQUIRED_MARKERS if marker not in local_validation_text
    ]
    checks.append(
        {
            "name": "qa:local-validation-wrapper-covers-openapi-full-stack-and-pytest",
            "category": "qa",
            "path": "scripts/qa/run_local_validation.sh",
            "passed": not missing_local_validation_markers,
            "detail": (
                "local validation wrapper runs OpenAPI verification, full stack validation, and full pytest"
                if not missing_local_validation_markers
                else (
                    "local validation wrapper is missing markers: "
                    f"{', '.join(missing_local_validation_markers)}"
                )
            ),
        }
    )

    local_validation_text = repo_path("docs/runbooks/local-validation.md").read_text(encoding="utf-8")
    missing_live_infra_runbook_markers = [
        marker for marker in LIVE_INFRA_RUNBOOK_REQUIRED_MARKERS if marker not in local_validation_text
    ]
    minio_alignment_markers = (
        'SMARTCLOUD_QA_SHARED_MINIO_ENDPOINT="${SMARTCLOUD_QA_SHARED_MINIO_ENDPOINT:-http://127.0.0.1:${SMARTCLOUD_MINIO_HOST_PORT:-19000}}"',
        '"${SMARTCLOUD_MINIO_HOST_PORT:-19000}:9000"',
        '"${SMARTCLOUD_MINIO_CONSOLE_HOST_PORT:-19001}:9001"',
    )
    missing_minio_alignment_markers = [
        marker
        for marker in minio_alignment_markers
        if marker not in "\n".join(
            (
                repo_path("scripts/qa/qa_env.sh").read_text(encoding="utf-8"),
                compose_text,
            )
        )
    ]
    checks.append(
        {
            "name": "qa:live-infra-runbook-aligns-with-qa-env-minio-defaults",
            "category": "qa",
            "path": "docs/runbooks/local-validation.md",
            "passed": not missing_live_infra_runbook_markers and not missing_minio_alignment_markers,
            "detail": (
                "local validation documents the same shared-backend defaults that qa_env.sh and compose use, including the MinIO 19000/19001 host-port mapping"
                if not missing_live_infra_runbook_markers and not missing_minio_alignment_markers
                else (
                    "live-infra runbook alignment is missing markers: "
                    f"runbook={missing_live_infra_runbook_markers}, qa_env_or_compose={missing_minio_alignment_markers}"
                )
            ),
        }
    )

    qa_env_text = repo_path("scripts/qa/qa_env.sh").read_text(encoding="utf-8")
    missing_qa_env_markers = [marker for marker in QA_ENV_REQUIRED_MARKERS if marker not in qa_env_text]
    checks.append(
        {
            "name": "qa:shared-runner-bootstrap-covers-python-and-playwright-setup",
            "category": "qa",
            "path": "scripts/qa/qa_env.sh",
            "passed": not missing_qa_env_markers,
            "detail": (
                "shared QA runner bootstrap centralizes uv/python selection and Playwright availability checks"
                if not missing_qa_env_markers
                else f"shared QA runner bootstrap is missing markers: {', '.join(missing_qa_env_markers)}"
            ),
        }
    )

    live_knowledge_rag_state = _knowledge_rag_live_connector_state()

    known_issues_text = repo_path("docs/reviews/known-issues.md").read_text(encoding="utf-8")
    missing_known_issues_markers = [
        marker for marker in KNOWN_ISSUES_REQUIRED_MARKERS if marker not in known_issues_text
    ]
    checks.append(
        {
            "name": "qa:known-issues-register-tracks-current-blockers-and-browser-gap",
            "category": "qa",
            "path": "docs/reviews/known-issues.md",
            "passed": not missing_known_issues_markers,
            "detail": (
                "known-issues register tracks current shared blockers and the repo-root browser coverage gap"
                if not missing_known_issues_markers
                else f"known-issues register is missing markers: {', '.join(missing_known_issues_markers)}"
            ),
        }
    )

    status_doc_text = repo_path("docs/status/supervisor-integration-qa-status.md").read_text(
        encoding="utf-8"
    )
    missing_status_doc_markers = [
        marker for marker in STATUS_DOC_REQUIRED_MARKERS if marker not in status_doc_text
    ]
    checks.append(
        {
            "name": "qa:status-doc-summarizes-current-baseline-and-blocker-state",
            "category": "qa",
            "path": "docs/status/supervisor-integration-qa-status.md",
            "passed": not missing_status_doc_markers,
            "detail": (
                "status doc records focused baseline health, service-process baseline, browser smoke, and shared blockers"
                if not missing_status_doc_markers
                else f"status doc is missing markers: {', '.join(missing_status_doc_markers)}"
            ),
        }
    )

    qa_008_line = _prefixed_line(known_issues_text, "| QA-008 |")
    expected_qa_008_status = "resolved" if live_knowledge_rag_state == "passed" else "open"
    expected_qa_008_line = (
        f"| QA-008 | medium | {expected_qa_008_status} | knowledge-live-connector-proof |"
    )
    checks.append(
        {
            "name": "qa:known-issues-live-knowledge-status-aligns-with-state",
            "category": "qa",
            "path": "docs/reviews/known-issues.md",
            "passed": expected_qa_008_line in qa_008_line,
            "detail": (
                "known-issues QA-008 status matches the live knowledge/rag scenario state recorded in state.json"
                if expected_qa_008_line in qa_008_line
                else (
                    "known-issues QA-008 row does not match "
                    f"knowledge-rag-admin={live_knowledge_rag_state!r}: {qa_008_line or '<missing row>'}"
                )
            ),
        }
    )

    status_line = _prefixed_line(status_doc_text, "- Status:")
    expected_status_phrase = (
        "live knowledge/rag connector proof is green"
        if live_knowledge_rag_state == "passed"
        else "live knowledge/rag connector proof remains pending"
    )
    checks.append(
        {
            "name": "qa:status-doc-live-knowledge-status-aligns-with-state",
            "category": "qa",
            "path": "docs/status/supervisor-integration-qa-status.md",
            "passed": expected_status_phrase in status_line,
            "detail": (
                "status doc summary matches the live knowledge/rag scenario state recorded in state.json"
                if expected_status_phrase in status_line
                else (
                    "status doc summary does not match "
                    f"knowledge-rag-admin={live_knowledge_rag_state!r}: {status_line or '<missing status line>'}"
                )
            ),
        }
    )

    review_doc_text = repo_path("docs/reviews/integration-qa-baseline.md").read_text(encoding="utf-8")
    missing_review_doc_markers = [
        marker for marker in REVIEW_DOC_REQUIRED_MARKERS if marker not in review_doc_text
    ]
    checks.append(
        {
            "name": "qa:review-doc-links-browser-fast-path-and-known-issues",
            "category": "qa",
            "path": "docs/reviews/integration-qa-baseline.md",
            "passed": not missing_review_doc_markers,
            "detail": (
                "integration QA review links the root browser entry, the fast smoke path, the service-process runner, and known issues"
                if not missing_review_doc_markers
                else f"integration QA review is missing markers: {', '.join(missing_review_doc_markers)}"
            ),
        }
    )

    return checks


def collect_all_checks() -> list[dict[str, Any]]:
    return [*collect_path_checks(), *collect_package_checks(), *collect_content_checks()]


def collect_observations() -> list[dict[str, Any]]:
    e2e_dir = repo_path("tests/e2e")
    e2e_items = sorted(path.name for path in e2e_dir.iterdir()) if e2e_dir.exists() else []
    infra_persistence = build_infra_persistence_report()
    return [
        {
            "name": "tests-e2e-contents",
            "detail": ", ".join(e2e_items) if e2e_items else "tests/e2e exists but has no committed files yet",
        },
        {
            "name": "web-user-generated-artifacts",
            "detail": json.dumps(
                {
                    "distPresent": repo_path("apps/web-user/dist").exists(),
                    "nodeModulesPresent": repo_path("apps/web-user/node_modules").exists(),
                    "playwrightBinaryPresent": repo_path(
                        "apps/web-user/node_modules/.bin/playwright"
                    ).exists(),
                },
                ensure_ascii=False,
            ),
        },
        {
            "name": "web-admin-generated-artifacts",
            "detail": json.dumps(
                {
                    "nodeModulesPresent": repo_path("apps/web-admin/node_modules").exists(),
                },
                ensure_ascii=False,
            ),
        },
        {
            "name": "openapi-document-count",
            "detail": str(len(list(repo_path("openapi").glob("*.yaml")))),
        },
        {
            "name": "status-document-count",
            "detail": str(len(list(repo_path("docs/status").glob("*.md")))),
        },
        {
            "name": "infra-persistence-summary",
            "detail": json.dumps(infra_persistence["summary"], ensure_ascii=False, sort_keys=True),
        },
        {
            "name": "infra-persistence-failing-services",
            "detail": ", ".join(infra_persistence["summary"]["failingServices"]),
        },
    ]
