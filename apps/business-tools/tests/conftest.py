from pathlib import Path
import sys

import pytest


SRC_PATH = Path(__file__).resolve().parents[1] / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from business_tools import (  # noqa: E402
    configure_idempotency_store,
    configure_query_cache,
    get_idempotency_store,
    get_query_cache_store,
)


@pytest.fixture(autouse=True)
def _reset_idempotency_store() -> None:
    configure_idempotency_store(persistence_path=None)
    configure_query_cache(enabled=True, ttl_cap_seconds=300, persistence_path=None)
    get_idempotency_store().clear()
    get_query_cache_store().clear()
