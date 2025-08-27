"""
llama.cpp provider implementation.
"""
import os
from collections.abc import AsyncGenerator

from openai import AsyncOpenAI

from ..base import LLMProvider


class LlamaCppProvider(LLMProvider):
    """llama.cpp LLM provider implementation."""
    
    def __init__(
        self, 
        api_key: str | None = None,
        base_url: str | None = None,
        **kwargs
    ):
        """Initialize the llama.cpp provider."""
        self.api_key = api_key or "llamacpp-api-key"  # llama.cpp doesn't use API keys
        self.base_url = base_url or os.getenv("LLAMACPP_BASE_URL") or "http://localhost:8080"
        
        if not self.base_url:
            raise ValueError("llama.cpp base URL is required")
        
        # Create OpenAI client for consistency, even though we'll use custom logic
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=f"{self.base_url}/v1",  # Most llamacpp servers have v1 endpoint
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
        """Generate a response using llama.cpp."""
        try:
            # Try OpenAI-compatible API first (newer llama.cpp servers)
            params = self._build_params(
                model=model or "llamacpp",
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            )
            
            response = await self.client.chat.completions.create(**params)
            return response.choices[0].message.content or ""
            
        except Exception:
            # Fallback to legacy completion endpoint
            return await self._legacy_generate(messages, model, temperature, max_tokens, **kwargs)
    
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
        """Stream a response using llama.cpp."""
        try:
            # Try OpenAI-compatible API first (newer llama.cpp servers)
            params = self._build_params(
                model=model or "llamacpp",
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
                    
        except Exception:
            # Fallback to legacy completion endpoint
            async for chunk in self._legacy_stream_generate(messages, model, temperature, max_tokens, **kwargs):
                yield chunk
    
    def _build_params(self, **kwargs) -> dict:
        """Build API parameters filtering out None values."""
        return {k: v for k, v in kwargs.items() if v is not None}
    
    async def _legacy_generate(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
        **kwargs
    ) -> str:
        """Generate using legacy llama.cpp completion endpoint."""
        import aiohttp
        
        prompt = self._messages_to_prompt(messages)
        
        params = {
            "prompt": prompt,
            "temperature": temperature or 0.0,
            "n_predict": max_tokens or 512,
            "stop": ["<|im_end|>", "User:", "Assistant:", "\n\n"],
            "stream": False,
            **kwargs
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/completion",
                json=params,
                headers={"Content-Type": "application/json"}
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise RuntimeError(f"llama.cpp API error {response.status}: {error_text}")
                
                result = await response.json()
                return result.get("content", "").strip()
    
    async def _legacy_stream_generate(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Stream using legacy llama.cpp completion endpoint."""
        import aiohttp
        import json
        
        prompt = self._messages_to_prompt(messages)
        
        params = {
            "prompt": prompt,
            "temperature": temperature or 0.0,
            "n_predict": max_tokens or 512,
            "stop": ["<|im_end|>", "User:", "Assistant:", "\n\n"],
            "stream": True,
            **kwargs
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/completion",
                json=params,
                headers={"Content-Type": "application/json"}
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise RuntimeError(f"llama.cpp API error {response.status}: {error_text}")
                
                async for line in response.content:
                    line_text = line.decode('utf-8').strip()
                    if line_text.startswith("data: "):
                        data_str = line_text[6:]
                        if data_str == "[DONE]":
                            break
                        
                        try:
                            chunk_data = json.loads(data_str)
                            if "content" in chunk_data:
                                content = chunk_data["content"]
                                if content:
                                    yield content
                        except json.JSONDecodeError:
                            continue

    def _messages_to_prompt(self, messages: list[dict[str, str]]) -> str:
        """Convert messages to a single prompt string."""
        prompt_parts = []
        
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            
            if role == "system":
                prompt_parts.append(f"System: {content}")
            elif role == "user":
                prompt_parts.append(f"User: {content}")
            elif role == "assistant":
                prompt_parts.append(f"Assistant: {content}")
        
        prompt_parts.append("Assistant:")
        return "\n".join(prompt_parts)