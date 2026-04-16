from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class PathExpectation:
    category: str
    rel_path: str
    note: str


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
        "apps/orchestrator-service/app/api/routes/orchestration.py",
        "orchestrator API routes",
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
        "apps/tool-hub-service/app/api/routes/tools.py",
        "tool-hub tool invocation routes",
    ),
    PathExpectation(
        "tool-hub",
        "apps/tool-hub-service/app/services/audit_store.py",
        "tool-hub audit persistence",
    ),
    PathExpectation("tool-hub", "openapi/tool-hub-service.openapi.yaml", "tool-hub published OpenAPI"),
    PathExpectation(
        "business-tools",
        "apps/business-tools/src/business_tools/catalog.py",
        "business-tools catalog implementation",
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
        "apps/knowledge-service/data/starter-catalog.json",
        "knowledge starter catalog",
    ),
    PathExpectation(
        "knowledge",
        "openapi/knowledge-service.openapi.yaml",
        "knowledge published OpenAPI",
    ),
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
        "tests/e2e/test_ui_smoke.py",
        "no-browser root browser wiring smoke",
    ),
    PathExpectation("qa", "tests/e2e/README.md", "repo-level browser smoke runbook"),
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

WEB_USER_REQUIRED_SCRIPTS = ("dev", "build", "typecheck", "docker:build")
WEB_ADMIN_REQUIRED_SCRIPTS = ("dev", "build", "preview")
FRONTEND_SDK_REQUIRED_EXPORTS = (".", "./core", "./web-user", "./web-admin")
REPO_E2E_REQUIRED_SCRIPTS = ("test:browser", "test:browser:headed", "install:browsers")
BROWSER_ROOT_REQUIRED_MARKERS = (
    "billing_summary_requires_refresh_once",
    "limited_marketing",
    "stream_disconnect_once",
    "citation_detail_forbidden",
    "marketing_copy_rate_limited",
)
BROWSER_UI_SMOKE_REQUIRED_MARKERS = (
    "test_browser_entry.spec.ts",
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
FULL_STACK_RUNNER_REQUIRED_MARKERS = (
    "scripts/qa/run_smoke.sh",
    "scripts/qa/project_smoke.py",
    "SMARTCLOUD_QA_RUN_BROWSER",
    "npm --prefix tests/e2e run test:browser",
    "deploy/docker-compose/trace-smoke.py",
    "deploy/docker-compose/smoke-test.py",
    "scripts/qa/release_readiness.py --strict",
)
LOCAL_VALIDATION_REQUIRED_MARKERS = (
    "scripts/qa/verify_openapi_contracts.py",
    "scripts/qa/run_full_stack_validation.sh",
    "pytest tests -q",
)


def repo_path(rel_path: str) -> Path:
    return REPO_ROOT / rel_path


def load_json(rel_path: str) -> dict[str, Any]:
    return json.loads(repo_path(rel_path).read_text(encoding="utf-8"))


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

    web_user_package = load_json("apps/web-user/package.json")
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

    web_admin_package = load_json("apps/web-admin/package.json")
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

    frontend_sdk_package = load_json("packages/frontend-sdk/package.json")
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

    repo_e2e_package = load_json("tests/e2e/package.json")
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

    web_user_shared_sdk_source = repo_path("apps/web-user/src/shared-sdk.ts").read_text(encoding="utf-8")
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

    web_admin_shared_sdk_source = repo_path("apps/web-admin/src/shared-sdk.ts").read_text(encoding="utf-8")
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

    qa_state = load_json("logs/supervisor-integration-qa/state.json")
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
                "root browser entry covers 401 refresh, route permission denial, SSE reconnect, citation 403, and marketing 429"
                if not missing_browser_markers
                else f"root browser entry is missing markers: {', '.join(missing_browser_markers)}"
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

    return checks


def collect_all_checks() -> list[dict[str, Any]]:
    return [*collect_path_checks(), *collect_package_checks(), *collect_content_checks()]


def collect_observations() -> list[dict[str, Any]]:
    e2e_dir = repo_path("tests/e2e")
    e2e_items = sorted(path.name for path in e2e_dir.iterdir()) if e2e_dir.exists() else []
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
    ]
