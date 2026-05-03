from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.dify_dataset_sync import get_dify_dataset_sync_service
from app.services.dify_external import get_dify_external_knowledge_service
from app.services.index_targets import KnowledgeIndexTargetResolver
from app.services.runtime_sync import get_runtime_sync_service
from app.services.store_provider import get_repository


class KnowledgeHealthService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def build_payload(self) -> dict[str, object]:
        checks: list[dict[str, str]] = []
        warnings: list[str] = []
        counts: dict[str, int] = {}

        data_path = self.settings.data_path.expanduser()
        audit_path = self.settings.audit_path.expanduser()
        starter_catalog_path = self.settings.starter_catalog_path.expanduser()
        import_root = self.settings.import_root.expanduser()

        store_ready, store_detail = self._repository_access_status()
        checks.append(self._check("data_store_access", store_ready, store_detail))
        if not store_ready:
            warnings.append(store_detail)

        audit_ready, audit_detail = self._writable_parent_status(audit_path)
        checks.append(self._check("audit_log_parent", audit_ready, audit_detail))
        if not audit_ready:
            warnings.append(audit_detail)

        starter_ready, starter_detail = self._existing_file_status(starter_catalog_path)
        checks.append(self._check("starter_catalog", starter_ready, starter_detail))
        if not starter_ready:
            warnings.append(starter_detail)

        import_root_ready, import_root_detail = self._existing_directory_status(import_root)
        checks.append(self._check("import_root", import_root_ready, import_root_detail))
        if not import_root_ready:
            warnings.append(import_root_detail)

        if store_ready:
            try:
                counts = get_repository().snapshot_counts()
            except Exception as exc:  # noqa: BLE001 - health payload should degrade, not crash
                warning = f"failed to read repository counts: {exc}"
                warnings.append(warning)
                checks.append(self._check("repository_counts", False, warning))
            else:
                checks.append(
                    self._check(
                        "repository_counts",
                        True,
                        (
                            f"sources={counts.get('sources', 0)}, "
                            f"documents={counts.get('documents', 0)}, "
                            f"chunks={counts.get('chunks', 0)}"
                        ),
                    )
                )

        ready = all(item["status"] == "ready" for item in checks)
        dify_external_status = get_dify_external_knowledge_service().build_status()
        dify_dataset_status = get_dify_dataset_sync_service().build_status()
        return {
            "status": "ok" if ready else "degraded",
            "ready": ready,
            "service": self.settings.app_name,
            "dataPath": str(data_path),
            "auditPath": str(audit_path),
            "starterCatalogPath": str(starter_catalog_path),
            "importRoot": str(import_root),
            "maxImportFiles": self.settings.max_import_files,
            "corsAllowedOrigins": self.settings.cors_allowed_origins,
            "counts": counts,
            "externalIntegrations": {
                "difyExternalKnowledge": dify_external_status,
                "difyDatasetSync": dify_dataset_status,
            },
            "readinessChecks": checks,
            "warnings": warnings,
        }

    def build_readiness_payload(self) -> tuple[int, dict[str, Any]]:
        """Build the knowledge-service readiness payload and matching HTTP status."""
        not_ready_components: list[str] = []
        runtime_mode = self._runtime_mode()
        runtime: dict[str, Any] = {}

        repository_probe = self._repository_readiness()
        runtime["repository"] = repository_probe
        if not repository_probe["ready"]:
            not_ready_components.append("repository")

        runtime_sync_probe = self._runtime_sync_readiness()
        runtime["runtimeSync"] = runtime_sync_probe
        if not runtime_sync_probe["ready"]:
            not_ready_components.append("runtimeSync")

        runtime_sync_integrations = runtime_sync_probe.get("integrations")
        if isinstance(runtime_sync_integrations, dict):
            runtime["backends"] = self._build_backend_records(runtime_sync_integrations)
            runtime["indexTargets"] = self._build_index_targets(runtime_sync_integrations)
            runtime["connectors"] = self._build_connector_evidence(runtime_sync_integrations)
            object_storage_probe = self._object_storage_readiness(runtime_sync_integrations)
            runtime["objectStorage"] = object_storage_probe
            if not object_storage_probe["ready"]:
                not_ready_components.append("objectStorage")
            for component_name, connector_key in (
                ("vectorStore", "vectorStore"),
                ("bm25Store", "bm25Store"),
            ):
                connector = runtime_sync_integrations.get(connector_key)
                connector_ready, error = self._connector_readiness(connector)
                runtime[component_name] = {
                    "ready": connector_ready,
                    "status": "ready" if connector_ready else "not_ready",
                    "mode": "runtime-sync",
                    "service": self.settings.app_name,
                    "notReadyComponents": [] if connector_ready else [component_name],
                    "error": error,
                }
                if not connector_ready and component_name not in not_ready_components:
                    not_ready_components.append(component_name)
        else:
            runtime["backends"] = {}
            runtime["indexTargets"] = {
                "active_mode": "single-baseline",
                "targets": {},
            }
            runtime["connectors"] = {}
            runtime["objectStorage"] = self._object_storage_unavailable_probe(
                "runtime sync integrations unavailable"
            )
            if "objectStorage" not in not_ready_components:
                not_ready_components.append("objectStorage")
            for component_name in ("vectorStore", "bm25Store"):
                runtime[component_name] = {
                    "ready": False,
                    "status": "not_ready",
                    "mode": "runtime-sync",
                    "service": self.settings.app_name,
                    "notReadyComponents": [component_name],
                    "error": "runtime sync integrations unavailable",
                }
                if component_name not in not_ready_components:
                    not_ready_components.append(component_name)

        payload = {
            "status": "ready" if not not_ready_components else "not_ready",
            "service": self.settings.app_name,
            "runtime_mode": runtime_mode,
            "not_ready_components": not_ready_components,
            "runtime": runtime,
        }
        return (200 if not not_ready_components else 503), payload

    @staticmethod
    def _check(name: str, ready: bool, detail: str) -> dict[str, str]:
        return {
            "name": name,
            "status": "ready" if ready else "failed",
            "detail": detail,
        }

    @staticmethod
    def _existing_file_status(path: Path) -> tuple[bool, str]:
        resolved = path.resolve()
        if not resolved.exists():
            return False, f"missing file: {resolved}"
        if not resolved.is_file():
            return False, f"expected a file but found a different path type: {resolved}"
        return True, f"available: {resolved}"

    @staticmethod
    def _existing_directory_status(path: Path) -> tuple[bool, str]:
        resolved = path.resolve()
        if not resolved.exists():
            return False, f"missing directory: {resolved}"
        if not resolved.is_dir():
            return False, f"expected a directory but found a different path type: {resolved}"
        if not os.access(resolved, os.R_OK):
            return False, f"directory is not readable: {resolved}"
        return True, f"readable directory: {resolved}"

    @staticmethod
    def _writable_parent_status(path: Path) -> tuple[bool, str]:
        resolved = path.resolve()
        parent = resolved.parent
        if not parent.exists():
            return False, f"missing parent directory: {parent}"
        if not parent.is_dir():
            return False, f"audit path parent is not a directory: {parent}"
        if not os.access(parent, os.W_OK):
            return False, f"parent directory is not writable: {parent}"
        return True, f"writable parent directory: {parent}"

    def _repository_access_status(self) -> tuple[bool, str]:
        try:
            repository = get_repository()
            repository.snapshot_counts()
        except Exception as exc:  # noqa: BLE001 - health payload should degrade, not crash
            return False, f"repository unavailable: {exc}"
        return True, f"repository loaded from {repository.path.resolve()}"

    def _repository_readiness(self) -> dict[str, Any]:
        try:
            repository = get_repository()
            counts = repository.snapshot_counts()
        except (OSError, RuntimeError, ValueError) as exc:
            return {
                "ready": False,
                "status": "not_ready",
                "mode": "repository",
                "service": self.settings.app_name,
                "notReadyComponents": ["repository"],
                "error": str(exc),
            }
        except Exception as exc:  # noqa: BLE001 - readiness should not raise 500
            return {
                "ready": False,
                "status": "not_ready",
                "mode": "repository",
                "service": self.settings.app_name,
                "notReadyComponents": ["repository"],
                "error": str(exc),
            }
        return {
            "ready": True,
            "status": "ready",
            "mode": "repository",
            "service": self.settings.app_name,
            "notReadyComponents": [],
            "path": str(repository.path.resolve()),
            "counts": counts,
        }

    def _runtime_sync_readiness(self) -> dict[str, Any]:
        try:
            integrations = get_runtime_sync_service().build_integrations().model_dump(
                mode="json",
                by_alias=True,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            return {
                "ready": False,
                "status": "not_ready",
                "mode": "runtime-sync",
                "service": self.settings.app_name,
                "notReadyComponents": ["runtimeSync"],
                "error": str(exc),
            }
        except Exception as exc:  # noqa: BLE001 - readiness should not raise 500
            return {
                "ready": False,
                "status": "not_ready",
                "mode": "runtime-sync",
                "service": self.settings.app_name,
                "notReadyComponents": ["runtimeSync"],
                "error": str(exc),
            }

        not_ready_components: list[str] = []
        for connector_name in ("metadataStore", "vectorStore", "bm25Store", "rawStorage", "taskQueue"):
            connector = integrations.get(connector_name)
            if not isinstance(connector, dict):
                not_ready_components.append(connector_name)
                continue
            configured = bool(connector.get("configured"))
            if connector_name in {"metadataStore", "taskQueue"}:
                continue
            if not configured:
                not_ready_components.append(connector_name)

        return {
            "ready": not not_ready_components,
            "status": "ready" if not not_ready_components else "not_ready",
            "mode": "runtime-sync",
            "service": self.settings.app_name,
            "notReadyComponents": not_ready_components,
            "integrations": integrations,
        }

    def _build_backend_records(self, integrations: dict[str, Any]) -> dict[str, Any]:
        records: dict[str, Any] = {}
        for source_key in (
            "rawStorage",
            "metadataStore",
            "vectorStore",
            "bm25Store",
            "difyExternalKnowledge",
            "difyDatasetSync",
            "cache",
            "taskQueue",
        ):
            connector = integrations.get(source_key)
            if isinstance(connector, dict):
                records[source_key] = connector
        return records

    def _build_index_targets(self, integrations: dict[str, Any]) -> dict[str, Any]:
        resolver = KnowledgeIndexTargetResolver()
        targets: dict[str, str] = {}
        baselines: dict[str, str] = {
            "vectorStore": resolver._baseline_qdrant_collection,
            "bm25Store": resolver._baseline_opensearch_index,
        }
        for connector_name in ("vectorStore", "bm25Store"):
            connector = integrations.get(connector_name)
            if isinstance(connector, dict) and isinstance(connector.get("target"), str):
                targets[connector_name] = connector["target"]
            else:
                targets[connector_name] = baselines[connector_name]
        unique_targets = {value for value in targets.values()}
        active_mode = "single-baseline" if len(unique_targets) <= 1 else "mixed"
        return {
            "active_mode": active_mode,
            "targets": targets,
            "fallback_targets": baselines,
        }

    def _build_connector_evidence(self, integrations: dict[str, Any]) -> dict[str, Any]:
        evidence: dict[str, Any] = {}
        for connector_name in ("vectorStore", "bm25Store", "rawStorage", "metadataStore"):
            connector = integrations.get(connector_name)
            if not isinstance(connector, dict):
                evidence[connector_name] = {
                    "ready": False,
                    "status": "not_ready",
                    "error": f"missing runtime connector payload: {connector_name}",
                }
                continue
            configured = bool(connector.get("configured"))
            notes = connector.get("notes") if isinstance(connector.get("notes"), list) else []
            error = None if configured else f"{connector_name} backend not configured"
            evidence[connector_name] = {
                "ready": configured,
                "status": "ready" if configured else "not_ready",
                "backend": connector.get("backend"),
                "endpoint": connector.get("endpoint"),
                "target": connector.get("target"),
                "notes": notes,
                "error": error,
            }
        return evidence

    def _object_storage_readiness(self, integrations: dict[str, Any]) -> dict[str, Any]:
        connector = integrations.get("rawStorage")
        if not isinstance(connector, dict):
            return self._object_storage_unavailable_probe("rawStorage connector payload unavailable")

        notes = connector.get("notes") if isinstance(connector.get("notes"), list) else []
        missing_fields: list[str] = []
        if not self.settings.minio_endpoint:
            missing_fields.append("SMARTCLOUD_MINIO_ENDPOINT")
        if not self.settings.minio_bucket:
            missing_fields.append("SMARTCLOUD_MINIO_BUCKET")
        if not self.settings.minio_access_key:
            missing_fields.append("SMARTCLOUD_MINIO_ACCESS_KEY")
        if not self.settings.minio_secret_key:
            missing_fields.append("SMARTCLOUD_MINIO_SECRET_KEY")

        if missing_fields:
            return {
                "ready": False,
                "status": "not_ready",
                "backend": connector.get("backend"),
                "endpoint": self.settings.minio_endpoint,
                "target": self.settings.minio_bucket or connector.get("target"),
                "configured": False,
                "notReadyComponents": ["objectStorage"],
                "missingConfig": missing_fields,
                "notes": notes,
                "error": f"object storage configuration incomplete: missing {', '.join(missing_fields)}",
            }

        return {
            "ready": True,
            "status": "ready",
            "backend": connector.get("backend"),
            "endpoint": self.settings.minio_endpoint,
            "target": self.settings.minio_bucket,
            "configured": True,
            "notReadyComponents": [],
            "missingConfig": [],
            "notes": notes,
        }

    def _object_storage_unavailable_probe(self, error: str) -> dict[str, Any]:
        return {
            "ready": False,
            "status": "not_ready",
            "backend": "unknown",
            "endpoint": self.settings.minio_endpoint,
            "target": self.settings.minio_bucket or str(self.settings.raw_mirror_root),
            "configured": False,
            "notReadyComponents": ["objectStorage"],
            "missingConfig": [],
            "notes": [],
            "error": error,
        }

    @staticmethod
    def _connector_readiness(connector: Any) -> tuple[bool, str | None]:
        if not isinstance(connector, dict):
            return False, "runtime connector payload missing"
        if connector.get("configured"):
            return True, None
        backend = connector.get("backend") or "unknown"
        return False, f"{backend} backend not configured"

    def _runtime_mode(self) -> str:
        if self.settings.mysql_dsn and self.settings.qdrant_url and self.settings.opensearch_url:
            return "shared-backend"
        if self.settings.mysql_dsn or self.settings.qdrant_url or self.settings.opensearch_url:
            return "mixed"
        return "local-fallback"


@lru_cache(maxsize=1)
def get_health_service() -> KnowledgeHealthService:
    return KnowledgeHealthService()
