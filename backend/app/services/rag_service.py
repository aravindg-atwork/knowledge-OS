import uuid
from dataclasses import dataclass

from app.ai.llm.base import ChatLLMProvider, LLMChatMessage
from app.models.chat import ChatRole
from app.models.chat import Citation as CitationModel
from app.repositories.chat_repository import ChatRepository
from app.services.retrieval_service import RetrievalService

SYSTEM_PROMPT = (
    "You are the Enterprise Knowledge Hub assistant. Answer the user's question "
    "using ONLY the numbered context passages below, drawn from the company's "
    "internal documents. If the context doesn't contain the answer, say you "
    "don't know rather than guessing. You may cite passages inline as [1], [2], "
    "etc. matching their number, but this is optional."
)


@dataclass(frozen=True)
class CitationView:
    document_id: str
    document_title: str
    chunk_id: str
    chunk_text_snippet: str
    score: float
    source_url: str
    version_number: int


@dataclass(frozen=True)
class RagAnswer:
    session_id: uuid.UUID
    answer: str
    citations: list[CitationView]


class RagService:
    def __init__(
        self, retrieval: RetrievalService, llm: ChatLLMProvider, chat_repo: ChatRepository
    ) -> None:
        self._retrieval = retrieval
        self._llm = llm
        self._chat_repo = chat_repo

    async def answer(
        self,
        *,
        session_id: uuid.UUID | None,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        allowed_roles: list[str],
        question: str,
        top_k: int = 6,
    ) -> RagAnswer:
        session = self._chat_repo.get_or_create_session(
            session_id=session_id, workspace_id=workspace_id, user_id=user_id
        )
        history = self._chat_repo.get_recent_messages(session.id, limit=10)
        results = self._retrieval.search(
            question, workspace_id=workspace_id, allowed_roles=allowed_roles, top_k=top_k
        )

        context_block = "\n\n".join(
            f'[{i + 1}] (from "{r.payload.source_title}"): {r.payload.chunk_text}'
            for i, r in enumerate(results)
        )
        if not context_block:
            context_block = "(no relevant documents were found for this question)"

        messages = [LLMChatMessage(role="system", content=SYSTEM_PROMPT)]
        messages.extend(LLMChatMessage(role=m.role.value, content=m.content) for m in history)
        messages.append(
            LLMChatMessage(
                role="user", content=f"Context:\n{context_block}\n\nQuestion: {question}"
            )
        )

        self._chat_repo.add_message(session_id=session.id, role=ChatRole.user, content=question)

        llm_response = await self._llm.generate(messages)
        assistant_message = self._chat_repo.add_message(
            session_id=session.id, role=ChatRole.assistant, content=llm_response.content
        )

        self._chat_repo.add_citations(
            [
                CitationModel(
                    chat_message_id=assistant_message.id,
                    chunk_id=uuid.UUID(r.id),
                    document_id=uuid.UUID(r.payload.document_id),
                    document_version_id=uuid.UUID(r.payload.document_version_id),
                    score=r.score,
                    rank=i,
                )
                for i, r in enumerate(results)
            ]
        )

        return RagAnswer(
            session_id=session.id,
            answer=llm_response.content,
            citations=[
                CitationView(
                    document_id=r.payload.document_id,
                    document_title=r.payload.source_title,
                    chunk_id=r.id,
                    chunk_text_snippet=r.payload.chunk_text[:280],
                    score=r.score,
                    source_url=r.payload.source_url,
                    version_number=r.payload.version_number,
                )
                for r in results
            ],
        )
