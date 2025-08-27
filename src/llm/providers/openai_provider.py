"""
OpenAI LLM provider implementation.
"""
import os
import logging
from collections.abc import AsyncGenerator
from openai import AsyncOpenAI
from .base import LLMProvider


class OpenAIProvider(LLMProvider):
    """
    OpenAI API provider implementation.

    Handles communication with OpenAI's API for text generation.
    """

    # Default base URL for OpenAI API
    DEFAULT_BASE_URL = "https://api.openai.com/v1"
    
    # Models that require special handling (thinking models)
    THINKING_MODELS = ["o3-mini", "o1-mini", "o1", "o4-mini", "o3", "gpt-5", "gpt-5-mini", "gpt-5-nano"]
    
    DEFAULT_MODEL = "gpt-5"

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        """
        Initialize the OpenAI provider.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY environment variable)
            base_url: OpenAI API base URL (defaults to OPENAI_BASE_URL environment variable or hardcoded default)
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key is required")
            
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL", self.DEFAULT_BASE_URL)

        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

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
        Generate a response using OpenAI's API.

        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            model: OpenAI model identifier (default: gpt-4o)
            temperature: Controls randomness (0.0 to 1.0), not used for thinking models
            max_tokens: Maximum number of tokens to generate (for non-thinking models)
            max_completion_tokens: Maximum number of tokens to generate (for thinking models)
            reasoning_effort: Reasoning effort for thinking models (low, medium, high)
            **kwargs: Additional OpenAI API parameters

        Returns:
            Generated text response
        """
        # Use default model if none provided
        if model is None:
            model = os.getenv("OPENAI_DEFAULT_MODEL", self.DEFAULT_MODEL)
            
        params: dict[str, object] = {
            "model": model,
            "messages": messages,
        }

        is_thinking = self._is_thinking_model(model)

        # For thinking models (o1, o3, etc.)
        if is_thinking:
            logging.debug(f"Using thinking model: {model}")

            # Handle reasoning_effort parameter
            if reasoning_effort:
                params["reasoning_effort"] = reasoning_effort
                logging.debug(f"Setting reasoning_effort={reasoning_effort} for model {model}")

            # Handle token limit for thinking models
            if max_completion_tokens is not None:
                params["max_completion_tokens"] = max_completion_tokens
            elif max_tokens is not None:
                logging.debug(f"Using max_tokens={max_tokens} as max_completion_tokens for model {model}")
                params["max_completion_tokens"] = max_tokens
        else:
            # For standard models (gpt-4o, etc.)
            # Set temperature
            if temperature is not None:
                params["temperature"] = temperature

            # Handle token limit for regular models
            if max_tokens is not None:
                logging.debug(f"Using max_tokens={max_tokens} for model {model}")
                params["max_tokens"] = max_tokens

        # Add any additional parameters
        params.update(kwargs)

        response = await self.client.chat.completions.create(**params)
        return response.choices[0].message.content or ""

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
        Stream a response using OpenAI's API.

        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            model: OpenAI model identifier (default: gpt-4o)
            temperature: Controls randomness (0.0 to 1.0), not used for thinking models
            max_tokens: Maximum number of tokens to generate (for non-thinking models)
            max_completion_tokens: Maximum number of tokens to generate (for thinking models)
            reasoning_effort: Reasoning effort for thinking models (low, medium, high)
            **kwargs: Additional OpenAI API parameters

        Returns:
            AsyncGenerator yielding chunks of the response as they become available
        """
        # Use default model if none provided
        if model is None:
            model = os.getenv("OPENAI_DEFAULT_MODEL", self.DEFAULT_MODEL)
            
        # logging.info(f"Starting OpenAI streaming with model: {model}")

        params: dict[str, object] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }

        is_thinking = self._is_thinking_model(model)

        # For thinking models (o1, o3, etc.)
        if is_thinking:
            logging.debug(f"Using thinking model: {model}")

            # Handle reasoning_effort parameter
            if reasoning_effort:
                params["reasoning_effort"] = reasoning_effort
                logging.debug(f"Setting reasoning_effort={reasoning_effort} for model {model}")

            # Handle token limit for thinking models
            if max_completion_tokens is not None:
                params["max_completion_tokens"] = max_completion_tokens
            elif max_tokens is not None:
                logging.debug(f"Using max_tokens={max_tokens} as max_completion_tokens for model {model}")
                params["max_completion_tokens"] = max_tokens
        else:
            # For standard models (gpt-4o, etc.)
            # Set temperature
            if temperature is not None:
                params["temperature"] = temperature

            # Handle token limit for regular models
            if max_tokens is not None:
                logging.debug(f"Using max_tokens={max_tokens} for model {model}")
                params["max_tokens"] = max_tokens

        # Add any additional parameters
        params.update(kwargs)

        chunk_count = 0
        total_tokens = 0

        stream = await self.client.chat.completions.create(**params)

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                chunk_content = chunk.choices[0].delta.content
                chunk_count += 1
                total_tokens += len(chunk_content)
                if chunk_count % 10 == 0:
                    logging.debug(f"OpenAI streaming: received {chunk_count} chunks, {total_tokens} chars so far")
                yield chunk_content

        logging.debug(f"OpenAI streaming complete: {chunk_count} chunks, {total_tokens} chars total")