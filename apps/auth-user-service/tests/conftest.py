import importlib
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


SERVICE_ROOT = Path(__file__).resolve().parents[1]
TEST_DATA_ROOT = Path(tempfile.mkdtemp(prefix="smartcloud-auth-tests-"))
os.environ["AUTH_USER_SERVICE_DATABASE_URL"] = f"sqlite:///{(TEST_DATA_ROOT / 'auth-user-service.db').as_posix()}"


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
    store = importlib.import_module("app.store")
    main = importlib.import_module("app.main")

    config.get_settings.cache_clear()
    security.get_token_codec.cache_clear()
    store.get_auth_store.cache_clear()
    store.get_auth_store().clear()
    return {
        "config": config,
        "security": security,
        "store": store,
        "main": main,
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


@pytest.fixture
def settings(service_modules: dict[str, Any]):
    return service_modules["config"].get_settings()


@pytest.fixture
def auth_store(service_modules: dict[str, Any]):
    return service_modules["store"].get_auth_store()
