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
from app.api.routes.orchestration import (  # noqa: E402
    _agent_config_store,
    _conversation_store,
    _run_control,
    _sse_event_store,
    _state_store,
)



def pytest_runtest_setup(item) -> None:  # pragma: no cover - pytest hook
    configure_idempotency_store(persistence_path=None)
    configure_query_cache(enabled=True, ttl_cap_seconds=300, persistence_path=None)
    get_idempotency_store().clear()
    get_query_cache_store().clear()
    _conversation_store.clear()
    _state_store.clear()
    _sse_event_store.clear()
    _run_control.clear()
    _agent_config_store.clear()
