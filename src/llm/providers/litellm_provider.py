"""
LiteLLM provider implementation.
"""
from collections.abc import AsyncGenerator

import litellm

from ..base import LLMProvider


class LiteLLMProvider(LLMProvider):
    """LiteLLM provider implementation for unified LLM access."""
    
    def __init__(self, api_key: str | None = None, **kwargs):
        """Initialize the LiteLLM provider."""
        # LiteLLM handles API keys internally based on model name
        pass
    
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
        """Generate a response using LiteLLM."""
        params = self._build_params(
            model=model or "gpt-4o-mini",
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
        
        response = await litellm.acompletion(**params)
        return response.choices[0].message.content
    
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
        """Stream a response using LiteLLM."""
        params = self._build_params(
            model=model or "gpt-4o-mini",
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            **kwargs
        )
        
        stream = await litellm.acompletion(**params)
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    
    def _build_params(self, **kwargs) -> dict:
        """Build API parameters filtering out None values."""
        return {k: v for k, v in kwargs.items() if v is not None}