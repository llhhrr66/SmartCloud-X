from functools import lru_cache

from app.core.config import get_settings
from app.services.store import KnowledgeStoreRepository


@lru_cache(maxsize=1)
def get_repository() -> KnowledgeStoreRepository:
    settings = get_settings()
    return KnowledgeStoreRepository(settings.data_path)
