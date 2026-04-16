#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_text(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def _missing_markers(file_markers: dict[str, tuple[str, ...]]) -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}
    for rel_path, markers in file_markers.items():
        content = _read_text(rel_path)
        absent = [marker for marker in markers if marker not in content]
        if absent:
            missing[rel_path] = absent
    return missing


def _check_capability(
    *,
    service: str,
    name: str,
    detail: str,
    file_markers: dict[str, tuple[str, ...]],
) -> dict[str, object]:
    missing = _missing_markers(file_markers)
    return {
        "service": service,
        "name": name,
        "passed": not missing,
        "detail": detail if not missing else f"{detail} missing markers: {missing}",
        "evidence": sorted(file_markers),
        "missingMarkers": missing,
    }


def _check_validation_gap(
    *,
    service: str,
    name: str,
    detail: str,
    file_markers: dict[str, tuple[str, ...]],
) -> dict[str, object]:
    missing = _missing_markers(file_markers)
    gap_still_present = not missing
    return {
        "service": service,
        "name": name,
        "passed": not gap_still_present,
        "detail": (
            detail
            if gap_still_present
            else "gap markers no longer match the repo; re-evaluate this validation gap"
        ),
        "evidence": sorted(file_markers),
        "missingMarkers": missing,
    }


def build_report() -> dict[str, object]:
    checks = [
        _check_capability(
            service="auth-user-service",
            name="auth-store-has-database-runtime-surface",
            detail=(
                "auth-user-service uses a SQLAlchemy-backed store with a configurable database runtime and JSON bootstrap fallback"
            ),
            file_markers={
                "apps/auth-user-service/app/core/config.py": (
                    "AUTH_USER_SERVICE_DATABASE_URL",
                    "SMARTCLOUD_MYSQL_DSN",
                ),
                "apps/auth-user-service/app/store.py": (
                    "create_engine",
                    "RefreshSessionRow",
                    "auth_refresh_sessions",
                ),
            },
        ),
        _check_capability(
            service="auth-user-service",
            name="auth-store-has-owned-restart-persistence-smoke",
            detail=(
                "the owned integration smoke proves refresh-session persistence survives auth-user-service restart via SQLite-backed storage"
            ),
            file_markers={
                "tests/integration/test_service_smoke.py": (
                    "test_auth_refresh_sessions_persist_in_sqlite_across_restart",
                    "auth_refresh_sessions",
                ),
            },
        ),
        _check_capability(
            service="auth-user-service",
            name="auth-db-runtime-keeps-bootstrap-json-static",
            detail=(
                "the owned auth restart smoke now also proves the legacy auth bootstrap JSON stays unchanged while refresh-session writes land in the configured database runtime"
            ),
            file_markers={
                "tests/integration/test_service_smoke.py": (
                    "test_auth_refresh_sessions_persist_in_sqlite_across_restart",
                    "apps/auth-user-service/data/auth-store.json",
                    "assert first_refresh_token not in bootstrap_path.read_text",
                ),
            },
        ),
        _check_capability(
            service="knowledge-service",
            name="knowledge-runtime-surfaces-real-connectors",
            detail=(
                "knowledge-service exposes MySQL, Redis, MinIO, Qdrant, and OpenSearch connector state through config and snapshot payloads"
            ),
            file_markers={
                "apps/knowledge-service/app/core/config.py": (
                    "SMARTCLOUD_MINIO_ENDPOINT",
                    "SMARTCLOUD_MYSQL_DSN",
                    "SMARTCLOUD_QDRANT_URL",
                    "SMARTCLOUD_OPENSEARCH_URL",
                    "SMARTCLOUD_REDIS_URL",
                ),
                "apps/knowledge-service/app/services/runtime_sync.py": (
                    'raw_storage_backend = "minio"',
                    'backend="mysql" if self.settings.mysql_dsn else "json-runtime-store"',
                    'backend="qdrant" if self.settings.qdrant_url else "planner-only"',
                    'backend="opensearch" if self.settings.opensearch_url else "keyword-baseline"',
                    'backend=cache_backend',
                    'backend=queue_backend',
                ),
                "apps/knowledge-service/app/services/metadata_backend.py": (
                    "MySQLKnowledgeMetadataBackend",
                    "knowledge_runtime_kb_profiles",
                    "knowledge_runtime_document_profiles",
                    "knowledge_runtime_admin_jobs",
                ),
                "tests/integration/test_service_smoke.py": (
                    "test_knowledge_snapshot_surfaces_real_connector_targets_when_env_is_configured",
                ),
            },
        ),
        _check_capability(
            service="knowledge-service",
            name="knowledge-owned-restart-smoke-preserves-snapshot-and-outbox-state",
            detail=(
                "the owned integration smoke proves knowledge snapshot counts plus queued outbox events survive knowledge-service restart while keeping MySQL/Redis/MinIO/Qdrant/OpenSearch connector targets visible"
            ),
            file_markers={
                "tests/integration/test_service_smoke.py": (
                    "test_knowledge_snapshot_and_outbox_state_persist_across_restart",
                    'first_import_event["rawObject"]["storageKind"] == "minio"',
                    'second_snapshot_data["integrations"]["pendingEvents"] >= 1',
                    'second_snapshot_data["integrations"]["metadataStore"]["backend"] == "mysql"',
                ),
            },
        ),
        _check_capability(
            service="knowledge-service",
            name="knowledge-compose-smoke-proves-connector-landing-path",
            detail=(
                "the compose smoke validates configured knowledge connector status plus completed connector results"
            ),
            file_markers={
                "deploy/docker-compose/docker-compose.yml": (
                    "SMARTCLOUD_MINIO_ENDPOINT",
                    "SMARTCLOUD_MYSQL_DSN",
                    "SMARTCLOUD_QDRANT_URL",
                    "SMARTCLOUD_OPENSEARCH_URL",
                    "SMARTCLOUD_REDIS_URL",
                ),
                "deploy/docker-compose/smoke-test.py": (
                    '"rawStorage"',
                    '"metadataStore"',
                    '"vectorStore"',
                    '"bm25Store"',
                    '"cache"',
                    '"taskQueue"',
                    "connectorResults",
                ),
            },
        ),
        _check_capability(
            service="knowledge-service",
            name="knowledge-rag-subprocess-smoke-revalidates-search-and-diagnostics-after-restart",
            detail=(
                "the owned subprocess smoke now restarts knowledge-service and rag-service, then revalidates snapshot/search/admin diagnostics so knowledge/rag persistence is exercised beyond first-pass ingestion"
            ),
            file_markers={
                "scripts/qa/project_smoke.py": (
                    "admin document detail after restart",
                    "knowledge search after restart",
                    "rag diagnose after restart",
                    "knowledge snapshot after restart",
                    '"snapshotEventRetainedAfterRestart": True',
                ),
            },
        ),
        _check_capability(
            service="rag-service",
            name="rag-runtime-keeps-redis-cache-and-knowledge-upstream-surfaces",
            detail=(
                "rag-service keeps a Redis cache surface and compose-backed upstream readiness proof"
            ),
            file_markers={
                "apps/rag-service/app/core/config.py": (
                    "KNOWLEDGE_SERVICE_BASE_URL",
                    "SMARTCLOUD_REDIS_URL",
                    "SMARTCLOUD_RAG_CACHE_NAMESPACE",
                ),
                "deploy/docker-compose/smoke-test.py": (
                    "rag_readiness_state 1.0",
                    "rag_upstream_ready_state 1.0",
                ),
            },
        ),
        _check_capability(
            service="marketing-service",
            name="marketing-runtime-surface-is-db-backed-with-optional-minio-artifacts",
            detail=(
                "marketing-service uses a SQLAlchemy-backed task store plus an optional MinIO poster artifact writer; Redis currently appears only as a declared config key, not an active runtime persistence path"
            ),
            file_markers={
                "apps/marketing-service/app/core/config.py": (
                    "MARKETING_SERVICE_DATABASE_URL",
                    "SMARTCLOUD_MYSQL_DSN",
                    "SMARTCLOUD_REDIS_URL",
                    "SMARTCLOUD_MINIO_ENDPOINT",
                ),
                "apps/marketing-service/app/store.py": (
                    "create_engine",
                    "PosterArtifactStorage",
                    "put_object",
                ),
            },
        ),
        _check_capability(
            service="marketing-service",
            name="marketing-owned-sqlite-restart-smoke-proves-db-persistence",
            detail=(
                "the owned integration smoke now proves poster tasks and idempotency records survive marketing-service restart via SQLite-backed runtime storage"
            ),
            file_markers={
                "tests/integration/test_service_smoke.py": (
                    "test_marketing_poster_tasks_persist_in_sqlite_across_restart",
                    "marketing_poster_tasks",
                    "marketing_poster_idempotency_records",
                ),
            },
        ),
        _check_capability(
            service="marketing-service",
            name="marketing-db-runtime-keeps-bootstrap-json-static",
            detail=(
                "the owned marketing restart smoke now also proves the legacy bootstrap JSON remains unchanged while poster task writes land in the configured database runtime"
            ),
            file_markers={
                "tests/integration/test_service_smoke.py": (
                    "test_marketing_poster_tasks_persist_in_sqlite_across_restart",
                    "apps/marketing-service/data/marketing-store.json",
                    "assert task_id not in bootstrap_path.read_text",
                ),
            },
        ),
        _check_capability(
            service="marketing-service",
            name="marketing-live-shared-backend-acceptance-path-is-available",
            detail=(
                "owned QA can now run marketing against shared MySQL and MinIO through SMARTCLOUD_QA_USE_LIVE_INFRA in project_smoke"
            ),
            file_markers={
                "scripts/qa/project_smoke.py": (
                    "SMARTCLOUD_QA_USE_LIVE_INFRA",
                    '"MARKETING_SERVICE_DATABASE_URL": (',
                    '"marketingPosterObjectStored"',
                ),
                "scripts/qa/qa_env.sh": (
                    "SMARTCLOUD_QA_SHARED_MYSQL_DSN",
                    "SMARTCLOUD_QA_SHARED_MINIO_ENDPOINT",
                ),
            },
        ),
        _check_capability(
            service="research-service",
            name="research-runtime-surface-is-db-backed-with-config-only-redis-key",
            detail=(
                "research-service uses a SQLAlchemy-backed task store; Redis currently appears only as a declared config key and is not part of the active runtime persistence path"
            ),
            file_markers={
                "apps/research-service/app/core/config.py": (
                    "RESEARCH_SERVICE_DATABASE_URL",
                    "SMARTCLOUD_MYSQL_DSN",
                    "SMARTCLOUD_REDIS_URL",
                ),
                "apps/research-service/app/store.py": (
                    "create_engine",
                    "sessionmaker",
                    "ResearchTaskRow",
                ),
            },
        ),
        _check_capability(
            service="research-service",
            name="research-owned-sqlite-restart-smoke-proves-db-persistence",
            detail=(
                "the owned integration smoke now proves research tasks and idempotency records survive research-service restart via SQLite-backed runtime storage"
            ),
            file_markers={
                "tests/integration/test_service_smoke.py": (
                    "test_research_tasks_persist_in_sqlite_across_restart",
                    "research_tasks",
                    "research_idempotency_records",
                ),
            },
        ),
        _check_capability(
            service="research-service",
            name="research-db-runtime-keeps-bootstrap-json-static",
            detail=(
                "the owned research restart smoke now also proves the legacy bootstrap JSON remains unchanged while task writes land in the configured database runtime"
            ),
            file_markers={
                "tests/integration/test_service_smoke.py": (
                    "test_research_tasks_persist_in_sqlite_across_restart",
                    "apps/research-service/data/research-store.json",
                    "assert task_id not in bootstrap_path.read_text",
                ),
            },
        ),
        _check_capability(
            service="research-service",
            name="research-live-shared-backend-acceptance-path-is-available",
            detail=(
                "owned QA can now run research against shared MySQL through SMARTCLOUD_QA_USE_LIVE_INFRA in project_smoke"
            ),
            file_markers={
                "scripts/qa/project_smoke.py": (
                    "SMARTCLOUD_QA_USE_LIVE_INFRA",
                    '"RESEARCH_SERVICE_DATABASE_URL": (',
                    '"researchIdempotencyStored"',
                ),
                "scripts/qa/qa_env.sh": (
                    "SMARTCLOUD_QA_SHARED_MYSQL_DSN",
                ),
            },
        ),
        _check_capability(
            service="orchestrator-service",
            name="orchestrator-runtime-surface-is-mysql-redis-capable",
            detail=(
                "orchestrator-service now exposes MySQL and Redis runtime settings for conversations, state, agent config, and SSE replay"
            ),
            file_markers={
                "apps/orchestrator-service/app/core/config.py": (
                    "SMARTCLOUD_MYSQL_DSN",
                    "SMARTCLOUD_REDIS_URL",
                    "ORCHESTRATOR_REDIS_NAMESPACE",
                ),
                "apps/orchestrator-service/app/services/runtime_mysql.py": (
                    "normalize_mysql_dsn",
                    "connect",
                    "create_index_if_missing",
                ),
                "apps/orchestrator-service/app/services/runtime_redis.py": (
                    "normalize_namespace",
                    "build_redis_client",
                ),
                "apps/orchestrator-service/app/services/conversation_store.py": (
                    "_MySQLConversationBackend",
                    '"backend": "mysql"',
                ),
                "apps/orchestrator-service/app/services/state_store.py": (
                    "_MySQLStateStoreBackend",
                    '"backend": "mysql"',
                ),
                "apps/orchestrator-service/app/services/sse_event_store.py": (
                    "redis-list",
                    "redisConfigured",
                ),
            },
        ),
        _check_capability(
            service="orchestrator-service",
            name="orchestrator-owned-health-smoke-surfaces-degraded-backend-truth",
            detail=(
                "the owned orchestrator smoke verifies healthz reports configured MySQL/Redis intent plus degraded JSON or memory fallbacks, while business-tools cache/idempotency surfaces stay inactive until transport-backed execution needs them"
            ),
            file_markers={
                "tests/integration/test_service_smoke.py": (
                    "test_orchestrator_healthz_reports_degraded_fallbacks_when_shared_backends_are_unreachable",
                    'runtime["conversationStore"]["degradedFrom"] == "mysql"',
                    'runtime["conversationStore"]["runtimeCache"]["redisNamespace"] == "qa:orchestrator:conversation"',
                    'runtime["stateStore"]["runtimeCache"]["redisNamespace"] == "qa:orchestrator:state"',
                    'runtime["sseStore"]["redisNamespace"] == "qa:orchestrator:sse"',
                    'runtime["runControl"]["degradedFrom"] == "redis-lock"',
                    'runtime["runControl"]["redisNamespace"] == "qa:orchestrator:run-control"',
                    'runtime["businessToolsQueryCache"]["activationMode"] == "degraded-fallback-only"',
                    'runtime["businessToolsQueryCache"]["redisNamespace"]',
                    'qa:orchestrator-business-tools:query-cache',
                    'runtime["businessToolsIdempotency"]["activationMode"] == "degraded-fallback-only"',
                    'runtime["businessToolsIdempotency"]["redisNamespace"]',
                    'qa:orchestrator-business-tools:idempotency',
                ),
            },
        ),
        _check_capability(
            service="orchestrator-service",
            name="orchestrator-live-mysql-redis-acceptance-path-is-available",
            detail=(
                "owned QA can now run orchestrator against shared MySQL and Redis through SMARTCLOUD_QA_USE_LIVE_INFRA in project_smoke"
            ),
            file_markers={
                "scripts/qa/project_smoke.py": (
                    "SMARTCLOUD_QA_USE_LIVE_INFRA",
                    '"backend": "mysql-and-redis"',
                    '"conversationStored"',
                    '"sseRedisKeys"',
                ),
                "scripts/qa/qa_env.sh": (
                    "SMARTCLOUD_QA_SHARED_MYSQL_DSN",
                    "SMARTCLOUD_QA_SHARED_REDIS_URL",
                ),
            },
        ),
        _check_capability(
            service="orchestrator-service",
            name="orchestrator-timeout-chain-acceptance-keeps-tool-hub-audit-proof",
            detail=(
                "the owned subprocess smoke now drives a real orchestrator -> tool-hub -> business-tools timeout chain and keeps timeout tool-call plus audit evidence visible, including MySQL landing when live shared backends are enabled"
            ),
            file_markers={
                "scripts/qa/project_smoke.py": (
                    "exercise_orchestrator_timeout_chain",
                    '"timeoutChain"',
                    '"toolHubAuditStatus"',
                    '"timeoutAuditStored"',
                    "start_business_tools_timeout_probe",
                ),
            },
        ),
        _check_capability(
            service="tool-hub-service",
            name="tool-hub-runtime-surface-is-mysql-redis-capable",
            detail=(
                "tool-hub-service now exposes MySQL and Redis runtime settings for audits and cache/idempotency behavior"
            ),
            file_markers={
                "apps/tool-hub-service/app/core/config.py": (
                    "SMARTCLOUD_MYSQL_DSN",
                    "SMARTCLOUD_REDIS_URL",
                    "TOOL_HUB_REDIS_NAMESPACE",
                ),
                "apps/tool-hub-service/app/services/runtime_mysql.py": (
                    "normalize_mysql_dsn",
                    "connect",
                    "create_index_if_missing",
                ),
                "apps/tool-hub-service/app/services/audit_store.py": (
                    "_MySQLAuditStoreBackend",
                    '"backend": "mysql"',
                ),
            },
        ),
        _check_capability(
            service="tool-hub-service",
            name="tool-hub-owned-health-smoke-surfaces-degraded-backend-truth",
            detail=(
                "the owned tool-hub smoke verifies healthz reports configured MySQL intent plus degraded JSON fallbacks, while business-tools cache/idempotency surfaces stay inactive until transport-backed execution needs them"
            ),
            file_markers={
                "tests/integration/test_service_smoke.py": (
                    "test_tool_hub_healthz_reports_degraded_fallbacks_when_shared_backends_are_unreachable",
                    'runtime["auditStore"]["degradedFrom"] == "mysql"',
                    'runtime["businessToolsIdempotency"]["activationMode"] == "degraded-fallback-only"',
                    'runtime["businessToolsIdempotency"]["redisNamespace"]',
                    'qa:tool-hub-business-tools:idempotency',
                    'runtime["businessToolsQueryCache"]["activationMode"] == "degraded-fallback-only"',
                    'runtime["businessToolsQueryCache"]["redisNamespace"]',
                    'qa:tool-hub-business-tools:query-cache',
                ),
            },
        ),
        _check_capability(
            service="tool-hub-service",
            name="tool-hub-live-mysql-redis-acceptance-path-is-available",
            detail=(
                "owned QA can now run tool-hub against shared MySQL and Redis through SMARTCLOUD_QA_USE_LIVE_INFRA in project_smoke"
            ),
            file_markers={
                "scripts/qa/project_smoke.py": (
                    "SMARTCLOUD_QA_USE_LIVE_INFRA",
                    '"toolHubAuditStored"',
                    '"toolHubQueryCacheKeys"',
                    '"toolHubIdempotencyKeys"',
                ),
                "scripts/qa/qa_env.sh": (
                    "SMARTCLOUD_QA_SHARED_MYSQL_DSN",
                    "SMARTCLOUD_QA_SHARED_REDIS_URL",
                ),
            },
        ),
        _check_capability(
            service="business-tools-service",
            name="business-tools-runtime-surface-is-redis-first-capable",
            detail=(
                "business-tools now exposes Redis-first idempotency/query-cache persistence with local fallback"
            ),
            file_markers={
                "apps/business-tools/src/business_tools_service/core/config.py": (
                    "SMARTCLOUD_REDIS_URL",
                    "BUSINESS_TOOLS_REDIS_NAMESPACE",
                ),
                "apps/business-tools/src/business_tools/runtime_backend.py": (
                    "normalize_namespace",
                    "build_redis_client",
                    "clear_namespace",
                ),
                "apps/business-tools/src/business_tools/idempotency.py": (
                    "Redis-first runtime persistence and local fallback",
                    '"backend": "redis"',
                ),
                "apps/business-tools/src/business_tools/query_cache.py": (
                    "Redis-first runtime persistence and local fallback",
                    '"backend": "redis-ttl"',
                ),
            },
        ),
        _check_capability(
            service="business-tools-service",
            name="business-tools-owned-health-smoke-surfaces-degraded-backend-truth",
            detail=(
                "the owned business-tools smoke verifies healthz reports configured Redis intent plus degraded JSON fallbacks when Redis is unreachable in local QA"
            ),
            file_markers={
                "tests/integration/test_service_smoke.py": (
                    "test_business_tools_healthz_reports_degraded_fallbacks_when_redis_is_unreachable",
                    'runtime["idempotency"]["degradedFrom"] == "redis"',
                    'runtime["idempotency"]["redisNamespace"] == "qa:business-tools:idempotency"',
                    'runtime["queryCache"]["degradedFrom"] == "redis-ttl"',
                    'runtime["queryCache"]["redisNamespace"] == "qa:business-tools:query-cache"',
                ),
            },
        ),
        _check_capability(
            service="business-tools-service",
            name="business-tools-live-redis-acceptance-path-is-available",
            detail=(
                "owned QA can now run business-tools against shared Redis through SMARTCLOUD_QA_USE_LIVE_INFRA in project_smoke"
            ),
            file_markers={
                "scripts/qa/project_smoke.py": (
                    "SMARTCLOUD_QA_USE_LIVE_INFRA",
                    '"businessToolsQueryCacheKeys"',
                    '"businessToolsIdempotencyKeys"',
                ),
                "scripts/qa/qa_env.sh": (
                    "SMARTCLOUD_QA_SHARED_REDIS_URL",
                ),
            },
        ),
    ]

    service_modes = {
        "auth-user-service": {
            "mode": "database-backed-auth-store",
            "desiredBackends": ["sqlite-or-mysql"],
            "qaEntrypoints": [
                "tests/integration/test_service_smoke.py",
                "scripts/qa/project_smoke.py",
            ],
        },
        "knowledge-service": {
            "mode": "connector-aware-runtime-store",
            "desiredBackends": ["mysql", "redis", "minio", "qdrant", "opensearch"],
            "qaEntrypoints": [
                "tests/integration/test_service_smoke.py",
                "deploy/docker-compose/smoke-test.py",
            ],
        },
        "rag-service": {
            "mode": "knowledge-upstream-plus-redis-cache",
            "desiredBackends": ["knowledge-service", "redis-optional"],
            "qaEntrypoints": [
                "tests/integration/test_service_smoke.py",
                "deploy/docker-compose/smoke-test.py",
            ],
        },
        "marketing-service": {
            "mode": "database-backed-tasks-plus-optional-minio-artifacts",
            "desiredBackends": ["mysql", "minio-optional", "redis-config-only"],
            "qaEntrypoints": [
                "tests/integration/test_service_smoke.py",
                "scripts/qa/project_smoke.py",
                "scripts/qa/infra_persistence_matrix.py",
            ],
        },
        "research-service": {
            "mode": "database-backed-tasks-with-config-only-redis-key",
            "desiredBackends": ["mysql", "redis-config-only"],
            "qaEntrypoints": [
                "tests/integration/test_service_smoke.py",
                "scripts/qa/project_smoke.py",
                "scripts/qa/infra_persistence_matrix.py",
            ],
        },
        "orchestrator-service": {
            "mode": "mysql-plus-redis-capable",
            "desiredBackends": ["mysql", "redis"],
            "qaEntrypoints": [
                "tests/integration/test_service_smoke.py",
                "scripts/qa/project_smoke.py",
                "scripts/qa/infra_persistence_matrix.py",
            ],
        },
        "tool-hub-service": {
            "mode": "mysql-plus-redis-capable",
            "desiredBackends": ["mysql", "redis"],
            "qaEntrypoints": [
                "tests/integration/test_service_smoke.py",
                "scripts/qa/project_smoke.py",
                "scripts/qa/infra_persistence_matrix.py",
            ],
        },
        "business-tools-service": {
            "mode": "redis-first-capable",
            "desiredBackends": ["redis"],
            "qaEntrypoints": [
                "tests/integration/test_service_smoke.py",
                "scripts/qa/project_smoke.py",
                "scripts/qa/infra_persistence_matrix.py",
            ],
        },
    }

    services: dict[str, dict[str, object]] = {}
    for service, metadata in service_modes.items():
        service_checks = [item for item in checks if item["service"] == service]
        failing = [item["name"] for item in service_checks if not item["passed"]]
        services[service] = {
            **metadata,
            "status": "pass" if not failing else "gap",
            "passedChecks": len(service_checks) - len(failing),
            "failedChecks": len(failing),
            "failingCheckNames": failing,
        }

    failing_services = sorted(service for service, info in services.items() if info["status"] == "gap")
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "owner": "supervisor-integration-qa",
        "workspace": str(REPO_ROOT),
        "summary": {
            "passed": sum(1 for item in checks if item["passed"]),
            "failed": sum(1 for item in checks if not item["passed"]),
            "total": len(checks),
            "failingServices": failing_services,
        },
        "services": services,
        "checks": checks,
    }


def main() -> int:
    print(json.dumps(build_report(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
