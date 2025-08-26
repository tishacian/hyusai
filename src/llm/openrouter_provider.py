"""
OpenRouter LLM provider implementation.
"""
import os
import logging
from collections.abc import AsyncGenerator
from openai import AsyncOpenAI
from .base import LLMProvider


class OpenRouterProvider(LLMProvider):
    """
    OpenRouter API provider implementation.

    Handles communication with OpenRouter's API for accessing multiple LLM providers
    through a unified interface compatible with OpenAI's API.
    """

    # Base URL for OpenRouter API
    DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

    # Default models - these are the model IDs used in OpenRouter
    DEFAULT_MODEL = "z-ai/glm-4.5"

    def __init__(
        self,
        api_key: str | None = None,
        site_url: str | None = None,
        site_name: str | None = None,
        base_url: str | None = None
    ):
        """
        Initialize the OpenRouter provider.

        Args:
            api_key: OpenRouter API key (defaults to OPENROUTER_API_KEY environment variable)
            site_url: Your site URL for rankings on openrouter.ai
            site_name: Your site name for rankings on openrouter.ai
            base_url: OpenRouter API base URL (defaults to OPENROUTER_BASE_URL environment variable or hardcoded default)
        """
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError("OpenRouter API key is required")

        # Store site information for headers
        self.site_url = site_url or os.getenv("OPENROUTER_SITE_URL", "")
        self.site_name = site_name or os.getenv("OPENROUTER_SITE_NAME", "")
        
        # Set base URL
        self.base_url = base_url or os.getenv("OPENROUTER_BASE_URL", self.DEFAULT_BASE_URL)

        # Initialize AsyncOpenAI client with OpenRouter base URL
        self.client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key
        )

        logging.info("OpenRouter provider initialized")

    def _get_headers(self) -> dict[str, str]:
        """
        Get the extra headers required for OpenRouter API calls.

        Returns:
            Dictionary of HTTP headers
        """
        headers = {}

        # Add site URL if available
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url

        # Add site name if available
        if self.site_name:
            headers["X-Title"] = self.site_name

        return headers

    def _clean_params(self, params: dict[str, object]) -> dict[str, object]:
        """
        Clean parameters to ensure compatibility with OpenRouter API.

        Removes unsupported keys that OpenRouter does not consume, since we
        normalize these at higher layers (LLM facade) already.
        """
        cleaned = params.copy()

        # Remove parameters that aren't supported/necessary for OpenRouter API
        for key in ("provider", "reasoning_effort", "max_completion_tokens"):
            cleaned.pop(key, None)

        return cleaned

    async def generate(
        self,
        messages: list[dict[str, str]],
        model: str = None,  # Will be set to default model
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
        max_completion_tokens: int | None = None,
        reasoning_effort: str | None = None,
        **kwargs
    ) -> str:
        """
        Generate a response using OpenRouter's API.

        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            model: OpenRouter model identifier (default: z-ai/glm-4.5)
            temperature: Controls randomness (0.0 to 1.0)
            max_tokens: Maximum number of tokens to generate
            max_completion_tokens: Not used by OpenRouter, included for compatibility
            reasoning_effort: Not used by OpenRouter, included for compatibility
            **kwargs: Additional API parameters

        Returns:
            Generated text response
        """
        # Use default model if none provided
        if model is None:
            model = os.getenv("OPENROUTER_DEFAULT_MODEL", self.DEFAULT_MODEL)
            
        # Prepare request parameters
        params: dict[str, object] = {
            "model": model,
            "messages": messages,
            "extra_headers": self._get_headers()
        }

        # Add temperature if provided
        if temperature is not None:
            params["temperature"] = temperature

        # Add max tokens if provided
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        elif max_completion_tokens is not None:
            # Use max_completion_tokens as fallback
            params["max_tokens"] = max_completion_tokens

        # Add any additional parameters and clean them
        params.update(kwargs)
        params = self._clean_params(params)

        # Make the API call
        response = await self.client.chat.completions.create(**params)

        # Extract and return the response content
        if response.choices and len(response.choices) > 0:
            return response.choices[0].message.content or ""
        else:
            logging.warning("Empty response from OpenRouter API")
            return ""

    async def stream_generate(
        self,
        messages: list[dict[str, str]],
        model: str,  # Required to match base class signature
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
        max_completion_tokens: int | None = None,
        reasoning_effort: str | None = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """
        Stream a response using OpenRouter's API.

        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            model: OpenRouter model identifier (default: z-ai/glm-4.5)
            temperature: Controls randomness (0.0 to 1.0)
            max_tokens: Maximum number of tokens to generate
            max_completion_tokens: Not used by OpenRouter, included for compatibility
            reasoning_effort: Not used by OpenRouter, included for compatibility
            **kwargs: Additional API parameters

        Returns:
            AsyncGenerator yielding chunks of the response as they become available
        """
        # No defaulting here; model must be provided by caller per base interface
        logging.info(f"Starting OpenRouter streaming with model: {model}")

        # Prepare request parameters
        params: dict[str, object] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "extra_headers": self._get_headers()
        }

        # Add temperature if provided
        if temperature is not None:
            params["temperature"] = temperature

        # Add max tokens if provided
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        elif max_completion_tokens is not None:
            # Use max_completion_tokens as fallback
            params["max_tokens"] = max_completion_tokens

        # Add any additional parameters and clean them
        params.update(kwargs)
        params = self._clean_params(params)

        # Stream the response
        chunk_count = 0
        total_tokens = 0

        stream = await self.client.chat.completions.create(**params)

        async for chunk in stream:
            if chunk.choices and len(chunk.choices) > 0 and chunk.choices[0].delta.content:
                chunk_content = chunk.choices[0].delta.content
                chunk_count += 1
                total_tokens += len(chunk_content)
                if chunk_count % 10 == 0:
                    logging.debug(f"OpenRouter streaming: received {chunk_count} chunks, {total_tokens} chars so far")
                yield chunk_content

        logging.info(f"OpenRouter streaming complete: {chunk_count} chunks, {total_tokens} chars total")