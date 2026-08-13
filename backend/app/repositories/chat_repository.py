import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chat import ChatMessage, ChatRole, ChatSession, Citation


class ChatRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_or_create_session(
        self, *, session_id: uuid.UUID | None, workspace_id: uuid.UUID, user_id: uuid.UUID
    ) -> ChatSession:
        if session_id is not None:
            session = self._db.get(ChatSession, session_id)
            if session is not None:
                return session
        session = ChatSession(workspace_id=workspace_id, user_id=user_id)
        self._db.add(session)
        self._db.flush()
        return session

    def get_recent_messages(self, session_id: uuid.UUID, limit: int = 10) -> list[ChatMessage]:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
        return list(reversed(list(self._db.scalars(stmt))))

    def add_message(self, *, session_id: uuid.UUID, role: ChatRole, content: str) -> ChatMessage:
        message = ChatMessage(session_id=session_id, role=role, content=content)
        self._db.add(message)
        self._db.flush()
        return message

    def add_citations(self, citations: list[Citation]) -> None:
        self._db.add_all(citations)
        self._db.flush()
