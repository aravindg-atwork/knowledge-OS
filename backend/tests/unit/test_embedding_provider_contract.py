import pytest

from app.ai.embeddings.local_sentence_transformers import LocalSentenceTransformerEmbeddings

pytestmark = pytest.mark.slow  # downloads/loads a real model on first run


@pytest.fixture(scope="module")
def provider() -> LocalSentenceTransformerEmbeddings:
    return LocalSentenceTransformerEmbeddings()


def test_dimension_matches_declared(provider):
    vectors = provider.embed_documents(["hello world"])
    assert len(vectors[0]) == provider.dimension


def test_embed_documents_returns_one_vector_per_text(provider):
    vectors = provider.embed_documents(["first text", "second text", "third text"])
    assert len(vectors) == 3
    assert all(len(v) == provider.dimension for v in vectors)


def test_embed_documents_empty_list_returns_empty(provider):
    assert provider.embed_documents([]) == []


def test_embed_query_returns_single_vector_of_declared_dimension(provider):
    vector = provider.embed_query("where is the payment api documentation?")
    assert len(vector) == provider.dimension


def test_model_name_matches_configured_model():
    provider = LocalSentenceTransformerEmbeddings(model_name="BAAI/bge-small-en-v1.5")
    assert provider.model_name == "BAAI/bge-small-en-v1.5"
