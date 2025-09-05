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
from .providers import (
    OpenAIProvider,
    GeminiProvider,
    OpenRouterProvider,
    AnthropicProvider,
    DeepSeekProvider,
    GroqProvider,
    TogetherProvider,
    XAIProvider,
    OllamaProvider,
    LMStudioProvider,
    AWSBedrockProvider,
    AzureOpenAIProvider,
    AzureOpenAIStructuredProvider,
    LangChainProvider,
    LiteLLMProvider,
    OpenAIStructuredProvider,
    SarvamProvider,
    VLLMProvider,
    LlamaCppProvider,
    LMDeployProvider,
)


class LLM:
    """
    LLM abstraction class that routes requests to the appropriate provider.

    Serves as a factory for creating and managing different LLM providers,
    providing a unified interface for text generation with type-safe models.
    """

    PROVIDER_MAPPING = {
        "openai": OpenAIProvider,
        "gemini": GeminiProvider,
        "openrouter": OpenRouterProvider,
        "anthropic": AnthropicProvider,
        "deepseek": DeepSeekProvider,
        "groq": GroqProvider,
        "together": TogetherProvider,
        "xai": XAIProvider,
        "ollama": OllamaProvider,
        "lmstudio": LMStudioProvider,
        "aws_bedrock": AWSBedrockProvider,
        "azure_openai": AzureOpenAIProvider,
        "azure_openai_structured": AzureOpenAIStructuredProvider,
        "langchain": LangChainProvider,
        "litellm": LiteLLMProvider,
        "openai_structured": OpenAIStructuredProvider,
        "sarvam": SarvamProvider,
        "vllm": VLLMProvider,
        "llamacpp": LlamaCppProvider,
        "lmdeploy": LMDeployProvider,
    }

    def __init__(
        self,
        provider: str,
        api_key: str | None = None,
        model_mapping: dict[str, str] | None = None,
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

        if self.provider_name not in self.PROVIDER_MAPPING:
            raise ValueError(f"Unsupported provider: {provider}. Must be one of: {', '.join(self.PROVIDER_MAPPING.keys())}")

        # Initialize the provider
        provider_class = self.PROVIDER_MAPPING[self.provider_name]
        self.provider: LLMProvider = provider_class(api_key=api_key, **kwargs)

    async def generate(
        self,
        messages: list[MessageParam],
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
            messages=messages,  # type: ignore - TypedDict compatibility
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
        
        # Call the provider with the validated request
        return await self.provider.generate(request)

    async def stream_generate(
        self,
        messages: list[MessageParam],
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
            messages=messages,  # type: ignore - TypedDict compatibility
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




