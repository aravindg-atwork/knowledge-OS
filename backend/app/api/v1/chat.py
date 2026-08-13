from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.ai.factory import get_embedding_provider, get_llm_provider
from app.api.deps import CurrentUser, get_current_user
from app.core.config import Settings, get_settings
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.repositories.chat_repository import ChatRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.chat import ChatRequest, ChatResponse, CitationResponse
from app.services.rag_service import RagService
from app.services.retrieval_service import RetrievalService
from app.vectorstore.factory import get_vector_store

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
@limiter.limit(get_settings().RATE_LIMIT_CHAT)
async def chat(
    request: Request,
    payload: ChatRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ChatResponse:
    membership = WorkspaceRepository(db).get_membership(
        current_user.workspace_id, current_user.user_id
    )
    allowed_roles = [membership.role.value] if membership else ["member"]

    retrieval = RetrievalService(
        get_embedding_provider(settings), get_vector_store(settings)
    )
    rag_service = RagService(retrieval, get_llm_provider(settings), ChatRepository(db))

    result = await rag_service.answer(
        session_id=payload.session_id,
        workspace_id=current_user.workspace_id,
        user_id=current_user.user_id,
        allowed_roles=allowed_roles,
        question=payload.message,
    )
    db.commit()

    return ChatResponse(
        session_id=result.session_id,
        answer=result.answer,
        citations=[CitationResponse(**vars(c)) for c in result.citations],
    )
