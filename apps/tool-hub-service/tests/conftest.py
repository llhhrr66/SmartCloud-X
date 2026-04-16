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
from app.core.business_tools_sdk import reset_local_runtime_state  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.api.routes.tools import _audit_store  # noqa: E402
def _remove_degraded_spool(path_value: str | None) -> None:
    if not path_value:
        return
    path = Path(path_value)
    if path.exists():
        path.unlink()


def pytest_runtest_setup(item) -> None:  # pragma: no cover - pytest hook
    settings = get_settings()
    configure_idempotency_store(
        persistence_path=settings.business_tools_idempotency_store_path,
        redis_url=settings.redis_url,
        redis_namespace=f"{settings.business_tools_redis_namespace}:idempotency",
    )
    configure_query_cache(
        enabled=settings.tool_query_cache_enabled,
        ttl_cap_seconds=settings.tool_query_cache_ttl_cap_seconds,
        persistence_path=settings.business_tools_query_cache_store_path,
        redis_url=settings.redis_url,
        redis_namespace=f"{settings.business_tools_redis_namespace}:query-cache",
    )
    get_idempotency_store().clear()
    get_query_cache_store().clear()
    _remove_degraded_spool(settings.business_tools_idempotency_store_path)
    _remove_degraded_spool(settings.business_tools_query_cache_store_path)
    configure_idempotency_store(persistence_path=None)
    configure_query_cache(enabled=True, ttl_cap_seconds=300, persistence_path=None)
    reset_local_runtime_state()
    _audit_store.clear()
