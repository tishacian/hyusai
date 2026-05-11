"""
OpenAI LLM provider implementation.
"""
import os
import time
import logging
from collections.abc import AsyncGenerator
from typing import Any

try:  # Import lazily enough for tests/dev envs without the optional package.
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover - exercised in minimal local envs
    AsyncOpenAI = None  # type: ignore[assignment]

from app.core.config import settings
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


class OpenAIProvider(LLMProvider):
    """
    OpenAI API provider implementation.

    Handles communication with OpenAI's API for text generation.
    Uses Pydantic models for type-safe request/response handling.
    """

    # Default base URL for OpenAI API
    DEFAULT_BASE_URL = "https://api.openai.com/v1"
    
    # Models that require special handling (thinking models)
    THINKING_MODELS = ["o3-mini", "o1-mini", "o1", "o4-mini", "o3", "gpt-5", "gpt-5-mini", "gpt-5-nano"]
    
    DEFAULT_MODEL = "gpt-5"
    
    # Model pricing per 1000 tokens
    MODEL_PRICING = {
        "gpt-4": {"input": 0.03, "output": 0.06},
        "gpt-4-32k": {"input": 0.06, "output": 0.12},
        "gpt-4-turbo": {"input": 0.01, "output": 0.03},
        "gpt-4o": {"input": 0.005, "output": 0.015},
        "gpt-3.5-turbo": {"input": 0.0015, "output": 0.002},
        "o1-mini": {"input": 0.003, "output": 0.012},
        "o1": {"input": 0.015, "output": 0.06},
    }

    def __init__(self, api_key=None, base_url=None):
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
        if AsyncOpenAI is None:
            raise RuntimeError("OpenAI package not installed. Install with: pip install openai")

        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

    def _is_thinking_model(self, model: str) -> bool:
        """Check if the model is a thinking model."""
        return any(model == item or model.startswith(f"{item}-") for item in self.THINKING_MODELS)

    def _uses_responses_api(self) -> bool:
        return bool(settings.openai_responses_api_enabled)
    
    def _prepare_api_params(self, request: CompletionRequest, streaming: bool = False) -> dict:
        """
        Prepare parameters for OpenAI API call.
        
        Args:
            request: Validated CompletionRequest
            streaming: Whether this is for streaming
            
        Returns:
            Dictionary of parameters for OpenAI API
        """
        # Use default model if not specified
        model = request.model or os.getenv("OPENAI_DEFAULT_MODEL", self.DEFAULT_MODEL)
        
        params = {
            "model": model,
            "messages": request.messages_as_dicts(),
        }
        
        if streaming:
            params["stream"] = True
        
        is_thinking = self._is_thinking_model(model)
        
        # For thinking models (o1, o3, etc.)
        if is_thinking:
            logging.debug(f"Using thinking model: {model}")
            
            if request.reasoning_effort:
                params["reasoning_effort"] = request.reasoning_effort
            
            if request.max_completion_tokens is not None:
                params["max_completion_tokens"] = request.max_completion_tokens
            elif request.max_tokens is not None:
                params["max_completion_tokens"] = request.max_tokens
        else:
            # For standard models
            if request.temperature is not None:
                params["temperature"] = request.temperature
            
            if request.max_tokens is not None:
                params["max_tokens"] = request.max_tokens
        
        # Add other common parameters
        if request.top_p is not None:
            params["top_p"] = request.top_p
        if request.n is not None:
            params["n"] = request.n
        if request.presence_penalty is not None:
            params["presence_penalty"] = request.presence_penalty
        if request.frequency_penalty is not None:
            params["frequency_penalty"] = request.frequency_penalty
        if request.logit_bias is not None:
            params["logit_bias"] = request.logit_bias
        if request.stop:
            params["stop"] = request.stop
        if request.response_format:
            params["response_format"] = request.response_format
        if request.seed is not None:
            params["seed"] = request.seed
        if request.logprobs:
            params["logprobs"] = request.logprobs
        if request.top_logprobs is not None:
            params["top_logprobs"] = request.top_logprobs
        if request.user:
            params["user"] = request.user
        
        return params

    def _prepare_responses_params(self, request: CompletionRequest) -> dict:
        """Prepare parameters for OpenAI Responses API calls."""
        model = request.model or os.getenv("OPENAI_DEFAULT_MODEL", self.DEFAULT_MODEL)
        messages = request.messages_as_dicts()
        instructions = None
        input_messages = []
        for message in messages:
            role = message.get("role")
            content = message.get("content", "")
            if role == "system" and instructions is None:
                instructions = content
                continue
            input_messages.append(
                {
                    "role": "assistant" if role == "assistant" else "user",
                    "content": content,
                }
            )

        params: dict[str, Any] = {
            "model": model,
            "input": input_messages or [{"role": "user", "content": ""}],
            "store": False,
        }
        if instructions:
            params["instructions"] = instructions

        is_thinking = self._is_thinking_model(model)
        if not is_thinking and request.temperature is not None:
            params["temperature"] = request.temperature
        if request.max_completion_tokens is not None:
            params["max_output_tokens"] = request.max_completion_tokens
        elif request.max_tokens is not None:
            params["max_output_tokens"] = request.max_tokens
        if request.top_p is not None:
            params["top_p"] = request.top_p
        if request.user:
            params["user"] = request.user
        if (
            is_thinking
            and settings.openai_responses_include_reasoning_encrypted_content
        ):
            params["include"] = ["reasoning.encrypted_content"]
        return params

    @staticmethod
    def _response_output_text(response: Any) -> str:
        text = getattr(response, "output_text", None)
        if text:
            return text
        parts: list[str] = []
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                content_text = getattr(content, "text", None)
                if content_text:
                    parts.append(content_text)
        return "".join(parts)

    @staticmethod
    def _responses_usage(response: Any) -> TokenUsage | None:
        usage = getattr(response, "usage", None)
        if not usage:
            return None
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", input_tokens + output_tokens) or 0)
        return TokenUsage(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            total_tokens=total_tokens,
        )
    
    def _calculate_costs(self, usage: TokenUsage, model: str) -> TokenUsage:
        """
        Calculate costs based on model pricing.
        
        Args:
            usage: Token usage object
            model: Model name
            
        Returns:
            Updated usage with costs
        """
        # Find matching pricing
        for model_key, pricing in self.MODEL_PRICING.items():
            if model_key in model.lower():
                usage.prompt_cost = usage.prompt_tokens * pricing["input"] / 1000
                usage.completion_cost = usage.completion_tokens * pricing["output"] / 1000
                usage.total_cost = usage.prompt_cost + usage.completion_cost
                break
        
        return usage

    async def generate(
        self,
        request: CompletionRequest
    ) -> CompletionResponse:
        """
        Generate a response using OpenAI's API.

        Args:
            request: Validated CompletionRequest with all parameters

        Returns:
            CompletionResponse with choices, usage, and metadata
        """
        # Track timing
        start_time = time.time()

        if self._uses_responses_api():
            params = self._prepare_responses_params(request)
            response = await self.client.responses.create(**params)
            response_ms = (time.time() - start_time) * 1000
            model = getattr(response, "model", request.model)
            usage = self._responses_usage(response)
            if usage:
                usage = self._calculate_costs(usage, model)
            return CompletionResponse(
                id=getattr(response, "id", request.request_id),
                model=model,
                created=int(getattr(response, "created_at", time.time()) or time.time()),
                choices=[
                    Choice(
                        index=0,
                        message=Message(
                            role=MessageRole.ASSISTANT,
                            content=self._response_output_text(response),
                        ),
                        finish_reason=getattr(response, "status", None),
                    )
                ],
                usage=usage,
                response_ms=response_ms,
            )

        # Prepare API parameters
        params = self._prepare_api_params(request)
        
        # Make the API call
        response = await self.client.chat.completions.create(**params)
        
        # Calculate response time
        response_ms = (time.time() - start_time) * 1000
        
        # Convert OpenAI response to our typed response
        choices = []
        for choice in response.choices:
            message = Message(
                role=MessageRole.ASSISTANT,
                content=choice.message.content,
            )
            
            # Tool/function calls are not supported in this repo
            
            choices.append(
                Choice(
                    index=choice.index,
                    message=message,
                    finish_reason=choice.finish_reason,
                    logprobs=choice.logprobs if hasattr(choice, 'logprobs') else None
                )
            )
        
        # Build usage info
        usage = None
        if response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens
            )
            
            # Add reasoning tokens if present (for thinking models)
            if hasattr(response.usage, 'reasoning_tokens'):
                usage.reasoning_tokens = response.usage.reasoning_tokens
            
            # Calculate costs
            usage = self._calculate_costs(usage, response.model)
        
        return CompletionResponse(
            id=response.id,
            model=response.model,
            created=response.created,
            choices=choices,
            usage=usage,
            system_fingerprint=response.system_fingerprint if hasattr(response, 'system_fingerprint') else None,
            response_ms=response_ms
        )

    async def stream_generate(
        self,
        request: CompletionRequest
    ) -> AsyncGenerator[StreamingResponse, None]:
        """
        Stream a response using OpenAI's API.

        Args:
            request: Validated CompletionRequest with all parameters

        Returns:
            AsyncGenerator yielding StreamingResponse chunks
        """
        if self._uses_responses_api():
            params = self._prepare_responses_params(request)
            model = params["model"]
            created = int(time.time())
            chunk_count = 0
            async with self.client.responses.stream(**params) as stream:
                async for event in stream:
                    if getattr(event, "type", None) != "response.output_text.delta":
                        continue
                    delta = getattr(event, "delta", "") or ""
                    if not delta:
                        continue
                    chunk_count += 1
                    yield StreamingResponse(
                        id=getattr(event, "response_id", request.request_id),
                        model=model,
                        created=created,
                        choices=[
                            StreamChoice(
                                index=0,
                                delta={"content": delta},
                                finish_reason=None,
                            )
                        ],
                    )
            logging.debug(f"Responses streaming complete: {chunk_count} chunks")
            return

        # Prepare API parameters
        params = self._prepare_api_params(request, streaming=True)
        
        # Make the streaming API call
        stream = await self.client.chat.completions.create(**params)
        
        chunk_count = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        
        # Process each chunk
        async for chunk in stream:
            chunk_count += 1
            
            # Convert OpenAI chunk to our typed streaming response
            choices = []
            for choice in chunk.choices:
                delta_dict = {}
                
                if choice.delta.content is not None:
                    delta_dict["content"] = choice.delta.content
                
                if hasattr(choice.delta, 'role') and choice.delta.role:
                    delta_dict["role"] = choice.delta.role
                
                # Tool/function deltas are not supported
                
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
                
                # Add reasoning tokens if present
                if hasattr(chunk.usage, 'reasoning_tokens'):
                    usage.reasoning_tokens = chunk.usage.reasoning_tokens
                
                # Calculate costs
                usage = self._calculate_costs(usage, chunk.model)
            
            yield StreamingResponse(
                id=chunk.id,
                model=chunk.model,
                created=chunk.created,
                choices=choices,
                usage=usage,
                system_fingerprint=chunk.system_fingerprint if hasattr(chunk, 'system_fingerprint') else None
            )
        
        logging.debug(f"Streaming complete: {chunk_count} chunks")
