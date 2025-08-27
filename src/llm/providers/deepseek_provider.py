"""
DeepSeek provider implementation.
"""
import os
import logging
from collections.abc import AsyncGenerator

from openai import AsyncOpenAI

from ..base import LLMProvider


class DeepSeekProvider(LLMProvider):
    """DeepSeek LLM provider implementation."""
    
    def __init__(self, api_key: str | None = None, base_url: str | None = None, **kwargs):
        """Initialize the DeepSeek provider."""
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.base_url = base_url or os.getenv("DEEPSEEK_API_BASE") or "https://api.deepseek.com"
        
        if not self.api_key:
            raise ValueError("DeepSeek API key is required")
        
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            **kwargs
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
        """Generate a response using DeepSeek."""
        params = self._build_params(
            model=model or "deepseek-chat",
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
        """Stream a response using DeepSeek."""
        params = self._build_params(
            model=model or "deepseek-chat",
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