from pathlib import Path
import sys


BUSINESS_TOOLS_SRC = Path(__file__).resolve().parents[2] / "business-tools" / "src"
if str(BUSINESS_TOOLS_SRC) not in sys.path:
    sys.path.insert(0, str(BUSINESS_TOOLS_SRC))

from business_tools import (  # noqa: E402
    configure_idempotency_store,
    configure_query_cache,
    get_idempotency_store,
    get_query_cache_store,
)



def pytest_runtest_setup(item) -> None:  # pragma: no cover - pytest hook
    configure_idempotency_store(persistence_path=None)
    configure_query_cache(enabled=True, ttl_cap_seconds=300, persistence_path=None)
    get_idempotency_store().clear()
    get_query_cache_store().clear()
