"""
OpenRouter LLM provider implementation.
"""
import os
import time
import logging
from collections.abc import AsyncGenerator
from openai import AsyncOpenAI
from ..base import LLMProvider
from ..models import (
    CompletionRequest,
    CompletionResponse,
    Choice,
    Message,
    MessageRole,
    StreamingResponse,
    StreamChoice,
    TokenUsage,
)


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

        logging.debug("OpenRouter provider initialized")

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

    def _calculate_costs(self, usage: TokenUsage, model: str) -> TokenUsage:
        """
        Calculate costs based on model pricing.
        
        Args:
            usage: Token usage object
            model: Model name
            
        Returns:
            Updated usage with costs (OpenRouter handles billing separately)
        """
        # OpenRouter handles its own billing, so we don't calculate costs here
        usage.prompt_cost = 0.0
        usage.completion_cost = 0.0
        usage.total_cost = 0.0
        
        return usage

    async def generate(
        self,
        request: CompletionRequest
    ) -> CompletionResponse:
        """
        Generate a response using OpenRouter's API.

        Args:
            request: Validated CompletionRequest with all parameters

        Returns:
            CompletionResponse with choices, usage, and metadata
        """
        # Use default model if none provided
        model = request.model or os.getenv("OPENROUTER_DEFAULT_MODEL", self.DEFAULT_MODEL)
            
        # Track timing
        start_time = time.time()
        
        # Prepare request parameters
        params: dict[str, object] = {
            "model": model,
            "messages": request.messages_as_dicts(),
            "extra_headers": self._get_headers()
        }

        # Add temperature if provided
        if request.temperature is not None:
            params["temperature"] = request.temperature

        # Add max tokens if provided
        if request.max_tokens is not None:
            params["max_tokens"] = request.max_tokens
        elif request.max_completion_tokens is not None:
            # Use max_completion_tokens as fallback
            params["max_tokens"] = request.max_completion_tokens

        # Add optional parameters
        if request.top_p is not None:
            params["top_p"] = request.top_p
        
        if request.stop:
            params["stop"] = request.stop
        
        if request.presence_penalty is not None:
            params["presence_penalty"] = request.presence_penalty
        
        if request.frequency_penalty is not None:
            params["frequency_penalty"] = request.frequency_penalty
        
        if request.seed is not None:
            params["seed"] = request.seed
        if request.n is not None:
            params["n"] = request.n
        if request.logit_bias is not None:
            params["logit_bias"] = request.logit_bias
        if request.user:
            params["user"] = request.user

        # Clean parameters
        params = self._clean_params(params)

        # Make the API call
        response = await self.client.chat.completions.create(**params)
        
        # Calculate response time
        response_ms = (time.time() - start_time) * 1000

        # Convert to our typed response
        choices = []
        for choice in response.choices:
            message = Message(
                role=MessageRole.ASSISTANT,
                content=choice.message.content
            )
            choices.append(
                Choice(
                    index=choice.index,
                    message=message,
                    finish_reason=choice.finish_reason
                )
            )

        # Build usage info
        usage = None
        if hasattr(response, 'usage') and response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens
            )
            # Calculate costs (OpenRouter handles billing separately)
            usage = self._calculate_costs(usage, model)

        return CompletionResponse(
            id=response.id,
            model=response.model,
            created=response.created,
            choices=choices,
            usage=usage,
            response_ms=response_ms
        )

    async def stream_generate(
        self,
        request: CompletionRequest
    ) -> AsyncGenerator[StreamingResponse, None]:
        """
        Stream a response using OpenRouter's API.

        Args:
            request: Validated CompletionRequest with all parameters

        Returns:
            AsyncGenerator yielding StreamingResponse chunks
        """
        # Use the model from request (required by base interface)
        model = request.model
        logging.debug(f"Starting OpenRouter streaming with model: {model}")

        # Prepare request parameters
        params: dict[str, object] = {
            "model": model,
            "messages": request.messages_as_dicts(),
            "stream": True,
            "extra_headers": self._get_headers()
        }

        # Add temperature if provided
        if request.temperature is not None:
            params["temperature"] = request.temperature

        # Add max tokens if provided
        if request.max_tokens is not None:
            params["max_tokens"] = request.max_tokens
        elif request.max_completion_tokens is not None:
            # Use max_completion_tokens as fallback
            params["max_tokens"] = request.max_completion_tokens

        # Add optional parameters
        if request.top_p is not None:
            params["top_p"] = request.top_p
        
        if request.stop:
            params["stop"] = request.stop
        
        if request.presence_penalty is not None:
            params["presence_penalty"] = request.presence_penalty
        
        if request.frequency_penalty is not None:
            params["frequency_penalty"] = request.frequency_penalty
        
        if request.seed is not None:
            params["seed"] = request.seed

        # Clean parameters
        params = self._clean_params(params)

        # Stream the response
        chunk_count = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0

        stream = await self.client.chat.completions.create(**params)

        async for chunk in stream:
            chunk_count += 1
            
            # Convert to our typed streaming response
            choices = []
            for choice in chunk.choices:
                delta_dict = {}
                
                if choice.delta.content is not None:
                    delta_dict["content"] = choice.delta.content
                
                if hasattr(choice.delta, 'role') and choice.delta.role:
                    delta_dict["role"] = choice.delta.role
                
                choices.append(
                    StreamChoice(
                        index=choice.index,
                        delta=delta_dict,
                        finish_reason=choice.finish_reason
                    )
                )
            
            # Build usage info if present (usually in the last chunk)
            usage = None
            if hasattr(chunk, 'usage') and chunk.usage:
                total_prompt_tokens = chunk.usage.prompt_tokens
                total_completion_tokens = chunk.usage.completion_tokens
                
                usage = TokenUsage(
                    prompt_tokens=total_prompt_tokens,
                    completion_tokens=total_completion_tokens,
                    total_tokens=total_prompt_tokens + total_completion_tokens
                )
                
                # Calculate costs (OpenRouter handles billing separately)
                usage = self._calculate_costs(usage, model)
            
            yield StreamingResponse(
                id=chunk.id,
                model=chunk.model,
                created=chunk.created,
                choices=choices,
                usage=usage
            )

        logging.debug(f"OpenRouter streaming complete: {chunk_count} chunks")
