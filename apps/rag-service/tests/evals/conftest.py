import sys
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]


def activate_service_imports() -> None:
    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            sys.modules.pop(module_name, None)

    service_root = str(SERVICE_ROOT)
    if service_root in sys.path:
        sys.path.remove(service_root)
    sys.path.insert(0, service_root)


activate_service_imports()
