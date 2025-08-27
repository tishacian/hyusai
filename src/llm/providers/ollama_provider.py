"""
Ollama provider implementation.
"""
from collections.abc import AsyncGenerator

from ollama import AsyncClient

from ..base import LLMProvider


class OllamaProvider(LLMProvider):
    """Ollama LLM provider implementation."""
    
    def __init__(self, host: str = "http://localhost:11434", api_key: str | None = None, **kwargs):
        """Initialize the Ollama provider."""
        # Ollama doesn't use API keys, filter them out
        filtered_kwargs = {k: v for k, v in kwargs.items() if k != 'api_key'}
        self.client = AsyncClient(host=host, **filtered_kwargs)
    
    async def generate(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
        max_completion_tokens: int | None = None,
        reasoning_effort: str | None = None,
        **kwargs
    ) -> str:
        """Generate a response using Ollama."""
        options = self._build_options(temperature=temperature, max_tokens=max_tokens, **kwargs)
        
        response = await self.client.chat(
            model=model or "qwen2.5:0.6b",
            messages=messages,
            options=options,
            stream=False
        )
        return response["message"]["content"]
    
    async def stream_generate(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
        max_completion_tokens: int | None = None,
        reasoning_effort: str | None = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Stream a response using Ollama."""
        options = self._build_options(temperature=temperature, max_tokens=max_tokens, **kwargs)
        
        async for chunk in await self.client.chat(
            model=model or "qwen2.5:0.6b",
            messages=messages,
            options=options,
            stream=True
        ):
            if chunk["message"]["content"]:
                yield chunk["message"]["content"]
    
    def _build_options(self, temperature: float | None = None, max_tokens: int | None = None, **kwargs) -> dict:
        """Build Ollama options filtering out None values."""
        options = {}
        if temperature is not None:
            options["temperature"] = temperature
        if max_tokens is not None:
            options["num_predict"] = max_tokens  # Ollama uses num_predict for max tokens
        
        # Add any additional options
        for key, value in kwargs.items():
            if value is not None:
                options[key] = value
        
        return options