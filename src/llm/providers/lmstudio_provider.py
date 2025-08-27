"""
LM Studio provider implementation.
"""
from collections.abc import AsyncGenerator

from openai import AsyncOpenAI

from ..base import LLMProvider


class LMStudioProvider(LLMProvider):
    """LM Studio LLM provider implementation."""
    
    def __init__(self, base_url: str = "http://localhost:1234/v1", api_key: str | None = None, **kwargs):
        """Initialize the LM Studio provider."""
        # Remove api_key from kwargs if it exists to avoid conflict
        filtered_kwargs = {k: v for k, v in kwargs.items() if k != 'api_key'}
        self.client = AsyncOpenAI(
            base_url=base_url,
            api_key="lm-studio",  # LM Studio uses a dummy API key
            **filtered_kwargs
        )
    
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
        """Generate a response using LM Studio."""
        params = self._build_params(
            model=model or "local-model",
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
        
        response = await self.client.chat.completions.create(**params)
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
        """Stream a response using LM Studio."""
        params = self._build_params(
            model=model or "local-model",
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            **kwargs
        )
        
        stream = await self.client.chat.completions.create(**params)
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    
    def _build_params(self, **kwargs) -> dict:
        """Build API parameters filtering out None values."""
        return {k: v for k, v in kwargs.items() if v is not None}