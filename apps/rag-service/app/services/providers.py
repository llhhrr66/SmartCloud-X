from functools import lru_cache

from app.services.knowledge_client import KnowledgeServiceClient


@lru_cache(maxsize=1)
def get_knowledge_client() -> KnowledgeServiceClient:
    return KnowledgeServiceClient()
