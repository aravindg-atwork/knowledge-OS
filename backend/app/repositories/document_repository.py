import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentVersion, ProcessingStatus


class DocumentRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_or_create_document(
        self,
        *,
        workspace_id: uuid.UUID,
        connector_account_id: uuid.UUID,
        external_id: str,
        title: str,
        mime_type: str,
        source_url: str,
        permission_scope: dict,
    ) -> Document:
        stmt = select(Document).where(
            Document.connector_account_id == connector_account_id,
            Document.external_id == external_id,
        )
        document = self._db.scalars(stmt).first()
        if document is None:
            document = Document(
                workspace_id=workspace_id,
                connector_account_id=connector_account_id,
                external_id=external_id,
                title=title,
                mime_type=mime_type,
                source_url=source_url,
                permission_scope=permission_scope,
            )
            self._db.add(document)
            self._db.flush()
        else:
            document.title = title
            document.mime_type = mime_type
            document.source_url = source_url
            document.is_deleted = False
        return document

    def find_by_external_id(
        self, connector_account_id: uuid.UUID, external_id: str
    ) -> Document | None:
        stmt = select(Document).where(
            Document.connector_account_id == connector_account_id,
            Document.external_id == external_id,
        )
        return self._db.scalars(stmt).first()

    def find_version_by_checksum(
        self, document_id: uuid.UUID, checksum: str
    ) -> DocumentVersion | None:
        stmt = select(DocumentVersion).where(
            DocumentVersion.document_id == document_id, DocumentVersion.checksum == checksum
        )
        return self._db.scalars(stmt).first()

    def next_version_number(self, document_id: uuid.UUID) -> int:
        stmt = (
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number.desc())
        )
        latest = self._db.scalars(stmt).first()
        return (latest.version_number + 1) if latest else 1

    def create_version(
        self,
        *,
        document_id: uuid.UUID,
        checksum: str,
        author: str | None,
        source_modified_at: datetime,
        raw_storage_ref: str,
    ) -> DocumentVersion:
        version = DocumentVersion(
            document_id=document_id,
            version_number=self.next_version_number(document_id),
            checksum=checksum,
            author=author,
            source_modified_at=source_modified_at,
            raw_storage_ref=raw_storage_ref,
            processing_status=ProcessingStatus.downloading,
        )
        self._db.add(version)
        self._db.flush()
        return version

    def mark_deleted(self, document: Document) -> None:
        document.is_deleted = True
        self._db.flush()

    def get_document(self, document_id: uuid.UUID) -> Document | None:
        return self._db.get(Document, document_id)

    def get_version(self, version_id: uuid.UUID) -> DocumentVersion | None:
        return self._db.get(DocumentVersion, version_id)

    def list_documents(
        self, workspace_id: uuid.UUID, limit: int = 50, offset: int = 0
    ) -> list[Document]:
        stmt = (
            select(Document)
            .where(Document.workspace_id == workspace_id, Document.is_deleted.is_(False))
            .order_by(Document.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self._db.scalars(stmt))

    def set_current_version(self, document: Document, version: DocumentVersion) -> None:
        document.current_version_id = version.id
        self._db.flush()
