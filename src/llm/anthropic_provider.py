"""
Anthropic LLM provider implementation.
"""
import os
import logging
from collections.abc import AsyncGenerator
from typing import Dict, List, Any

try:
    import anthropic
except ImportError:
    raise ImportError("The 'anthropic' library is required. Please install it using 'pip install anthropic'.")

from .base import LLMProvider


class AnthropicProvider(LLMProvider):
    """
    Anthropic API provider implementation.

    Handles communication with Anthropic's Claude API for text generation.
    """

    # Default base URL for Anthropic API
    DEFAULT_BASE_URL = "https://api.anthropic.com"

    # Default models for Anthropic
    DEFAULT_MODEL = "claude-3-5-sonnet-20241022"

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        """
        Initialize the Anthropic provider.

        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY environment variable)
            base_url: Anthropic API base URL (defaults to ANTHROPIC_BASE_URL environment variable or hardcoded default)
        """
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("Anthropic API key is required")
            
        self.base_url = base_url or os.getenv("ANTHROPIC_BASE_URL", self.DEFAULT_BASE_URL)

        # Initialize Anthropic client
        self.client = anthropic.AsyncAnthropic(
            api_key=self.api_key,
            base_url=self.base_url
        )

        logging.info("Anthropic provider initialized")

    def _prepare_messages(self, messages: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
        """
        Prepare messages for Anthropic API by separating system message.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            
        Returns:
            Tuple of (system_message, filtered_messages)
        """
        system_message = ""
        filtered_messages = []
        
        for message in messages:
            if message["role"] == "system":
                system_message = message["content"]
            else:
                filtered_messages.append(message)
                
        return system_message, filtered_messages

    def _clean_params(self, params: dict[str, object]) -> dict[str, object]:
        """
        Clean parameters to ensure compatibility with Anthropic API.

        Removes unsupported keys that Anthropic does not consume.
        """
        cleaned = params.copy()

        # Remove parameters that aren't supported by Anthropic API
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
        Generate a response using Anthropic's API.

        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            model: Anthropic model identifier (default: claude-3-5-sonnet-20241022)
            temperature: Controls randomness (0.0 to 1.0)
            max_tokens: Maximum number of tokens to generate
            max_completion_tokens: Not used by Anthropic, included for compatibility
            reasoning_effort: Not used by Anthropic, included for compatibility
            **kwargs: Additional API parameters

        Returns:
            Generated text response
        """
        # Use default model if none provided
        if model is None:
            model = os.getenv("ANTHROPIC_DEFAULT_MODEL", self.DEFAULT_MODEL)
            
        # Separate system message from other messages
        system_message, filtered_messages = self._prepare_messages(messages)

        # Prepare request parameters
        params: dict[str, object] = {
            "model": model,
            "messages": filtered_messages,
            "max_tokens": max_tokens or 4096,  # Anthropic requires max_tokens
        }

        # Add system message if provided
        if system_message:
            params["system"] = system_message

        # Add temperature if provided
        if temperature is not None:
            params["temperature"] = temperature

        # Use max_completion_tokens as fallback for max_tokens
        if max_tokens is None and max_completion_tokens is not None:
            params["max_tokens"] = max_completion_tokens

        # Add any additional parameters and clean them
        params.update(kwargs)
        params = self._clean_params(params)

        # Make the API call
        response = await self.client.messages.create(**params)

        # Extract and return the response content
        if response.content and len(response.content) > 0:
            return response.content[0].text
        else:
            logging.warning("Empty response from Anthropic API")
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
        Stream a response using Anthropic's API.

        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            model: Anthropic model identifier (default: claude-3-5-sonnet-20241022)
            temperature: Controls randomness (0.0 to 1.0)
            max_tokens: Maximum number of tokens to generate
            max_completion_tokens: Not used by Anthropic, included for compatibility
            reasoning_effort: Not used by Anthropic, included for compatibility
            **kwargs: Additional API parameters

        Returns:
            AsyncGenerator yielding chunks of the response as they become available
        """
        # No defaulting here; model must be provided by caller per base interface
        logging.info(f"Starting Anthropic streaming with model: {model}")

        # Separate system message from other messages
        system_message, filtered_messages = self._prepare_messages(messages)

        # Prepare request parameters
        params: dict[str, object] = {
            "model": model,
            "messages": filtered_messages,
            "max_tokens": max_tokens or 4096,  # Anthropic requires max_tokens
        }

        # Add system message if provided
        if system_message:
            params["system"] = system_message

        # Add temperature if provided
        if temperature is not None:
            params["temperature"] = temperature

        # Use max_completion_tokens as fallback for max_tokens
        if max_tokens is None and max_completion_tokens is not None:
            params["max_tokens"] = max_completion_tokens

        # Add any additional parameters and clean them
        params.update(kwargs)
        params = self._clean_params(params)

        # Stream the response using Anthropic's async streaming API
        chunk_count = 0
        total_chars = 0

        async with self.client.messages.stream(**params) as stream:
            async for event in stream:
                if event.type == "content_block_delta" and hasattr(event.delta, "text"):
                    text = event.delta.text
                    chunk_count += 1
                    total_chars += len(text)
                    if chunk_count % 10 == 0:
                        logging.debug(f"Anthropic streaming: received {chunk_count} chunks, {total_chars} chars so far")
                    yield text

        logging.info(f"Anthropic streaming complete: {chunk_count} chunks, {total_chars} chars total")