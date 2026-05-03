import importlib
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


SERVICE_ROOT = Path(__file__).resolve().parents[1]
TEST_DATA_ROOT = Path(tempfile.mkdtemp(prefix="smartcloud-marketing-tests-"))
os.environ["MARKETING_SERVICE_DATABASE_URL"] = f"sqlite:///{(TEST_DATA_ROOT / 'marketing-service.db').as_posix()}"


def activate_service_imports() -> None:
    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            sys.modules.pop(module_name, None)
    service_root = str(SERVICE_ROOT)
    if service_root in sys.path:
        sys.path.remove(service_root)
    sys.path.insert(0, service_root)


activate_service_imports()


def _load_service_modules() -> dict[str, Any]:
    activate_service_imports()
    config = importlib.import_module("app.core.config")
    security = importlib.import_module("app.security")
    dependencies = importlib.import_module("app.dependencies")
    models = importlib.import_module("app.models")
    telemetry = importlib.import_module("app.core.telemetry")
    metrics = importlib.import_module("app.core.metrics")
    store = importlib.import_module("app.store")
    copy_generator = importlib.import_module("app.services.copy_generator")
    poster_generator = importlib.import_module("app.services.poster_generator")
    mongo_runtime = importlib.import_module("app.mongo_runtime")
    celery_app = importlib.import_module("app.celery_app")
    tasks = importlib.import_module("app.tasks")
    routes = importlib.import_module("app.routes")
    main = importlib.import_module("app.main")

    config.get_settings.cache_clear()
    security.get_token_codec.cache_clear()

    modules_to_reload = [
        telemetry,
        metrics,
        copy_generator,
        poster_generator,
        store,
        mongo_runtime,
        celery_app,
        tasks,
        dependencies,
        routes,
        main,
    ]
    reloaded = {module.__name__: importlib.reload(module) for module in modules_to_reload}

    reloaded_store = reloaded["app.store"]
    reloaded_store.get_marketing_store.cache_clear()
    reloaded_store.get_marketing_store().clear()
    reloaded_telemetry = reloaded["app.core.telemetry"]
    if hasattr(reloaded_telemetry, "reset_tracing"):
        reloaded_telemetry.reset_tracing()
    reloaded_metrics = reloaded["app.core.metrics"]
    if hasattr(reloaded_metrics, "reset_metrics"):
        reloaded_metrics.reset_metrics()
    importlib.reload(reloaded["app.routes"])
    importlib.reload(reloaded["app.main"])
    return {
        "config": config,
        "security": security,
        "dependencies": reloaded["app.dependencies"],
        "models": models,
        "store": reloaded_store,
        "telemetry": reloaded_telemetry,
        "metrics": reloaded_metrics,
        "copy_generator": reloaded["app.services.copy_generator"],
        "poster_generator": reloaded["app.services.poster_generator"],
        "mongo_runtime": reloaded["app.mongo_runtime"],
        "celery_app": reloaded["app.celery_app"],
        "tasks": reloaded["app.tasks"],
        "routes": importlib.import_module("app.routes"),
        "main": importlib.import_module("app.main"),
    }


@pytest.fixture
def service_modules() -> dict[str, Any]:
    return _load_service_modules()


@pytest.fixture
def client(service_modules: dict[str, Any]) -> TestClient:
    return TestClient(service_modules["main"].app)


@pytest.fixture
def token_codec(service_modules: dict[str, Any]):
    return service_modules["security"].get_token_codec()
