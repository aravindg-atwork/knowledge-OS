import uuid

from app.ai.embeddings.base import EmbeddingProvider
from app.vectorstore.base import SearchResult, VectorStore


class RetrievalService:
    """Permission-filtered vector search. The workspace/role filter is baked
    into the Qdrant query itself (see build_permission_filter) -- callers
    never receive chunks they aren't allowed to see, regardless of how
    topically relevant those chunks are."""

    def __init__(self, embedding_provider: EmbeddingProvider, vector_store: VectorStore) -> None:
        self._embeddings = embedding_provider
        self._vector_store = vector_store

    def search(
        self,
        query_text: str,
        *,
        workspace_id: uuid.UUID,
        allowed_roles: list[str],
        top_k: int = 6,
    ) -> list[SearchResult]:
        query_vector = self._embeddings.embed_query(query_text)
        return self._vector_store.search(
            query_vector,
            workspace_id=str(workspace_id),
            allowed_roles=allowed_roles,
            limit=top_k,
        )
