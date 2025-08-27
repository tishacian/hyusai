"""
Main LLM class providing a unified interface for different LLM providers.
"""
from collections.abc import AsyncGenerator

from .base import LLMProvider
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
    providing a unified interface for text generation.
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
        self.provider = provider_class(api_key=api_key, **kwargs)



    def _prepare_generation_params(self, max_tokens: int | None, temperature: float | None = 0.0, **kwargs) -> dict[str, object]:
        """
        Prepare parameters for generation.

        Args:
            max_tokens: Maximum number of tokens to generate
            temperature: Controls randomness (0.0 to 1.0)
            **kwargs: Additional generation parameters

        Returns:
            Dictionary of generation parameters
        """
        params: dict[str, object] = kwargs.copy()

        # Remove 'provider' parameter if it exists to avoid passing it to the API
        if 'provider' in params:
            del params['provider']

        # Add standard parameters
        if max_tokens is not None:
            params["max_tokens"] = max_tokens

        if temperature is not None:
            params["temperature"] = temperature

        return params

    async def generate(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs
    ) -> str:
        """
        Generate a response using the configured provider.

        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            model: Specific model name (required, e.g., "gpt-4o", "claude-3-5-sonnet-20241022")
            temperature: Controls randomness (0.0 to 1.0, ignored for thinking models)
            max_tokens: Maximum number of tokens to generate
            **kwargs: Additional provider-specific parameters

        Returns:
            Generated text response
        """
        params = self._prepare_generation_params(max_tokens, temperature, **kwargs)

        return await self.provider.generate(
            messages=messages,
            model=model,
            **params
        )

    async def stream_generate(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """
        Generate a streaming response using the configured provider.

        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            model: Specific model name (required, e.g., "gpt-4o", "claude-3-5-sonnet-20241022")
            temperature: Controls randomness (0.0 to 1.0, ignored for thinking models)
            max_tokens: Maximum number of tokens to generate
            **kwargs: Additional provider-specific parameters

        Returns:
            AsyncGenerator yielding chunks of the response as they become available
        """
        params = self._prepare_generation_params(max_tokens, temperature, **kwargs)

        async for chunk in self.provider.stream_generate(
            messages=messages,
            model=model,
            **params
        ):
            yield chunk