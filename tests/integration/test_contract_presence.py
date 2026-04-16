from __future__ import annotations

import json

from scripts.qa.baseline_expectations import (
    FOUNDATION_CONTRACT_EXPECTATIONS,
    KEY_SERVICE_EXPECTATIONS,
    QA_BASELINE_EXPECTATIONS,
    STATUS_DOC_EXPECTATIONS,
    collect_content_checks,
    collect_package_checks,
    repo_path,
)
from scripts.qa.check_release_readiness import build_report
from scripts.qa.infra_persistence_matrix import build_report as build_infra_persistence_report


PERSISTENCE_CHANGE_REQUESTS = (
    "docs/contracts/change-requests/2026-04-16-persistence-backend-contract-baseline.md",
    "docs/contracts/change-requests/2026-04-16-auth-marketing-research-runtime-backend-health-baseline.md",
)
REQUIRED_STATE_VALIDATIONS = (
    "local_smoke",
    "knowledge_rag_restart_smoke",
    "orchestrator_timeout_chain_local",
    "repo_browser",
    "readiness",
    "infra_persistence",
    "live_shared_backend",
    "live_knowledge_rag_connector",
    "live_marketing_minio_artifact",
    "orchestrator_timeout_chain_live",
    "scenarioStatus",
)
REQUIRED_LIVE_SHARED_BACKEND_SERVICES = (
    "auth-user-service",
    "marketing-service",
    "research-service",
    "business-tools-service",
    "tool-hub-service",
    "orchestrator-service",
)
REQUIRED_LIVE_SHARED_BACKEND_EVIDENCE = (
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
)
REQUIRED_LIVE_SHARED_BACKEND_POSITIVE_COUNTERS = (
    "businessToolsQueryCacheKeys",
    "businessToolsIdempotencyKeys",
    "sseRedisKeys",
)
REQUIRED_KNOWLEDGE_RAG_RESTART_EVIDENCE = (
    "snapshotEventRetainedAfterRestart",
    "searchTotalAfterRestart",
    "ragCandidateCountAfterRestart",
    "adminCandidateCountAfterRestart",
)
REQUIRED_LOCAL_TIMEOUT_CHAIN_EVIDENCE = (
    "timeoutChainVerified",
    "toolHubTimeoutAuditRecorded",
    "persistedAfterRestart",
)
REQUIRED_LIVE_TIMEOUT_CHAIN_EVIDENCE = (
    "timeoutChainVerified",
    "timeoutAuditStored",
    "timeoutConversationStored",
    "timeoutStateStored",
    "sseRedisKeys",
)
REQUIRED_LIVE_KNOWLEDGE_RAG_BACKENDS = (
    "mysql",
    "redis",
    "minio",
    "qdrant",
    "opensearch",
)
REQUIRED_LIVE_KNOWLEDGE_RAG_EVIDENCE = (
    "rawStorage",
    "metadataStore",
    "vectorStore",
    "bm25Store",
    "cache",
    "taskQueue",
    "connectorResults",
    "snapshotEventRetainedAfterRestart",
    "searchTotalAfterRestart",
    "ragCandidateCountAfterRestart",
    "adminCandidateCountAfterRestart",
)
REQUIRED_SCENARIOS = (
    "auth-marketing-research",
    "business-tools-tool-hub",
    "orchestrator-billing",
    "knowledge-rag-admin",
)
REQUIRED_INFRA_PERSISTENCE_SERVICES = (
    "auth-user-service",
    "knowledge-service",
    "rag-service",
    "marketing-service",
    "research-service",
    "orchestrator-service",
    "tool-hub-service",
    "business-tools-service",
)
REQUIRED_INFRA_PERSISTENCE_CHECKS = (
    "auth-store-has-database-runtime-surface",
    "knowledge-runtime-surfaces-real-connectors",
    "orchestrator-runtime-surface-is-mysql-redis-capable",
    "orchestrator-owned-health-smoke-surfaces-degraded-backend-truth",
    "tool-hub-runtime-surface-is-mysql-redis-capable",
    "tool-hub-owned-health-smoke-surfaces-degraded-backend-truth",
    "business-tools-runtime-surface-is-redis-first-capable",
    "business-tools-owned-health-smoke-surfaces-degraded-backend-truth",
    "marketing-live-shared-backend-acceptance-path-is-available",
    "research-live-shared-backend-acceptance-path-is-available",
)
REQUIRED_REPORTING_CHECKS = (
    "qa:known-issues-live-knowledge-status-aligns-with-state",
    "qa:status-doc-live-knowledge-status-aligns-with-state",
)
REQUIRED_SHARED_BACKEND_CONTENT_CHECKS = (
    "qa:compose-live-infra-surfaces-required-backends-and-minio-host-port",
    "qa:live-infra-runbook-aligns-with-qa-env-minio-defaults",
)


def _missing_paths(*rel_paths: str) -> list[str]:
    return [rel_path for rel_path in rel_paths if not repo_path(rel_path).exists()]


def _load_state_snapshot() -> dict[str, object]:
    return json.loads(
        repo_path("logs/supervisor-integration-qa/state.json").read_text(encoding="utf-8")
    )


def test_key_service_assets_exist_for_current_repo_baseline() -> None:
    missing = _missing_paths(*(expectation.rel_path for expectation in KEY_SERVICE_EXPECTATIONS))
    assert not missing, f"missing key service assets: {missing}"


def test_foundation_contracts_status_docs_and_qa_artifacts_exist() -> None:
    missing = _missing_paths(
        *(expectation.rel_path for expectation in FOUNDATION_CONTRACT_EXPECTATIONS),
        *(expectation.rel_path for expectation in STATUS_DOC_EXPECTATIONS),
        *(expectation.rel_path for expectation in QA_BASELINE_EXPECTATIONS),
    )
    assert not missing, f"missing contracts/status/qa artifacts: {missing}"


def test_repo_packages_keep_required_scripts_and_exports() -> None:
    package_failures = [
        check["detail"]
        for check in collect_package_checks()
        if not check["passed"]
    ]
    assert not package_failures, f"package baseline drift detected: {package_failures}"


def test_reporting_docs_align_with_state_snapshot() -> None:
    content_checks = {check["name"]: check for check in collect_content_checks()}
    missing = [check_name for check_name in REQUIRED_REPORTING_CHECKS if check_name not in content_checks]
    assert not missing, f"missing reporting consistency checks: {missing}"

    failures = [
        content_checks[check_name]["detail"]
        for check_name in REQUIRED_REPORTING_CHECKS
        if not content_checks[check_name]["passed"]
    ]
    assert not failures, f"reporting/state consistency drift detected: {failures}"


def test_shared_backend_docs_and_compose_surface_stay_aligned() -> None:
    content_checks = {check["name"]: check for check in collect_content_checks()}
    missing = [
        check_name
        for check_name in REQUIRED_SHARED_BACKEND_CONTENT_CHECKS
        if check_name not in content_checks
    ]
    assert not missing, f"missing shared-backend content checks: {missing}"

    failures = [
        content_checks[check_name]["detail"]
        for check_name in REQUIRED_SHARED_BACKEND_CONTENT_CHECKS
        if not content_checks[check_name]["passed"]
    ]
    assert not failures, f"shared-backend compose/runbook drift detected: {failures}"


def test_current_persistence_change_requests_are_present() -> None:
    missing = _missing_paths(*PERSISTENCE_CHANGE_REQUESTS)
    assert not missing, f"missing current persistence change requests: {missing}"


def test_qa_state_snapshot_tracks_required_runtime_validation_entries() -> None:
    state_snapshot = _load_state_snapshot()
    validation = state_snapshot.get("validation")

    assert isinstance(validation, dict)
    missing = [key for key in REQUIRED_STATE_VALIDATIONS if key not in validation]
    assert not missing, f"missing required state validation entries: {missing}"

    local_smoke = validation["local_smoke"]
    assert isinstance(local_smoke, dict)
    assert local_smoke.get("passed") is True
    assert "scripts/qa/run_smoke.sh" in str(local_smoke.get("command", ""))
    assert int(local_smoke.get("focused_pytest_tests", 0)) >= 1

    knowledge_rag_restart = validation["knowledge_rag_restart_smoke"]
    assert isinstance(knowledge_rag_restart, dict)
    assert knowledge_rag_restart.get("passed") is True
    assert "--scenario knowledge-rag-admin" in str(knowledge_rag_restart.get("command", ""))
    knowledge_rag_evidence = knowledge_rag_restart.get("evidence")
    assert isinstance(knowledge_rag_evidence, dict)
    assert knowledge_rag_evidence.get("backend") == "local-runtime"
    assert set(REQUIRED_KNOWLEDGE_RAG_RESTART_EVIDENCE) <= set(knowledge_rag_evidence)
    assert knowledge_rag_evidence["snapshotEventRetainedAfterRestart"] is True
    assert int(knowledge_rag_evidence["searchTotalAfterRestart"]) >= 1
    assert int(knowledge_rag_evidence["ragCandidateCountAfterRestart"]) >= 1
    assert int(knowledge_rag_evidence["adminCandidateCountAfterRestart"]) >= 1

    local_timeout_chain = validation["orchestrator_timeout_chain_local"]
    assert isinstance(local_timeout_chain, dict)
    assert local_timeout_chain.get("passed") is True
    assert "--scenario orchestrator-billing" in str(local_timeout_chain.get("command", ""))
    local_timeout_evidence = local_timeout_chain.get("evidence")
    assert isinstance(local_timeout_evidence, dict)
    assert local_timeout_evidence.get("backend") == "local-fallback"
    assert set(REQUIRED_LOCAL_TIMEOUT_CHAIN_EVIDENCE) <= set(local_timeout_evidence)
    assert local_timeout_evidence["timeoutChainVerified"] is True
    assert local_timeout_evidence["toolHubTimeoutAuditRecorded"] is True
    assert local_timeout_evidence["persistedAfterRestart"] is True

    live_shared_backend = validation["live_shared_backend"]
    assert isinstance(live_shared_backend, dict)
    assert live_shared_backend.get("passed") is True
    assert set(REQUIRED_LIVE_SHARED_BACKEND_SERVICES) <= set(live_shared_backend.get("services", []))
    assert {"mysql", "redis"} <= set(live_shared_backend.get("backends", []))
    live_shared_backend_evidence = live_shared_backend.get("evidence")
    assert isinstance(live_shared_backend_evidence, dict)
    assert live_shared_backend_evidence.get("backend") == "mysql-and-redis"
    assert set(REQUIRED_LIVE_SHARED_BACKEND_EVIDENCE) <= set(live_shared_backend_evidence)
    for field in REQUIRED_LIVE_SHARED_BACKEND_EVIDENCE:
        assert live_shared_backend_evidence[field] is True
    for field in REQUIRED_LIVE_SHARED_BACKEND_POSITIVE_COUNTERS:
        assert int(live_shared_backend_evidence[field]) >= 1

    live_timeout_chain = validation["orchestrator_timeout_chain_live"]
    assert isinstance(live_timeout_chain, dict)
    assert live_timeout_chain.get("passed") is True
    assert {"mysql", "redis"} <= set(live_timeout_chain.get("backends", []))
    live_timeout_evidence = live_timeout_chain.get("evidence")
    assert isinstance(live_timeout_evidence, dict)
    assert live_timeout_evidence.get("backend") == "mysql-and-redis"
    assert set(REQUIRED_LIVE_TIMEOUT_CHAIN_EVIDENCE) <= set(live_timeout_evidence)
    assert live_timeout_evidence["timeoutChainVerified"] is True
    assert live_timeout_evidence["timeoutAuditStored"] is True
    assert live_timeout_evidence["timeoutConversationStored"] is True
    assert live_timeout_evidence["timeoutStateStored"] is True
    assert int(live_timeout_evidence["sseRedisKeys"]) >= 1

    live_knowledge_rag = validation["live_knowledge_rag_connector"]
    assert isinstance(live_knowledge_rag, dict)
    assert live_knowledge_rag.get("passed") is True
    assert "SMARTCLOUD_QA_USE_LIVE_INFRA=1" in str(live_knowledge_rag.get("command", ""))
    assert "--scenario knowledge-rag-admin" in str(live_knowledge_rag.get("command", ""))
    assert set(REQUIRED_LIVE_KNOWLEDGE_RAG_BACKENDS) <= set(live_knowledge_rag.get("backends", []))
    live_knowledge_rag_evidence = live_knowledge_rag.get("evidence")
    assert isinstance(live_knowledge_rag_evidence, dict)
    assert live_knowledge_rag_evidence.get("backend") == "shared-connectors"
    assert set(REQUIRED_LIVE_KNOWLEDGE_RAG_EVIDENCE) <= set(live_knowledge_rag_evidence)
    assert live_knowledge_rag_evidence["rawStorage"] == "minio"
    assert live_knowledge_rag_evidence["metadataStore"] == "mysql"
    assert live_knowledge_rag_evidence["vectorStore"] == "qdrant"
    assert live_knowledge_rag_evidence["bm25Store"] == "opensearch"
    assert live_knowledge_rag_evidence["cache"] in {"redis-configured", "redis-ttl"}
    assert live_knowledge_rag_evidence["taskQueue"] == "redis-list-primary"
    assert live_knowledge_rag_evidence["snapshotEventRetainedAfterRestart"] is True
    assert int(live_knowledge_rag_evidence["connectorResults"]) >= 1
    assert int(live_knowledge_rag_evidence["searchTotalAfterRestart"]) >= 1
    assert int(live_knowledge_rag_evidence["ragCandidateCountAfterRestart"]) >= 1
    assert int(live_knowledge_rag_evidence["adminCandidateCountAfterRestart"]) >= 1

    live_marketing_minio = validation["live_marketing_minio_artifact"]
    assert isinstance(live_marketing_minio, dict)
    assert live_marketing_minio.get("passed") is False
    assert "SMARTCLOUD_QA_USE_LIVE_INFRA=1" in str(live_marketing_minio.get("command", ""))
    assert "--scenario auth-marketing-research" in str(live_marketing_minio.get("command", ""))
    assert {"mysql", "redis", "minio"} <= set(live_marketing_minio.get("backends", []))
    live_marketing_minio_evidence = live_marketing_minio.get("evidence")
    assert isinstance(live_marketing_minio_evidence, dict)
    assert live_marketing_minio_evidence.get("backend") == "mysql-redis-minio"
    assert live_marketing_minio_evidence.get("marketingPosterObjectStored") is False

    scenario_status = validation["scenarioStatus"]
    assert isinstance(scenario_status, dict)
    assert set(REQUIRED_SCENARIOS) <= set(scenario_status)
    assert scenario_status["knowledge-rag-admin"]["status"] == "passed"


def test_release_readiness_report_tracks_recorded_runtime_proof_items() -> None:
    report = build_report()
    checklist = {item["id"]: item for item in report["releaseChecklist"]}

    required_items = {
        "runtime-backend-capability-matrix-green",
        "local-smoke-recorded",
        "repo-browser-validation-recorded",
        "knowledge-rag-local-restart-proof-recorded",
        "orchestrator-timeout-chain-local-proof-recorded",
        "live-auth-tooling-backend-proof-recorded",
        "live-orchestrator-timeout-chain-proof-recorded",
        "live-knowledge-rag-connector-rerun-recorded",
        "qa-reporting-consistent",
        "live-marketing-minio-artifact-proof-recorded",
    }
    assert required_items <= set(checklist)
    assert report["ok"] is True
    assert checklist["runtime-backend-capability-matrix-green"]["blocking"] is True
    assert checklist["local-smoke-recorded"]["blocking"] is True
    assert checklist["repo-browser-validation-recorded"]["blocking"] is True
    assert checklist["knowledge-rag-local-restart-proof-recorded"]["blocking"] is True
    assert checklist["orchestrator-timeout-chain-local-proof-recorded"]["blocking"] is True
    assert checklist["live-auth-tooling-backend-proof-recorded"]["blocking"] is True
    assert checklist["live-orchestrator-timeout-chain-proof-recorded"]["blocking"] is True
    assert checklist["live-knowledge-rag-connector-rerun-recorded"]["blocking"] is True
    assert checklist["qa-reporting-consistent"]["blocking"] is True
    assert checklist["live-marketing-minio-artifact-proof-recorded"]["blocking"] is False
    assert checklist["live-marketing-minio-artifact-proof-recorded"]["passed"] is False
    assert report["focusAreas"]["recordedRuntimeEvidence"]["failed"] == 0
    assert report["focusAreas"]["qaReporting"]["failed"] == 0


def test_infra_persistence_matrix_tracks_current_runtime_backend_capabilities() -> None:
    report = build_infra_persistence_report()

    assert report["summary"]["failed"] == 0
    services = report["services"]
    assert set(REQUIRED_INFRA_PERSISTENCE_SERVICES) <= set(services)
    assert services["knowledge-service"]["desiredBackends"] == [
        "mysql",
        "redis",
        "minio",
        "qdrant",
        "opensearch",
    ]
    assert services["orchestrator-service"]["desiredBackends"] == ["mysql", "redis"]
    assert services["tool-hub-service"]["desiredBackends"] == ["mysql", "redis"]
    assert services["business-tools-service"]["desiredBackends"] == ["redis"]
    assert all(services[service_name]["status"] == "pass" for service_name in REQUIRED_INFRA_PERSISTENCE_SERVICES)

    checks_by_name = {str(item["name"]): item for item in report["checks"]}
    missing = [name for name in REQUIRED_INFRA_PERSISTENCE_CHECKS if name not in checks_by_name]
    assert not missing, f"missing runtime backend capability checks: {missing}"
    failing = [
        name
        for name in REQUIRED_INFRA_PERSISTENCE_CHECKS
        if checks_by_name[name]["passed"] is not True
    ]
    assert not failing, f"runtime backend capability checks failed: {failing}"
