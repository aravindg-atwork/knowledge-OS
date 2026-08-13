from app.ai.embeddings.local_sentence_transformers import LocalSentenceTransformerEmbeddings
from app.core.config import get_settings
from app.services.retrieval_service import RetrievalService
from app.vectorstore.factory import get_vector_store


def test_retrieval_never_crosses_workspace_boundaries(db, workspace_factory, sync_pipeline):
    workspace_a, _user_a, connector_a = workspace_factory("permtest-a")
    workspace_b, _user_b, connector_b = workspace_factory("permtest-b")

    sync_pipeline(connector_a.id)
    sync_pipeline(connector_b.id)

    settings = get_settings()
    embedding_provider = LocalSentenceTransformerEmbeddings(model_name=settings.EMBEDDING_MODEL)
    retrieval = RetrievalService(embedding_provider, get_vector_store(settings))

    results_a = retrieval.search(
        "payment API documentation",
        workspace_id=workspace_a.id,
        allowed_roles=["admin", "member"],
        top_k=10,
    )
    assert len(results_a) > 0
    assert all(r.payload.workspace_id == str(workspace_a.id) for r in results_a)
    assert all(r.payload.workspace_id != str(workspace_b.id) for r in results_a)

    results_b = retrieval.search(
        "payment API documentation",
        workspace_id=workspace_b.id,
        allowed_roles=["admin", "member"],
        top_k=10,
    )
    assert len(results_b) > 0
    assert all(r.payload.workspace_id == str(workspace_b.id) for r in results_b)
