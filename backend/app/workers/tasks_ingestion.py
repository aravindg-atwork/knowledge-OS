import asyncio
import logging
import uuid

from app.ai.factory import get_embedding_provider
from app.connectors.registry import get_connector
from app.connectors.types import ConnectorCredential
from app.core.config import get_settings
from app.core.errors import TransientConnectorError
from app.db.session import SessionLocal
from app.models.document import ProcessingStatus
from app.pipeline.pipeline_service import PipelineService
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.sync_repository import SyncRepository
from app.vectorstore.base import VectorPoint
from app.vectorstore.factory import get_vector_store
from app.vectorstore.payload_schema import ChunkPayload
from app.workers.celery_app import celery_app
from app.workers.task_utils import CONNECTOR_RETRY_KWARGS, remote_file_from_dict

logger = logging.getLogger(__name__)


async def _authenticate_and_download(connector, account, remote_file):
    """Refreshes the connector's access token before downloading -- this task
    runs independently of (and often well after) the sync task that
    discovered `remote_file`, so any token obtained during that earlier sync
    may already be stale."""
    await connector.authenticate(
        ConnectorCredential(connector_account_id=str(account.id), extra=account.credential_ref)
    )
    return await connector.download(remote_file)


@celery_app.task(
    name="app.workers.tasks_ingestion.process_document_task",
    bind=True,
    autoretry_for=(TransientConnectorError,),
    **CONNECTOR_RETRY_KWARGS,
)
def process_document_task(self, connector_account_id: str, remote_file_dict: dict) -> dict:
    settings = get_settings()
    remote_file = remote_file_from_dict(remote_file_dict)

    db = SessionLocal()
    try:
        sync_repo = SyncRepository(db)
        account = sync_repo.get_connector_account(uuid.UUID(connector_account_id))
        if account is None:
            raise ValueError(f"No connector account {connector_account_id}")

        connector = get_connector(account.connector_type, account.mode)
        try:
            downloaded = asyncio.run(_authenticate_and_download(connector, account, remote_file))
        except TransientConnectorError:
            raise
        except Exception as exc:  # network/IO failures from the connector -> retryable
            raise TransientConnectorError(str(exc)) from exc

        permission_scope = {
            "workspace_id": str(account.workspace_id),
            "allowed_roles": ["admin", "member"],
        }

        pipeline_service = PipelineService(db, settings.RAW_STORAGE_DIR)
        try:
            result = pipeline_service.process_document(
                workspace_id=account.workspace_id,
                connector_account_id=account.id,
                remote_file=remote_file,
                downloaded=downloaded,
                permission_scope=permission_scope,
            )
        except Exception as exc:
            # Extraction/chunking failure on this one file: log and move on --
            # don't retry indefinitely, don't block the rest of the sync run.
            db.commit()
            logger.warning("Failed to process %s: %s", remote_file.external_id, exc)
            return {
                "status": "failed",
                "external_id": remote_file.external_id,
                "error": str(exc),
            }

        db.commit()

        if result.is_new_version:
            embed_chunk_batch_task.delay(str(result.version.id))
            return {"status": "processing", "document_version_id": str(result.version.id)}

        return {"status": "unchanged", "document_id": str(result.document.id)}
    finally:
        db.close()


@celery_app.task(
    name="app.workers.tasks_ingestion.embed_chunk_batch_task",
    bind=True,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=60,
)
def embed_chunk_batch_task(self, document_version_id: str) -> dict:
    settings = get_settings()
    version_uuid = uuid.UUID(document_version_id)

    db = SessionLocal()
    try:
        chunk_repo = ChunkRepository(db)
        document_repo = DocumentRepository(db)
        sync_repo = SyncRepository(db)

        version = document_repo.get_version(version_uuid)
        if version is None:
            raise ValueError(f"No document version {document_version_id}")
        document = document_repo.get_document(version.document_id)
        account = sync_repo.get_connector_account(document.connector_account_id)

        embedding_provider = get_embedding_provider(settings)
        vector_store = get_vector_store(settings)
        vector_store.ensure_collection(embedding_provider.dimension)

        unembedded = chunk_repo.get_unembedded_for_version(version_uuid)
        if unembedded:
            texts = [c.text for c in unembedded]
            vectors = embedding_provider.embed_documents(texts)
            allowed_roles = document.permission_scope.get("allowed_roles", ["admin", "member"])

            points = [
                VectorPoint(
                    id=str(chunk.id),
                    vector=vector,
                    payload=ChunkPayload(
                        document_id=str(document.id),
                        document_version_id=str(version.id),
                        workspace_id=str(document.workspace_id),
                        allowed_roles=allowed_roles,
                        connector_type=account.connector_type.value,
                        source_title=version.extracted_title or document.title,
                        source_url=document.source_url,
                        mime_type=document.mime_type,
                        chunk_index=chunk.chunk_index,
                        chunk_text=chunk.text,
                        author=version.author,
                        source_modified_at=version.source_modified_at.isoformat(),
                        version_number=version.version_number,
                        checksum=version.checksum,
                    ),
                )
                for chunk, vector in zip(unembedded, vectors, strict=True)
            ]
            vector_store.upsert(points)
            for chunk in unembedded:
                chunk_repo.mark_embedded(chunk, embedding_provider.model_name)
            db.commit()

        all_chunks = chunk_repo.get_all_for_version(version_uuid)
        if all_chunks and all(c.embedded_at is not None for c in all_chunks):
            old_version_id = document.current_version_id
            document_repo.set_current_version(document, version)
            version.processing_status = ProcessingStatus.completed
            db.commit()

            # Retire the previous version's vectors so retrieval only ever
            # surfaces the latest content -- this is the "no silent
            # duplication after a change" guarantee at the retrieval layer.
            if old_version_id and str(old_version_id) != str(version.id):
                vector_store.delete_by_document(
                    str(document.id), exclude_version_id=str(version.id)
                )

        return {"status": "completed", "chunks_embedded": len(unembedded)}
    finally:
        db.close()
