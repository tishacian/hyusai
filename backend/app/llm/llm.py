"""
Main LLM class providing a unified interface for different LLM providers.
"""
from collections.abc import AsyncGenerator
from typing import Optional, Any

from .base import LLMProvider
from .models import (
    CompletionRequest,
    CompletionResponse,
    StreamingResponse,
    MessageParam,
)
from .providers import OpenAIProvider


def _lazy_provider(module_name: str, class_name: str):
    """Return a callable that lazy-imports a provider class."""
    _cached = {}

    def _get():
        if class_name not in _cached:
            import importlib
            mod = importlib.import_module(f".providers.{module_name}", package="app.llm")
            _cached[class_name] = getattr(mod, class_name)
        return _cached[class_name]
    return _get


class LLM:
    """LLM abstraction routing to the appropriate provider."""

    _PROVIDER_FACTORIES = {
        "openai": lambda: OpenAIProvider,
        "gemini": _lazy_provider("gemini_provider", "GeminiProvider"),
        "openrouter": _lazy_provider("openrouter_provider", "OpenRouterProvider"),
        "anthropic": _lazy_provider("anthropic_provider", "AnthropicProvider"),
        "deepseek": _lazy_provider("deepseek_provider", "DeepSeekProvider"),
        "groq": _lazy_provider("groq_provider", "GroqProvider"),
        "together": _lazy_provider("together_provider", "TogetherProvider"),
        "xai": _lazy_provider("xai_provider", "XAIProvider"),
        "ollama": _lazy_provider("ollama_provider", "OllamaProvider"),
        "lmstudio": _lazy_provider("lmstudio_provider", "LMStudioProvider"),
        "aws_bedrock": _lazy_provider("aws_bedrock_provider", "AWSBedrockProvider"),
        "azure_openai": _lazy_provider("azure_openai_provider", "AzureOpenAIProvider"),
        "azure_openai_structured": _lazy_provider("azure_openai_structured_provider", "AzureOpenAIStructuredProvider"),
        "langchain": _lazy_provider("langchain_provider", "LangChainProvider"),
        "litellm": _lazy_provider("litellm_provider", "LiteLLMProvider"),
        "openai_structured": _lazy_provider("openai_structured_provider", "OpenAIStructuredProvider"),
        "sarvam": _lazy_provider("sarvam_provider", "SarvamProvider"),
        "vllm": _lazy_provider("vllm_provider", "VLLMProvider"),
        "llamacpp": _lazy_provider("llamacpp_provider", "LlamaCppProvider"),
        "lmdeploy": _lazy_provider("lmdeploy_provider", "LMDeployProvider"),
    }

    def __init__(
        self,
        provider: str,
        api_key: Optional[str] = None,
        model_mapping: Optional[dict] = None,
        **kwargs
    ):
        """
        Initialize the LLM with a specific provider.

        Args:
            provider: The provider to use (required) - one of: openai, anthropic, gemini, etc.
            api_key: API key for the provider (defaults to environment variable)
            model_mapping: Custom mapping of generic model names to provider-specific models
            **kwargs: Additional provider-specific initialization parameters
        """
        self.provider_name = provider.lower()

        if self.provider_name not in self._PROVIDER_FACTORIES:
            raise ValueError(f"Unsupported provider: {provider}. Must be one of: {', '.join(self._PROVIDER_FACTORIES.keys())}")

        provider_class = self._PROVIDER_FACTORIES[self.provider_name]()
        self.provider: LLMProvider = provider_class(api_key=api_key, **kwargs)

    async def generate(
        self,
        messages: list,
        model: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> CompletionResponse:
        """
        Generate a response using the configured provider.

        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            model: Specific model name (required, e.g., "gpt-4o", "claude-3-5-sonnet")
            temperature: Controls randomness (0.0 to 1.0, ignored for thinking models)
            max_tokens: Maximum number of tokens to generate
            **kwargs: Additional provider-specific parameters

        Returns:
            CompletionResponse with choices, usage, and metadata
        """
        # Create a validated request
        request = CompletionRequest(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
        
        # Call the provider with the validated request
        return await self.provider.generate(request)

    async def stream_generate(
        self,
        messages: list,
        model: str,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> AsyncGenerator[StreamingResponse, None]:
        """
        Stream a response using the configured provider.

        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            model: Specific model name (required, e.g., "gpt-4o", "claude-3-5-sonnet")
            temperature: Controls randomness (0.0 to 1.0)
            max_tokens: Maximum number of tokens to generate
            **kwargs: Additional provider-specific parameters

        Returns:
            AsyncGenerator yielding StreamingResponse chunks
        """
        # Create a validated request
        request = CompletionRequest(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            **kwargs
        )
        
        # Stream from the provider with the validated request
        async for chunk in self.provider.stream_generate(request):
            yield chunk
    
    # Convenience methods for simple text generation
    
    async def complete(
        self,
        prompt: str,
        model: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        """
        Simple text completion with automatic message formatting.
        
        Args:
            prompt: User prompt text
            model: Model to use
            system_prompt: Optional system message
            temperature: Controls randomness
            max_tokens: Maximum tokens to generate
            **kwargs: Additional parameters
            
        Returns:
            Generated text content
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        response = await self.generate(
            messages=messages,  # type: ignore
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
        
        # Extract text from response
        if response.choices and response.choices[0].message.content:
            return response.choices[0].message.content
        return ""
    
    async def stream_complete(
        self,
        prompt: str,
        model: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """
        Simple streaming text completion with automatic message formatting.
        
        Args:
            prompt: User prompt text
            model: Model to use
            system_prompt: Optional system message
            temperature: Controls randomness
            max_tokens: Maximum tokens to generate
            **kwargs: Additional parameters
            
        Yields:
            Generated text chunks
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        async for chunk in self.stream_generate(
            messages=messages,  # type: ignore
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        ):
            # Extract content from streaming response
            if chunk.choices and chunk.choices[0].delta:
                content = chunk.choices[0].delta.get("content", "")
                if content:
                    yield content



