from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.vectorstore.payload_schema import ChunkPayload


@dataclass(frozen=True)
class VectorPoint:
    id: str
    vector: list[float]
    payload: ChunkPayload


@dataclass(frozen=True)
class SearchResult:
    id: str
    score: float
    payload: ChunkPayload


class VectorStore(ABC):
    @abstractmethod
    def ensure_collection(self, dimension: int) -> None:
        """Create the collection (+ payload indexes) if it doesn't exist yet."""

    @abstractmethod
    def upsert(self, points: list[VectorPoint]) -> None: ...

    @abstractmethod
    def search(
        self,
        vector: list[float],
        *,
        workspace_id: str,
        allowed_roles: list[str],
        limit: int = 6,
    ) -> list[SearchResult]:
        """Vector search with the permission filter baked into the query
        itself -- callers never receive points they aren't allowed to see."""

    @abstractmethod
    def delete_by_document(self, document_id: str, exclude_version_id: str | None = None) -> None:
        """Remove points for a document, optionally keeping one version's
        points (used to retire a superseded version after a new one embeds)."""
