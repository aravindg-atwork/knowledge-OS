from collections.abc import AsyncIterator

import httpx

from app.ai.llm.base import LLMChatMessage, LLMResponse

_CHAT_COMPLETIONS_URL = "https://api.mistral.ai/v1/chat/completions"


class MistralChatLLM:
    """Calls the Mistral AI chat completions API (OpenAI-compatible shape).

    Default model mistral-small-latest -- cheap/fast and good enough for a
    RAG-answering assistant; mistral-large-latest is the documented upgrade
    path for higher-quality generation (set MISTRAL_MODEL to swap -- no code
    change needed).
    """

    def __init__(
        self,
        api_key: str,
        model: str = "mistral-small-latest",
        timeout: float = 120.0,
    ) -> None:
        if not api_key:
            raise ValueError("MISTRAL_API_KEY is required when AI_PROVIDER=mistral")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def generate(
        self,
        messages: list[LLMChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                _CHAT_COMPLETIONS_URL,
                headers=self._headers(),
                json={
                    "model": self._model,
                    "messages": [{"role": m.role, "content": m.content} for m in messages],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": False,
                },
            )
            response.raise_for_status()
            data = response.json()
            return LLMResponse(
                content=data["choices"][0]["message"]["content"],
                model=data.get("model", self._model),
            )

    async def generate_stream(
        self,
        messages: list[LLMChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        import json

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST",
                _CHAT_COMPLETIONS_URL,
                headers=self._headers(),
                json={
                    "model": self._model,
                    "messages": [{"role": m.role, "content": m.content} for m in messages],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    payload = line[len("data: ") :]
                    if payload == "[DONE]":
                        break
                    chunk = json.loads(payload)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
