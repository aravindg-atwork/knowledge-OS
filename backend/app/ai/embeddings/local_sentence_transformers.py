from sentence_transformers import SentenceTransformer


class LocalSentenceTransformerEmbeddings:
    """CPU-friendly local embeddings via sentence-transformers. Default model
    BAAI/bge-small-en-v1.5 (384-dim). Runs in-process -- no HTTP round trip
    from the Celery worker, unlike routing embeddings through Ollama.
    """

    _QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        self._model_name = model_name
        self._model = SentenceTransformer(model_name)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        embeddings = self._model.encode(texts, normalize_embeddings=True)
        return embeddings.tolist()

    def embed_query(self, text: str) -> list[float]:
        embedding = self._model.encode(
            self._QUERY_INSTRUCTION + text, normalize_embeddings=True
        )
        return embedding.tolist()

    @property
    def dimension(self) -> int:
        return self._model.get_sentence_embedding_dimension()

    @property
    def model_name(self) -> str:
        return self._model_name
