#!/usr/bin/env python3
"""Focused release-readiness report for the owned SmartCloud-X QA baseline."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.qa.baseline_expectations import (
    collect_content_checks,
    collect_observations,
    collect_package_checks,
    collect_path_checks,
)
from scripts.qa.infra_persistence_matrix import build_report as build_infra_persistence_report


ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "logs" / "supervisor-integration-qa" / "state.json"


def _summarize(checks: list[dict[str, object]]) -> dict[str, object]:
    failing = [check for check in checks if not check["passed"]]
    return {
        "passed": len(checks) - len(failing),
        "failed": len(failing),
        "total": len(checks),
        "failingChecks": [
            {
                "name": check["name"],
                "path": check["path"],
                "detail": check["detail"],
            }
            for check in failing
        ],
    }


def _check_item(
    *,
    item_id: str,
    label: str,
    checks: list[dict[str, object]],
    blocking: bool,
    detail: str,
) -> dict[str, object]:
    summary = _summarize(checks)
    return {
        "id": item_id,
        "label": label,
        "blocking": blocking,
        "passed": summary["failed"] == 0,
        "detail": detail if summary["failed"] == 0 else f"{detail} failed: {summary['failingChecks']}",
        "summary": summary,
    }


def _summarize_release_items(items: list[dict[str, object]]) -> dict[str, object]:
    failing = [item for item in items if not item["passed"]]
    return {
        "passed": len(items) - len(failing),
        "failed": len(failing),
        "total": len(items),
        "failingChecks": [
            {
                "id": item["id"],
                "label": item["label"],
                "detail": item["detail"],
            }
            for item in failing
        ],
    }


def _load_state_snapshot() -> dict[str, object]:
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def _missing_members(value: object, required: tuple[str, ...]) -> list[str]:
    if not isinstance(value, list):
        return list(required)
    actual = {str(item) for item in value}
    return [member for member in required if member not in actual]


def _require_evidence_dict(
    entry: dict[str, object],
    failures: list[str],
    *,
    validation_key: str,
) -> dict[str, object]:
    evidence = entry.get("evidence")
    if not isinstance(evidence, dict):
        failures.append(f"validation.{validation_key}.evidence is missing or not an object")
        return {}
    return evidence


def _require_true_fields(
    evidence: dict[str, object],
    failures: list[str],
    *,
    validation_key: str,
    fields: tuple[str, ...],
) -> None:
    for field in fields:
        if evidence.get(field) is not True:
            failures.append(f"validation.{validation_key}.evidence.{field} is not true")


def _require_positive_int_fields(
    evidence: dict[str, object],
    failures: list[str],
    *,
    validation_key: str,
    fields: tuple[str, ...],
) -> None:
    for field in fields:
        try:
            value = int(evidence.get(field, 0))
        except (TypeError, ValueError):
            value = 0
        if value < 1:
            failures.append(f"validation.{validation_key}.evidence.{field} is not a positive integer")


def _validation_state_item(
    *,
    item_id: str,
    label: str,
    validation_key: str,
    state_snapshot: dict[str, object],
    detail: str,
    blocking: bool,
    validator: Callable[[dict[str, object]], list[str]] | None = None,
) -> dict[str, object]:
    validation = state_snapshot.get("validation", {})
    entry = validation.get(validation_key) if isinstance(validation, dict) else None
    failures: list[str] = []

    if not isinstance(entry, dict):
        failures.append(
            f"validation.{validation_key} is missing from logs/supervisor-integration-qa/state.json"
        )
    else:
        if entry.get("passed") is not True:
            failures.append(f"validation.{validation_key}.passed is not true")
        if validator is not None:
            failures.extend(validator(entry))

    return {
        "id": item_id,
        "label": label,
        "blocking": blocking,
        "passed": not failures,
        "detail": detail if not failures else f"{detail} failed: {failures}",
        "summary": {
            "passed": 0 if failures else 1,
            "failed": len(failures),
            "total": 1,
            "failingChecks": failures,
        },
    }


def _scenario_state_item(
    *,
    item_id: str,
    label: str,
    scenario_names: tuple[str, ...],
    state_snapshot: dict[str, object],
    detail: str,
) -> dict[str, object]:
    validation = state_snapshot.get("validation", {})
    scenario_status = validation.get("scenarioStatus", {}) if isinstance(validation, dict) else {}
    results = []
    failing = []
    for scenario_name in scenario_names:
        status = scenario_status.get(scenario_name)
        passed = isinstance(status, dict) and status.get("status") == "passed"
        result = {
            "scenario": scenario_name,
            "passed": passed,
            "detail": (
                status.get("detail", "")
                if isinstance(status, dict)
                else "scenario status has not been recorded in logs/supervisor-integration-qa/state.json"
            ),
        }
        results.append(result)
        if not passed:
            failing.append(result)

    return {
        "id": item_id,
        "label": label,
        "blocking": False,
        "passed": not failing,
        "detail": detail if not failing else f"{detail} failed: {failing}",
        "summary": {
            "passed": len(results) - len(failing),
            "failed": len(failing),
            "total": len(results),
            "failingChecks": failing,
        },
    }


def build_report() -> dict[str, object]:
    path_checks = collect_path_checks()
    package_checks = collect_package_checks()
    content_checks = collect_content_checks()
    infra_persistence = build_infra_persistence_report()
    state_snapshot = _load_state_snapshot()

    def validate_local_smoke(entry: dict[str, object]) -> list[str]:
        failures: list[str] = []
        command = str(entry.get("command", ""))
        if "scripts/qa/run_smoke.sh" not in command:
            failures.append("local smoke command no longer points at scripts/qa/run_smoke.sh")
        if int(entry.get("focused_pytest_tests", 0)) < 1:
            failures.append("local smoke focused_pytest_tests is not positive")
        if "/" not in str(entry.get("readiness_checks", "")):
            failures.append("local smoke readiness_checks no longer records a pass/total summary")
        if "/" not in str(entry.get("infra_persistence_checks", "")):
            failures.append(
                "local smoke infra_persistence_checks no longer records a pass/total summary"
            )
        return failures

    def validate_repo_browser(entry: dict[str, object]) -> list[str]:
        failures: list[str] = []
        command = str(entry.get("command", ""))
        if "npm --prefix tests/e2e run test:browser" not in command:
            failures.append("repo browser command no longer points at the repo-root Playwright wrapper")
        if int(entry.get("tests_run", 0)) < 1:
            failures.append("repo browser tests_run is not positive")
        return failures

    def validate_knowledge_rag_restart(entry: dict[str, object]) -> list[str]:
        failures: list[str] = []
        command = str(entry.get("command", ""))
        if "--scenario knowledge-rag-admin" not in command:
            failures.append(
                "knowledge/rag restart smoke command no longer targets --scenario knowledge-rag-admin"
            )
        evidence = _require_evidence_dict(
            entry,
            failures,
            validation_key="knowledge_rag_restart_smoke",
        )
        if evidence.get("backend") != "local-runtime":
            failures.append(
                "validation.knowledge_rag_restart_smoke.evidence.backend is not local-runtime"
            )
        _require_true_fields(
            evidence,
            failures,
            validation_key="knowledge_rag_restart_smoke",
            fields=("snapshotEventRetainedAfterRestart",),
        )
        _require_positive_int_fields(
            evidence,
            failures,
            validation_key="knowledge_rag_restart_smoke",
            fields=(
                "searchTotalAfterRestart",
                "ragCandidateCountAfterRestart",
                "adminCandidateCountAfterRestart",
            ),
        )
        return failures

    def validate_orchestrator_timeout_chain_local(entry: dict[str, object]) -> list[str]:
        failures: list[str] = []
        command = str(entry.get("command", ""))
        if "--scenario orchestrator-billing" not in command:
            failures.append(
                "local orchestrator timeout-chain command no longer targets --scenario orchestrator-billing"
            )
        evidence = _require_evidence_dict(
            entry,
            failures,
            validation_key="orchestrator_timeout_chain_local",
        )
        if evidence.get("backend") != "local-fallback":
            failures.append(
                "validation.orchestrator_timeout_chain_local.evidence.backend is not local-fallback"
            )
        _require_true_fields(
            evidence,
            failures,
            validation_key="orchestrator_timeout_chain_local",
            fields=(
                "timeoutChainVerified",
                "toolHubTimeoutAuditRecorded",
                "persistedAfterRestart",
            ),
        )
        return failures

    def validate_live_shared_backend(entry: dict[str, object]) -> list[str]:
        failures: list[str] = []
        command = str(entry.get("command", ""))
        if "SMARTCLOUD_QA_USE_LIVE_INFRA=1" not in command:
            failures.append("live shared-backend command no longer enables SMARTCLOUD_QA_USE_LIVE_INFRA=1")
        missing_services = _missing_members(
            entry.get("services"),
            (
                "auth-user-service",
                "marketing-service",
                "research-service",
                "business-tools-service",
                "tool-hub-service",
                "orchestrator-service",
            ),
        )
        if missing_services:
            failures.append(f"live shared-backend services missing: {missing_services}")
        missing_backends = _missing_members(entry.get("backends"), ("mysql", "redis"))
        if missing_backends:
            failures.append(f"live shared-backend backends missing: {missing_backends}")
        evidence = _require_evidence_dict(
            entry,
            failures,
            validation_key="live_shared_backend",
        )
        if evidence.get("backend") != "mysql-and-redis":
            failures.append("validation.live_shared_backend.evidence.backend is not mysql-and-redis")
        _require_true_fields(
            evidence,
            failures,
            validation_key="live_shared_backend",
            fields=(
                "authRefreshSessionStored",
                "marketingCopyStored",
                "marketingPromotionLinkStored",
                "marketingPosterTaskStored",
                "marketingPosterIdempotencyStored",
                "researchTaskStored",
                "researchIdempotencyStored",
                "toolHubAuditStored",
                "conversationStored",
                "stateStored",
                "bootstrapFilesStatic",
            ),
        )
        _require_positive_int_fields(
            evidence,
            failures,
            validation_key="live_shared_backend",
            fields=(
                "businessToolsQueryCacheKeys",
                "businessToolsIdempotencyKeys",
                "sseRedisKeys",
            ),
        )
        return failures

    def validate_orchestrator_timeout_chain_live(entry: dict[str, object]) -> list[str]:
        failures: list[str] = []
        command = str(entry.get("command", ""))
        if "--scenario orchestrator-billing" not in command:
            failures.append("live orchestrator timeout-chain command no longer targets --scenario orchestrator-billing")
        missing_backends = _missing_members(entry.get("backends"), ("mysql", "redis"))
        if missing_backends:
            failures.append(f"live orchestrator timeout-chain backends missing: {missing_backends}")
        evidence = _require_evidence_dict(
            entry,
            failures,
            validation_key="orchestrator_timeout_chain_live",
        )
        if evidence.get("backend") != "mysql-and-redis":
            failures.append(
                "validation.orchestrator_timeout_chain_live.evidence.backend is not mysql-and-redis"
            )
        _require_true_fields(
            evidence,
            failures,
            validation_key="orchestrator_timeout_chain_live",
            fields=(
                "timeoutChainVerified",
                "timeoutAuditStored",
                "timeoutConversationStored",
                "timeoutStateStored",
            ),
        )
        _require_positive_int_fields(
            evidence,
            failures,
            validation_key="orchestrator_timeout_chain_live",
            fields=("sseRedisKeys",),
        )
        return failures

    def validate_live_knowledge_rag_connector(entry: dict[str, object]) -> list[str]:
        failures: list[str] = []
        command = str(entry.get("command", ""))
        if "SMARTCLOUD_QA_USE_LIVE_INFRA=1" not in command:
            failures.append(
                "live knowledge/rag connector command no longer enables SMARTCLOUD_QA_USE_LIVE_INFRA=1"
            )
        if "--scenario knowledge-rag-admin" not in command:
            failures.append(
                "live knowledge/rag connector command no longer targets --scenario knowledge-rag-admin"
            )
        missing_backends = _missing_members(
            entry.get("backends"),
            ("mysql", "redis", "minio", "qdrant", "opensearch"),
        )
        if missing_backends:
            failures.append(f"live knowledge/rag connector backends missing: {missing_backends}")

        evidence = _require_evidence_dict(
            entry,
            failures,
            validation_key="live_knowledge_rag_connector",
        )
        if evidence.get("backend") != "shared-connectors":
            failures.append(
                "validation.live_knowledge_rag_connector.evidence.backend is not shared-connectors"
            )
        if evidence.get("rawStorage") != "minio":
            failures.append(
                "validation.live_knowledge_rag_connector.evidence.rawStorage is not minio"
            )
        if evidence.get("metadataStore") != "mysql":
            failures.append(
                "validation.live_knowledge_rag_connector.evidence.metadataStore is not mysql"
            )
        if evidence.get("vectorStore") != "qdrant":
            failures.append(
                "validation.live_knowledge_rag_connector.evidence.vectorStore is not qdrant"
            )
        if evidence.get("bm25Store") != "opensearch":
            failures.append(
                "validation.live_knowledge_rag_connector.evidence.bm25Store is not opensearch"
            )
        if evidence.get("cache") not in {"redis-configured", "redis-ttl"}:
            failures.append(
                "validation.live_knowledge_rag_connector.evidence.cache is not a redis-backed value"
            )
        if evidence.get("taskQueue") != "redis-list-primary":
            failures.append(
                "validation.live_knowledge_rag_connector.evidence.taskQueue is not redis-list-primary"
            )
        _require_true_fields(
            evidence,
            failures,
            validation_key="live_knowledge_rag_connector",
            fields=("snapshotEventRetainedAfterRestart",),
        )
        _require_positive_int_fields(
            evidence,
            failures,
            validation_key="live_knowledge_rag_connector",
            fields=(
                "connectorResults",
                "searchTotalAfterRestart",
                "ragCandidateCountAfterRestart",
                "adminCandidateCountAfterRestart",
            ),
        )
        return failures

    def validate_live_marketing_minio_artifact(entry: dict[str, object]) -> list[str]:
        failures: list[str] = []
        command = str(entry.get("command", ""))
        if "SMARTCLOUD_QA_USE_LIVE_INFRA=1" not in command:
            failures.append(
                "live marketing MinIO artifact command no longer enables SMARTCLOUD_QA_USE_LIVE_INFRA=1"
            )
        if "--scenario auth-marketing-research" not in command:
            failures.append(
                "live marketing MinIO artifact command no longer targets --scenario auth-marketing-research"
            )
        missing_backends = _missing_members(
            entry.get("backends"),
            ("mysql", "redis", "minio"),
        )
        if missing_backends:
            failures.append(f"live marketing MinIO artifact backends missing: {missing_backends}")

        evidence = _require_evidence_dict(
            entry,
            failures,
            validation_key="live_marketing_minio_artifact",
        )
        if evidence.get("backend") != "mysql-redis-minio":
            failures.append(
                "validation.live_marketing_minio_artifact.evidence.backend is not mysql-redis-minio"
            )
        if not isinstance(evidence.get("marketingPosterObjectStored"), bool):
            failures.append(
                "validation.live_marketing_minio_artifact.evidence.marketingPosterObjectStored is not a boolean"
            )
        return failures

    key_service_checks = [
        check for check in path_checks if check["category"] not in {"contracts", "status", "qa"}
    ]
    contract_and_status_checks = [
        check for check in path_checks if check["category"] in {"contracts", "status"}
    ]
    owned_qa_checks = [check for check in path_checks if check["category"] == "qa"]
    browser_checks = [
        *[check for check in path_checks if str(check["path"]).startswith("tests/e2e")],
        *[check for check in package_checks if check["path"] == "tests/e2e/package.json"],
        *[check for check in content_checks if str(check["path"]).startswith("tests/e2e/")],
    ]
    runner_checks = [
        *[
            check
            for check in path_checks
            if str(check["path"]).startswith("scripts/qa/")
            or str(check["path"]) == "docs/runbooks/local-validation.md"
        ],
        *[
            check
            for check in content_checks
            if str(check["path"]).startswith("scripts/qa/")
            or str(check["path"]) == "docs/runbooks/local-validation.md"
        ],
    ]
    shared_backend_checks = [
        *[
            check
            for check in path_checks
            if str(check["path"])
            in {
                "scripts/qa/project_smoke.py",
                "scripts/qa/qa_env.sh",
                "scripts/qa/run_full_stack_validation.sh",
                "docs/runbooks/local-validation.md",
            }
        ],
        *[
            check
            for check in content_checks
            if str(check["path"])
            in {
                "deploy/docker-compose/docker-compose.yml",
                "scripts/qa/project_smoke.py",
                "scripts/qa/qa_env.sh",
                "scripts/qa/run_full_stack_validation.sh",
                "scripts/qa/run_local_validation.sh",
                "scripts/qa/run_smoke.sh",
                "docs/runbooks/local-validation.md",
            }
        ],
    ]
    reporting_checks = [
        *[
            check
            for check in content_checks
            if str(check["path"])
            in {
                "docs/reviews/known-issues.md",
                "docs/reviews/integration-qa-baseline.md",
                "docs/status/supervisor-integration-qa-status.md",
            }
        ],
    ]
    recorded_runtime_items = [
        _validation_state_item(
            item_id="local-smoke-recorded",
            label="local smoke recorded",
            validation_key="local_smoke",
            state_snapshot=state_snapshot,
            blocking=True,
            detail=(
                "state.json records a passing focused scripts/qa/run_smoke.sh run with pytest, readiness, infra-persistence, and default service-process evidence"
            ),
            validator=validate_local_smoke,
        ),
        _validation_state_item(
            item_id="repo-browser-validation-recorded",
            label="repo browser validation recorded",
            validation_key="repo_browser",
            state_snapshot=state_snapshot,
            blocking=True,
            detail=(
                "state.json records a passing repo-root Playwright rerun through tests/e2e"
            ),
            validator=validate_repo_browser,
        ),
        _validation_state_item(
            item_id="knowledge-rag-local-restart-proof-recorded",
            label="knowledge rag local restart proof recorded",
            validation_key="knowledge_rag_restart_smoke",
            state_snapshot=state_snapshot,
            blocking=True,
            detail=(
                "state.json records a passing restart-aware knowledge/rag subprocess validation"
            ),
            validator=validate_knowledge_rag_restart,
        ),
        _validation_state_item(
            item_id="orchestrator-timeout-chain-local-proof-recorded",
            label="orchestrator timeout-chain local proof recorded",
            validation_key="orchestrator_timeout_chain_local",
            state_snapshot=state_snapshot,
            blocking=True,
            detail=(
                "state.json records a passing local orchestrator -> tool-hub -> business-tools timeout-chain validation"
            ),
            validator=validate_orchestrator_timeout_chain_local,
        ),
        _validation_state_item(
            item_id="live-auth-tooling-backend-proof-recorded",
            label="live auth tooling backend proof recorded",
            validation_key="live_shared_backend",
            state_snapshot=state_snapshot,
            blocking=True,
            detail=(
                "state.json records a passing live MySQL/Redis rerun for auth/marketing/research plus business-tools/tool-hub/orchestrator"
            ),
            validator=validate_live_shared_backend,
        ),
        _validation_state_item(
            item_id="live-orchestrator-timeout-chain-proof-recorded",
            label="live orchestrator timeout-chain proof recorded",
            validation_key="orchestrator_timeout_chain_live",
            state_snapshot=state_snapshot,
            blocking=True,
            detail=(
                "state.json records a passing live MySQL/Redis timeout-chain rerun for orchestrator/tool-hub/business-tools"
            ),
            validator=validate_orchestrator_timeout_chain_live,
        ),
        _validation_state_item(
            item_id="live-knowledge-rag-connector-rerun-recorded",
            label="live knowledge rag connector rerun recorded",
            validation_key="live_knowledge_rag_connector",
            state_snapshot=state_snapshot,
            blocking=True,
            detail=(
                "state.json records a successful live knowledge/rag connector rerun with MySQL/Redis/MinIO/Qdrant/OpenSearch-backed proof"
            ),
            validator=validate_live_knowledge_rag_connector,
        ),
    ]

    release_checklist = [
        _check_item(
            item_id="key-service-assets-present",
            label="key service assets present",
            checks=key_service_checks,
            blocking=True,
            detail="auth/orchestrator/knowledge/rag/web-user/frontend-sdk service assets and current repo entrypoints are present",
        ),
        _check_item(
            item_id="owned-artifacts-present",
            label="owned qa artifacts present",
            checks=owned_qa_checks,
            blocking=True,
            detail="owned integration tests, repo e2e wrapper, qa scripts, runbooks, reviews, status, and logs are committed",
        ),
        _check_item(
            item_id="contracts-and-status-docs-present",
            label="contracts and status docs present",
            checks=contract_and_status_checks,
            blocking=True,
            detail="shared contracts plus supervisor status docs required by the current QA baseline are present",
        ),
        _check_item(
            item_id="repo-browser-entry-present",
            label="repo browser entry present",
            checks=browser_checks,
            blocking=True,
            detail="tests/e2e keeps a real Playwright wrapper, runnable scripts, and a no-browser guard for the current error-path matrix",
        ),
        _check_item(
            item_id="qa-runners-present",
            label="qa runners present",
            checks=runner_checks,
            blocking=True,
            detail="focused smoke, local validation, and readiness runners keep the current QA workflow wired",
        ),
        _check_item(
            item_id="shared-backend-acceptance-path-present",
            label="shared backend acceptance path present",
            checks=shared_backend_checks,
            blocking=True,
            detail="qa runners, env bootstrap, and the local validation runbook support SMARTCLOUD_QA_USE_LIVE_INFRA and shared-backend evidence collection",
        ),
        _check_item(
            item_id="qa-reporting-consistent",
            label="qa reporting consistent",
            checks=reporting_checks,
            blocking=True,
            detail="integration QA status and review docs align with the current browser scope, baseline, and live runtime state recorded in state.json",
        ),
        {
            "id": "runtime-backend-capability-matrix-green",
            "label": "runtime backend capability matrix green",
            "blocking": True,
            "passed": infra_persistence["summary"]["failed"] == 0,
            "detail": (
                "owned infra persistence matrix is green across the current runtime backend helper, degraded-health, and shared-backend acceptance markers"
                if infra_persistence["summary"]["failed"] == 0
                else (
                    "owned infra persistence matrix still has service gaps: "
                    + ", ".join(infra_persistence["summary"]["failingServices"])
                )
            ),
            "summary": infra_persistence["summary"],
        },
        *recorded_runtime_items,
        {
            "id": "infra-persistence-live-proof",
            "label": "infra persistence capability report",
            "blocking": False,
            "passed": infra_persistence["summary"]["failed"] == 0,
            "detail": (
                "the owned infra persistence capability report is green for all tracked services"
                if infra_persistence["summary"]["failed"] == 0
                else (
                    "the owned infra persistence capability report still has service gaps: "
                    + ", ".join(infra_persistence["summary"]["failingServices"])
                )
            ),
            "summary": infra_persistence["summary"],
        },
        _validation_state_item(
            item_id="live-marketing-minio-artifact-proof-recorded",
            label="live marketing minio artifact proof recorded",
            validation_key="live_marketing_minio_artifact",
            state_snapshot=state_snapshot,
            blocking=False,
            detail=(
                "state.json records whether the stronger live auth/marketing/research rerun stores marketing poster artifacts in MinIO"
            ),
            validator=validate_live_marketing_minio_artifact,
        ),
        _scenario_state_item(
            item_id="live-auth-and-orchestrator-backend-rerun-recorded",
            label="live auth and orchestrator backend rerun recorded",
            scenario_names=(
                "auth-marketing-research",
                "business-tools-tool-hub",
                "orchestrator-billing",
            ),
            state_snapshot=state_snapshot,
            detail=(
                "state.json records successful live shared-backend reruns for auth/marketing/research plus business-tools/tool-hub and orchestrator"
            ),
        ),
    ]

    blocking_failures = [
        item["id"]
        for item in release_checklist
        if item["blocking"] and not item["passed"]
    ]
    all_checks = [*path_checks, *package_checks, *content_checks]
    return {
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "owner": "supervisor-integration-qa",
        "workspace": str(ROOT),
        "ok": not blocking_failures,
        "blockingFailures": blocking_failures,
        "summary": _summarize(all_checks),
        "releaseChecklist": release_checklist,
        "focusAreas": {
            "keyServiceAssets": _summarize(key_service_checks),
            "contractsAndStatus": _summarize(contract_and_status_checks),
            "ownedQaArtifacts": _summarize(owned_qa_checks),
            "repoBrowserEntry": _summarize(browser_checks),
            "qaRunners": _summarize(runner_checks),
            "sharedBackendAcceptance": _summarize(shared_backend_checks),
            "qaReporting": _summarize(reporting_checks),
            "recordedRuntimeEvidence": _summarize_release_items(recorded_runtime_items),
            "infraPersistence": infra_persistence,
        },
        "observations": collect_observations(),
    }


def main() -> int:
    report = build_report()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
