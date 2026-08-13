import httpx


class OllamaEmbeddings:
    """Alternative to LocalSentenceTransformerEmbeddings: routes embeddings
    through the same Ollama runtime used for the LLM (e.g. nomic-embed-text),
    trading a per-call HTTP hop for a single-runtime-dependency deployment.
    Not the default -- swap in via AI_PROVIDER config if preferred.
    """

    def __init__(
        self,
        base_url: str,
        model: str = "nomic-embed-text",
        dimension: int = 768,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._dimension = dimension
        self._client = httpx.Client(timeout=timeout)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)

    def _embed_one(self, text: str) -> list[float]:
        response = self._client.post(
            f"{self._base_url}/api/embeddings", json={"model": self._model, "prompt": text}
        )
        response.raise_for_status()
        return response.json()["embedding"]

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model
