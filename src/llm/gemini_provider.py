"""
Google Gemini LLM provider implementation.
"""
import os
import logging
import asyncio
import google.generativeai as genai
from collections.abc import AsyncGenerator

from .base import LLMProvider


class GeminiProvider(LLMProvider):
    """
    Google Gemini API provider implementation.

    Handles communication with Google's Gemini API for text generation.
    """

    # Default base URL for Gemini API
    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"
    
    # Models that might require special handling
    THINKING_MODELS: list[str] = []

    # Default models for Gemini
    DEFAULT_MODEL = "gemini-2.5-pro"

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        """
        Initialize the Gemini provider.

        Args:
            api_key: Gemini API key (defaults to GEMINI_API_KEY environment variable)
            base_url: Gemini API base URL (defaults to GEMINI_BASE_URL environment variable or hardcoded default)
        """
        # Setup API key
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("Gemini API key is required")
            
        self.base_url = base_url or os.getenv("GEMINI_BASE_URL", self.DEFAULT_BASE_URL)

        # Configure the Google GenAI client
        genai.configure(api_key=self.api_key)

    def _get_model(self, model_name: str):
        """
        Get the Gemini model instance based on model name.

        Args:
            model_name: Name of the Gemini model to use

        Returns:
            Gemini model instance
        """
        return genai.GenerativeModel(model_name)

    def _is_thinking_model(self, model: str) -> bool:
        """Check if the model is a thinking model."""
        return model in self.THINKING_MODELS

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
        Generate a response using Gemini's API.

        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            model: Gemini model identifier (default: gemini-1.5-pro)
            temperature: Controls randomness (0.0 to 1.0)
            max_tokens: Maximum number of tokens to generate
            max_completion_tokens: Not used by Gemini, included for compatibility
            reasoning_effort: Not used by Gemini, included for compatibility
            **kwargs: Additional Gemini API parameters

        Returns:
            Generated text response
        """
        # Use default model if none provided
        if model is None:
            model = os.getenv("GEMINI_DEFAULT_MODEL", self.DEFAULT_MODEL)
            
        # Convert OpenAI-style messages to Gemini format
        gemini_messages = self._convert_messages_to_gemini_format(messages)

        # Initialize the model
        gemini_model = self._get_model(model)

        # Prepare generation config
        generation_config: dict[str, object] = {}

        # Add temperature if provided
        if temperature is not None:
            generation_config["temperature"] = temperature

        # Add max output tokens if provided
        if max_tokens is not None:
            generation_config["max_output_tokens"] = max_tokens
        elif max_completion_tokens is not None:
            generation_config["max_output_tokens"] = max_completion_tokens

        # Add any additional parameters
        generation_config.update(kwargs.get("generation_config", {}))

        # Create a wrapper around the synchronous API call to make it async
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: gemini_model.generate_content(
                gemini_messages,
                generation_config=generation_config,
                safety_settings=kwargs.get("safety_settings"),
            )
        )

        # Check for a successful response
        if hasattr(response, "text"):
            return response.text
        else:
            logging.error(f"Unexpected response format from Gemini: {response}")
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
        Stream a response using Gemini's API.

        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            model: Gemini model identifier (default: gemini-1.5-pro)
            temperature: Controls randomness (0.0 to 1.0)
            max_tokens: Maximum number of tokens to generate
            max_completion_tokens: Not used by Gemini, included for compatibility
            reasoning_effort: Not used by Gemini, included for compatibility
            **kwargs: Additional Gemini API parameters

        Returns:
            AsyncGenerator yielding chunks of the response as they become available
        """
        logging.info(f"Starting Gemini streaming with model: {model}")

        # Convert OpenAI-style messages to Gemini format
        gemini_messages = self._convert_messages_to_gemini_format(messages)

        # Initialize the model
        gemini_model = self._get_model(model)

        # Prepare generation config
        generation_config: dict[str, object] = {}

        # Add temperature if provided
        if temperature is not None:
            generation_config["temperature"] = temperature

        # Add max output tokens if provided
        if max_tokens is not None:
            generation_config["max_output_tokens"] = max_tokens
        elif max_completion_tokens is not None:
            generation_config["max_output_tokens"] = max_completion_tokens

        # Add any additional parameters
        generation_config.update(kwargs.get("generation_config", {}))

        # Create a wrapper around the synchronous API call to make it stream
        # Run the initial part synchronously because Gemini's Python SDK doesn't have native async support
        # We need to use run_in_executor to prevent blocking the event loop
        loop = asyncio.get_event_loop()
        stream_response = await loop.run_in_executor(
            None,
            lambda: gemini_model.generate_content(
                gemini_messages,
                generation_config=generation_config,
                safety_settings=kwargs.get("safety_settings"),
                stream=True
            )
        )

        # Stream the content
        chunk_count = 0
        async for chunk in self._stream_async_generator(stream_response):
            if hasattr(chunk, "text") and chunk.text:
                chunk_count += 1
                if chunk_count % 10 == 0:
                    logging.debug(f"Gemini streaming: received {chunk_count} chunks so far")
                yield chunk.text

        logging.info(f"Gemini streaming complete: {chunk_count} chunks total")

    def _convert_messages_to_gemini_format(self, messages: list[dict[str, str]]) -> list[dict[str, object]] | str:
        """
        Convert OpenAI-style messages to Gemini format.

        Args:
            messages: List of message dictionaries with 'role' and 'content' keys

        Returns:
            List of messages in Gemini format or a string for single message
        """
        # For simple use cases, we can just extract the content
        # This is a simplified version, as Gemini's API accepts various formats
        if len(messages) == 1:
            return messages[0]["content"]

        # For chat format, we can use "contents" with role mapping
        # This is a simplified approach and may need refinement for specific use cases
        role_mapping = {
            "system": "user",  # Gemini doesn't have a distinct system role
            "user": "user",
            "assistant": "model"
        }

        # Create a proper chat history
        gemini_messages: list[dict[str, object]] = []
        for msg in messages:
            role = role_mapping.get(msg["role"], "user")
            gemini_messages.append({"role": role, "parts": [{"text": msg["content"]}]})

        return gemini_messages

    async def _stream_async_generator(self, sync_generator):
        """
        Convert a synchronous generator to an async generator.

        Args:
            sync_generator: A synchronous generator to convert

        Returns:
            An async generator that yields the same items
        """
        loop = asyncio.get_event_loop()
        for item in sync_generator:
            # Yield control to the event loop briefly to avoid blocking
            await asyncio.sleep(0)
            yield item