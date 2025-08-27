"""
OpenAI Structured provider implementation.
"""
import os
from collections.abc import AsyncGenerator

from openai import AsyncOpenAI

from ..base import LLMProvider


class OpenAIStructuredProvider(LLMProvider):
    """OpenAI Structured LLM provider implementation for structured output."""
    
    # Models that require special handling (thinking models)
    THINKING_MODELS = ["o3-mini", "o1-mini", "o1", "o4-mini", "o3", "gpt-5", "gpt-5-mini", "gpt-5-nano"]
    
    def __init__(self, api_key: str | None = None, base_url: str | None = None, **kwargs):
        """Initialize the OpenAI Structured provider."""
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_API_BASE") or "https://api.openai.com/v1"
        
        if not self.api_key:
            raise ValueError("OpenAI API key is required")
        
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            **kwargs
        )
    
    def _is_thinking_model(self, model: str) -> bool:
        """Check if the model is a thinking model."""
        return model in self.THINKING_MODELS
    
    async def generate(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
        max_completion_tokens: int | None = None,
        reasoning_effort: str | None = None,
        response_format: dict | None = None,
        **kwargs
    ) -> str:
        """Generate a structured response using OpenAI."""
        model_name = model or "gpt-4o-2024-08-06"
        is_thinking = self._is_thinking_model(model_name)
        
        params = {
            "model": model_name,
            "messages": messages,
        }
        
        if response_format:
            params["response_format"] = response_format
        
        # Handle thinking vs regular models
        if is_thinking:
            if reasoning_effort:
                params["reasoning_effort"] = reasoning_effort
            if max_completion_tokens is not None:
                params["max_completion_tokens"] = max_completion_tokens
            elif max_tokens is not None:
                params["max_completion_tokens"] = max_tokens
        else:
            if temperature is not None:
                params["temperature"] = temperature
            if max_tokens is not None:
                params["max_tokens"] = max_tokens
        
        params.update({k: v for k, v in kwargs.items() if v is not None})
        
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
        response_format: dict | None = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Stream a structured response using OpenAI."""
        model_name = model or "gpt-4o-2024-08-06"
        is_thinking = self._is_thinking_model(model_name)
        
        params = {
            "model": model_name,
            "messages": messages,
            "stream": True,
        }
        
        if response_format:
            params["response_format"] = response_format
        
        # Handle thinking vs regular models
        if is_thinking:
            if reasoning_effort:
                params["reasoning_effort"] = reasoning_effort
            if max_completion_tokens is not None:
                params["max_completion_tokens"] = max_completion_tokens
            elif max_tokens is not None:
                params["max_completion_tokens"] = max_tokens
        else:
            if temperature is not None:
                params["temperature"] = temperature
            if max_tokens is not None:
                params["max_tokens"] = max_tokens
        
        params.update({k: v for k, v in kwargs.items() if v is not None})
        
        stream = await self.client.chat.completions.create(**params)
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content