import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import DocumentSummary
from app.services.document_access_service import DocumentAccessService

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=list[DocumentSummary])
def list_documents(
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DocumentSummary]:
    repo = DocumentRepository(db)
    documents = repo.list_documents(current_user.workspace_id)

    summaries = []
    for document in documents:
        version = (
            repo.get_version(document.current_version_id)
            if document.current_version_id
            else None
        )
        summaries.append(
            DocumentSummary(
                id=document.id,
                title=document.title,
                mime_type=document.mime_type,
                source_url=document.source_url,
                version_number=version.version_number if version else None,
                updated_at=document.updated_at,
            )
        )
    return summaries


@router.get("/{document_id}/content")
def get_document_content(
    document_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    service = DocumentAccessService(DocumentRepository(db), settings)
    content, mime_type = service.get_content(document_id, workspace_id=current_user.workspace_id)
    return Response(content=content, media_type=mime_type)
