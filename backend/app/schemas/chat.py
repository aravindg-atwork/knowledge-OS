import uuid

from pydantic import BaseModel


class ChatRequest(BaseModel):
    session_id: uuid.UUID | None = None
    message: str


class CitationResponse(BaseModel):
    document_id: str
    document_title: str
    chunk_id: str
    chunk_text_snippet: str
    score: float
    source_url: str
    version_number: int


class ChatResponse(BaseModel):
    session_id: uuid.UUID
    answer: str
    citations: list[CitationResponse]
