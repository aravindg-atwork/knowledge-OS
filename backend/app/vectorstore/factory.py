from functools import lru_cache

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.vectorstore.base import VectorStore
from app.vectorstore.qdrant_store import QdrantVectorStore


@lru_cache
def _build_vector_store(url: str, collection_name: str) -> VectorStore:
    return QdrantVectorStore(url=url, collection_name=collection_name)


def get_vector_store(settings: Settings = Depends(get_settings)) -> VectorStore:
    return _build_vector_store(settings.QDRANT_URL, settings.QDRANT_COLLECTION)
