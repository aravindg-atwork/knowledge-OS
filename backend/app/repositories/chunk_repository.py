import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.chunk import Chunk


class ChunkRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def bulk_insert(self, chunks: list[Chunk]) -> None:
        self._db.add_all(chunks)
        self._db.flush()

    def get_unembedded_for_version(self, document_version_id: uuid.UUID) -> list[Chunk]:
        stmt = (
            select(Chunk)
            .where(
                Chunk.document_version_id == document_version_id, Chunk.embedded_at.is_(None)
            )
            .order_by(Chunk.chunk_index)
        )
        return list(self._db.scalars(stmt))

    def get_all_for_version(self, document_version_id: uuid.UUID) -> list[Chunk]:
        stmt = (
            select(Chunk)
            .where(Chunk.document_version_id == document_version_id)
            .order_by(Chunk.chunk_index)
        )
        return list(self._db.scalars(stmt))

    def mark_embedded(self, chunk: Chunk, model_name: str) -> None:
        chunk.embedded_at = utcnow()
        chunk.embedding_model = model_name
        self._db.flush()

    def get_by_id(self, chunk_id: uuid.UUID) -> Chunk | None:
        return self._db.get(Chunk, chunk_id)
