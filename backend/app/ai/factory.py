from functools import lru_cache

from fastapi import Depends

from app.ai.embeddings.base import EmbeddingProvider
from app.ai.embeddings.local_sentence_transformers import LocalSentenceTransformerEmbeddings
from app.ai.llm.base import ChatLLMProvider
from app.ai.llm.mistral_llm import MistralChatLLM
from app.ai.llm.ollama_llm import OllamaChatLLM
from app.core.config import Settings, get_settings

# Cached on primitive args so the (expensive-to-load) model is a true
# process-wide singleton, reused by both FastAPI request handlers and Celery
# tasks -- neither needs FastAPI's DI container, they just call these
# functions directly.


@lru_cache
def _build_embedding_provider(ai_provider: str, embedding_model: str) -> EmbeddingProvider:
    if ai_provider == "local":
        return LocalSentenceTransformerEmbeddings(model_name=embedding_model)
    # future: elif ai_provider == "openai": return OpenAIEmbeddings(...)
    # future: elif ai_provider == "anthropic": return VoyageEmbeddings(...)
    raise NotImplementedError(f"AI_PROVIDER={ai_provider!r} not yet implemented for embeddings")


@lru_cache
def _build_llm_provider(
    ai_provider: str,
    ollama_base_url: str,
    llm_model: str,
    mistral_api_key: str,
    mistral_model: str,
) -> ChatLLMProvider:
    if ai_provider == "local":
        return OllamaChatLLM(base_url=ollama_base_url, model=llm_model)
    if ai_provider == "mistral":
        return MistralChatLLM(api_key=mistral_api_key, model=mistral_model)
    # future: elif ai_provider == "openai": return OpenAIChatLLM(...)
    # future: elif ai_provider == "anthropic": return AnthropicChatLLM(...)
    raise NotImplementedError(f"AI_PROVIDER={ai_provider!r} not yet implemented for LLM")


def get_embedding_provider(settings: Settings = Depends(get_settings)) -> EmbeddingProvider:
    return _build_embedding_provider(settings.AI_PROVIDER, settings.EMBEDDING_MODEL)


def get_llm_provider(settings: Settings = Depends(get_settings)) -> ChatLLMProvider:
    return _build_llm_provider(
        settings.AI_PROVIDER,
        settings.OLLAMA_BASE_URL,
        settings.LLM_MODEL,
        settings.MISTRAL_API_KEY,
        settings.MISTRAL_MODEL,
    )
