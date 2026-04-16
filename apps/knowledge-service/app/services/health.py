from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings
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
            "readinessChecks": checks,
            "warnings": warnings,
        }

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


@lru_cache(maxsize=1)
def get_health_service() -> KnowledgeHealthService:
    return KnowledgeHealthService()
