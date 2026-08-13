from typing import Protocol


class EmbeddingProvider(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of chunk texts for storage."""

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string for retrieval."""

    @property
    def dimension(self) -> int: ...

    @property
    def model_name(self) -> str: ...
