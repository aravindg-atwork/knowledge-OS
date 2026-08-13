import pathlib
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.connectors.types import DownloadedFile, RemoteFile
from app.models.chunk import Chunk
from app.models.document import Document, DocumentVersion, ProcessingStatus
from app.pipeline.chunking import RecursiveChunker
from app.pipeline.extractors import get_extractor
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository


@dataclass(frozen=True)
class ProcessResult:
    document: Document
    version: DocumentVersion
    is_new_version: bool  # False means the checksum matched an existing version (no-op)


class PipelineService:
    """Orchestrates one document end-to-end: idempotency check, download
    persistence, extraction, chunking. Embedding is a separate stage (see
    embed_chunk_batch_task) since it's the part most worth batching/retrying
    independently.
    """

    def __init__(self, db: Session, raw_storage_dir: str) -> None:
        self._db = db
        self._documents = DocumentRepository(db)
        self._chunks = ChunkRepository(db)
        self._raw_storage_dir = raw_storage_dir
        self._chunker = RecursiveChunker()

    def process_document(
        self,
        *,
        workspace_id: uuid.UUID,
        connector_account_id: uuid.UUID,
        remote_file: RemoteFile,
        downloaded: DownloadedFile,
        permission_scope: dict,
    ) -> ProcessResult:
        document = self._documents.get_or_create_document(
            workspace_id=workspace_id,
            connector_account_id=connector_account_id,
            external_id=remote_file.external_id,
            title=remote_file.name,
            mime_type=remote_file.mime_type,
            source_url=remote_file.source_url,
            permission_scope=permission_scope,
        )

        # Idempotency gate: unchanged content (by checksum) is a no-op, even
        # across repeated syncs -- the unique (document_id, checksum)
        # constraint backs this up at the DB level under concurrent workers.
        existing = self._documents.find_version_by_checksum(document.id, downloaded.checksum)
        if existing is not None:
            return ProcessResult(document=document, version=existing, is_new_version=False)

        raw_storage_ref = self._persist_raw_bytes(document.id, downloaded)
        version = self._documents.create_version(
            document_id=document.id,
            checksum=downloaded.checksum,
            author=remote_file.author,
            source_modified_at=remote_file.modified_time,
            raw_storage_ref=raw_storage_ref,
        )

        try:
            version.processing_status = ProcessingStatus.extracting
            self._db.flush()
            extractor = get_extractor(downloaded.mime_type)
            extracted = extractor.extract(downloaded.content)

            version.extracted_title = extracted.extracted_title
            version.extracted_text_length = len(extracted.text)
            if extracted.author and not version.author:
                version.author = extracted.author

            version.processing_status = ProcessingStatus.chunking
            self._db.flush()
            text_chunks = self._chunker.chunk(extracted.text)
            chunk_rows = [
                Chunk(
                    document_version_id=version.id,
                    document_id=document.id,
                    chunk_index=tc.index,
                    text=tc.text,
                    token_count=tc.token_count,
                )
                for tc in text_chunks
            ]
            self._chunks.bulk_insert(chunk_rows)

            version.processing_status = ProcessingStatus.embedding
            self._db.flush()
        except Exception as exc:
            # One bad file shouldn't block the sync run: mark this version
            # failed and let the caller move on rather than retry forever.
            version.processing_status = ProcessingStatus.failed
            version.error_message = str(exc)
            self._db.flush()
            raise

        return ProcessResult(document=document, version=version, is_new_version=True)

    def _persist_raw_bytes(self, document_id: uuid.UUID, downloaded: DownloadedFile) -> str:
        directory = pathlib.Path(self._raw_storage_dir) / str(document_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{downloaded.checksum}.bin"
        if not path.exists():
            path.write_bytes(downloaded.content)
        return str(path)
