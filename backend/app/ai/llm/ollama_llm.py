from collections.abc import AsyncIterator

import httpx

from app.ai.llm.base import LLMChatMessage, LLMResponse


class OllamaChatLLM:
    """Calls a local Ollama server. Default model llama3.2:1b -- fast enough
    for CPU-only inference (no GPU required), which matters since this
    milestone targets local/self-hosted deployment. llama3.1:8b or gemma2:9b
    are documented alternatives with better quality if GPU/CPU headroom is
    available (set LLM_MODEL to swap -- no code change needed)."""

    def __init__(self, base_url: str, model: str = "llama3.2:1b", timeout: float = 120.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    async def generate(
        self,
        messages: list[LLMChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": [{"role": m.role, "content": m.content} for m in messages],
                    "stream": False,
                    "options": {"temperature": temperature, "num_predict": max_tokens},
                },
            )
            response.raise_for_status()
            data = response.json()
            return LLMResponse(content=data["message"]["content"], model=self._model)

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
                f"{self._base_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": [{"role": m.role, "content": m.content} for m in messages],
                    "stream": True,
                    "options": {"temperature": temperature, "num_predict": max_tokens},
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        yield content
