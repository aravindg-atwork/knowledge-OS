import asyncio

from app.ai.embeddings.local_sentence_transformers import LocalSentenceTransformerEmbeddings
from app.models.chunk import Chunk
from app.models.document import Document, DocumentVersion
from app.repositories.chat_repository import ChatRepository
from app.services.rag_service import RagService
from app.services.retrieval_service import RetrievalService
from app.vectorstore.factory import get_vector_store
from app.core.config import get_settings
from tests.integration.conftest import StubLLM


def test_sync_populates_documents_versions_and_chunks(db, workspace_factory, sync_pipeline):
    _workspace, _user, connector_account = workspace_factory("sync-flow")

    outcome = sync_pipeline(connector_account.id)

    assert len(outcome["change_set"].changed) == 10
    assert all(r["status"] == "processing" for r in outcome["results"])

    documents = db.query(Document).filter(Document.connector_account_id == connector_account.id).all()
    assert len(documents) == 10
    assert all(doc.current_version_id is not None for doc in documents)

    versions = db.query(DocumentVersion).filter(
        DocumentVersion.document_id.in_([d.id for d in documents])
    ).all()
    assert len(versions) == 10

    chunks = db.query(Chunk).filter(Chunk.document_id.in_([d.id for d in documents])).all()
    assert len(chunks) > 0
    assert all(c.embedded_at is not None for c in chunks)


def test_chat_answer_cites_the_relevant_document(db, workspace_factory, sync_pipeline):
    workspace, user, connector_account = workspace_factory("chat-flow")
    sync_pipeline(connector_account.id)

    settings = get_settings()
    embedding_provider = LocalSentenceTransformerEmbeddings(model_name=settings.EMBEDDING_MODEL)
    vector_store = get_vector_store(settings)
    retrieval = RetrievalService(embedding_provider, vector_store)
    rag_service = RagService(retrieval, StubLLM(), ChatRepository(db))

    result = asyncio.run(
        rag_service.answer(
            session_id=None,
            workspace_id=workspace.id,
            user_id=user.id,
            allowed_roles=["admin", "member"],
            question="Where is the payment API documentation?",
            top_k=4,
        )
    )
    db.commit()

    assert result.answer
    assert len(result.citations) > 0
    assert any("Payment" in c.document_title for c in result.citations)
