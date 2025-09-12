"""
LM Studio LLM provider implementation.
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


class LMStudioProvider(LLMProvider):
    """
    LM Studio LLM provider implementation.
    
    Handles communication with LM Studio's API for text generation.
    Uses Pydantic models for type-safe request/response handling.
    """
    
    # Default model and base URL
    DEFAULT_MODEL = "local-model"
    DEFAULT_BASE_URL = "http://localhost:1234/v1"
    
    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        """
        Initialize the LM Studio provider.
        
        Args:
            base_url: LM Studio API base URL (defaults to LMSTUDIO_BASE_URL environment variable or localhost)
            api_key: Not used by LM Studio, included for compatibility
        """
        self.base_url = base_url or os.getenv("LMSTUDIO_BASE_URL", self.DEFAULT_BASE_URL)
        
        self.client = AsyncOpenAI(
            base_url=self.base_url,
            api_key="lm-studio",  # LM Studio uses a dummy API key
        )
    
    def _prepare_api_params(self, request: CompletionRequest, streaming: bool = False) -> dict:
        """
        Prepare parameters for LM Studio API call.
        
        Args:
            request: Validated CompletionRequest
            streaming: Whether this is for streaming
            
        Returns:
            Dictionary of parameters for LM Studio API
        """
        # Use default model if not specified
        model = request.model or os.getenv("LMSTUDIO_DEFAULT_MODEL", self.DEFAULT_MODEL)
        
        params = {
            "model": model,
            "messages": request.messages_as_dicts(),
        }
        
        if streaming:
            params["stream"] = True
        
        # Add parameters that are supported
        if request.temperature is not None:
            params["temperature"] = request.temperature
        
        if request.max_tokens is not None:
            params["max_tokens"] = request.max_tokens
        
        if request.top_p is not None:
            params["top_p"] = request.top_p
        
        if request.n is not None:
            params["n"] = request.n
        
        if request.stop:
            params["stop"] = request.stop
        
        if request.presence_penalty is not None:
            params["presence_penalty"] = request.presence_penalty
        
        if request.frequency_penalty is not None:
            params["frequency_penalty"] = request.frequency_penalty
        
        if request.seed is not None:
            params["seed"] = request.seed
        
        if request.user:
            params["user"] = request.user
        
        if request.logit_bias is not None:
            params["logit_bias"] = request.logit_bias

        return params
    
    def _calculate_costs(self, usage: TokenUsage, model: str) -> TokenUsage:
        """
        Calculate costs based on model pricing.
        
        Args:
            usage: Token usage object
            model: Model name
            
        Returns:
            Updated usage with costs (always 0 for local LM Studio)
        """
        # LM Studio is free/local, so costs are always 0
        usage.prompt_cost = 0.0
        usage.completion_cost = 0.0
        usage.total_cost = 0.0
        
        return usage
    
    async def generate(
        self,
        request: CompletionRequest
    ) -> CompletionResponse:
        """
        Generate a response using LM Studio's API.
        
        Args:
            request: Validated CompletionRequest with all parameters
        
        Returns:
            CompletionResponse with choices, usage, and metadata
        """
        # Prepare API parameters
        params = self._prepare_api_params(request)
        
        # Track timing
        start_time = time.time()
        
        # Make the API call
        response = await self.client.chat.completions.create(**params)
        
        # Calculate response time
        response_ms = (time.time() - start_time) * 1000
        
        # Convert LM Studio response to our typed response
        choices = []
        for choice in response.choices:
            message = Message(
                role=MessageRole.ASSISTANT,
                content=choice.message.content,
            )
            
            choices.append(
                Choice(
                    index=choice.index,
                    message=message,
                    finish_reason=choice.finish_reason
                )
            )
        
        # Build usage info (may be None for local models)
        usage = None
        if hasattr(response, 'usage') and response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens
            )
        else:
            # Estimate token usage if not provided
            prompt_text = " ".join([msg.get("content", "") for msg in request.messages_as_dicts()])
            content = choices[0].message.content if choices else ""
            prompt_tokens = max(len(prompt_text.split()) * 1.3, 1)
            completion_tokens = max(len(content.split()) * 1.3, 1) if content else 0
            
            usage = TokenUsage(
                prompt_tokens=int(prompt_tokens),
                completion_tokens=int(completion_tokens),
                total_tokens=int(prompt_tokens + completion_tokens)
            )
        
        # Calculate costs (always 0 for local LM Studio)
        usage = self._calculate_costs(usage, response.model)
        
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
        Stream a response using LM Studio's API.
        
        Args:
            request: Validated CompletionRequest with all parameters
        
        Returns:
            AsyncGenerator yielding StreamingResponse chunks
        """
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
            
            # Convert LM Studio chunk to our typed streaming response
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
                
                # Calculate costs (always 0 for local LM Studio)
                usage = self._calculate_costs(usage, chunk.model)
            
            yield StreamingResponse(
                id=chunk.id,
                model=chunk.model,
                created=chunk.created,
                choices=choices,
                usage=usage
            )
        
        logging.debug(f"LM Studio streaming complete: {chunk_count} chunks")
