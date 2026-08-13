import uuid
from pathlib import Path

from app.core.audit import log_audit_event
from app.core.config import Settings
from app.core.errors import NotFoundError, PermissionDeniedError
from app.repositories.document_repository import DocumentRepository


class DocumentAccessService:
    """Resolves "open the original document." Built against the locally
    cached raw bytes populated during ingestion (settings.DOCUMENT_CONTENT_MODE
    == "cached"); when a real connector is wired in, this can instead redirect
    to document.source_url (DOCUMENT_CONTENT_MODE == "redirect") -- a
    one-line branch, not a redesign.
    """

    def __init__(self, document_repo: DocumentRepository, settings: Settings) -> None:
        self._documents = document_repo
        self._settings = settings

    def get_content(self, document_id: uuid.UUID, *, workspace_id: uuid.UUID) -> tuple[bytes, str]:
        document = self._documents.get_document(document_id)
        if document is None or document.is_deleted:
            raise NotFoundError("Document not found")
        if document.workspace_id != workspace_id:
            log_audit_event(
                "document.access.denied",
                document_id=str(document_id),
                requesting_workspace_id=str(workspace_id),
                document_workspace_id=str(document.workspace_id),
            )
            raise PermissionDeniedError("You do not have access to this document")
        if document.current_version_id is None:
            raise NotFoundError("Document has no processed version yet")

        version = self._documents.get_version(document.current_version_id)
        content = Path(version.raw_storage_ref).read_bytes()
        log_audit_event(
            "document.access.granted",
            document_id=str(document_id),
            workspace_id=str(workspace_id),
        )
        return content, document.mime_type
