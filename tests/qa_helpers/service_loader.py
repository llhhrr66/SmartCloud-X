from __future__ import annotations

import importlib
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parents[2]

SERVICE_ROOTS = {
    "auth-user-service": REPO_ROOT / "apps" / "auth-user-service",
    "marketing-service": REPO_ROOT / "apps" / "marketing-service",
    "research-service": REPO_ROOT / "apps" / "research-service",
    "orchestrator-service": REPO_ROOT / "apps" / "orchestrator-service",
    "tool-hub-service": REPO_ROOT / "apps" / "tool-hub-service",
    "knowledge-service": REPO_ROOT / "apps" / "knowledge-service",
    "rag-service": REPO_ROOT / "apps" / "rag-service",
}
BUSINESS_TOOLS_SRC = REPO_ROOT / "apps" / "business-tools" / "src"
PROMETHEUS_DEFAULT_PREFIXES = ("python_", "process_", "platform_")


def _clear_modules() -> None:
    prefixes = ("app", "business_tools", "business_tools_service")
    for module_name in list(sys.modules):
        if module_name in prefixes or module_name.startswith(tuple(f"{prefix}." for prefix in prefixes)):
            sys.modules.pop(module_name, None)


def _reset_prometheus_registry() -> None:
    try:
        from prometheus_client import REGISTRY
    except ModuleNotFoundError:
        return

    collector_to_names = getattr(REGISTRY, "_collector_to_names", {})
    for collector, names in list(collector_to_names.items()):
        if any(str(name).startswith(PROMETHEUS_DEFAULT_PREFIXES) for name in names):
            continue
        try:
            REGISTRY.unregister(collector)
        except KeyError:
            continue


@contextmanager
def _patched_environ(overrides: dict[str, str]) -> Iterator[None]:
    original = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            os.environ[key] = value
        yield
    finally:
        for key, original_value in original.items():
            if original_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original_value


@contextmanager
def service_test_client(
    service_name: str,
    *,
    env_overrides: dict[str, str] | None = None,
) -> Iterator[TestClient]:
    original_sys_path = list(sys.path)
    root = SERVICE_ROOTS[service_name]
    additions = [str(root)]
    if service_name in {"orchestrator-service", "tool-hub-service"}:
        additions.append(str(BUSINESS_TOOLS_SRC))

    _clear_modules()
    _reset_prometheus_registry()
    sys.path[:] = [*additions, *[path for path in sys.path if path not in additions]]

    try:
        with _patched_environ(env_overrides or {}):
            module = importlib.import_module("app.main")
            app = getattr(module, "app")
            with TestClient(app) as client:
                yield client
    finally:
        _clear_modules()
        _reset_prometheus_registry()
        sys.path[:] = original_sys_path


def assert_standard_headers(headers: dict[str, str] | Any) -> None:
    for header in ("X-Request-Id", "X-Trace-Id", "X-App-Name", "X-Response-Time"):
        assert headers.get(header), f"missing expected header {header}"
