"""
LiteLLM provider implementation.
"""
import time
import logging
from collections.abc import AsyncGenerator

import litellm

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


class LiteLLMProvider(LLMProvider):
    """LiteLLM provider implementation for unified LLM access."""
    
    def __init__(self, api_key: str | None = None, **kwargs):
        """Initialize the LiteLLM provider."""
        # LiteLLM handles API keys internally based on model name
        pass
    
    def _prepare_api_params(self, request: CompletionRequest, streaming: bool = False) -> dict:
        """
        Prepare parameters for LiteLLM API call.
        
        Args:
            request: Validated CompletionRequest
            streaming: Whether this is for streaming
            
        Returns:
            Dictionary of parameters for LiteLLM API
        """
        # Use default model if not specified
        model = request.model or "gpt-4o-mini"
        
        params = {
            "model": model,
            "messages": request.messages_as_dicts(),
        }
        
        if streaming:
            params["stream"] = True
        
        # Add optional parameters
        if request.temperature is not None:
            params["temperature"] = request.temperature
        if request.max_tokens is not None:
            params["max_tokens"] = request.max_tokens
        if request.max_completion_tokens is not None:
            params["max_completion_tokens"] = request.max_completion_tokens
        if request.top_p is not None:
            params["top_p"] = request.top_p
        if request.presence_penalty is not None:
            params["presence_penalty"] = request.presence_penalty
        if request.frequency_penalty is not None:
            params["frequency_penalty"] = request.frequency_penalty
        if request.stop:
            params["stop"] = request.stop
        if request.response_format:
            params["response_format"] = request.response_format
        if request.seed is not None:
            params["seed"] = request.seed
        if request.user:
            params["user"] = request.user
        if request.reasoning_effort:
            params["reasoning_effort"] = request.reasoning_effort
        
        return params
    
    def _calculate_costs(self, usage: TokenUsage, model: str) -> TokenUsage:
        """
        Calculate costs for LiteLLM - costs are set to 0 since pricing varies by provider.
        
        Args:
            usage: Token usage object
            model: Model name
            
        Returns:
            Updated usage with costs set to 0
        """
        # LiteLLM supports many providers with different pricing
        # For now, set costs to 0 - could be enhanced to lookup pricing per provider
        usage.prompt_cost = 0.0
        usage.completion_cost = 0.0
        usage.total_cost = 0.0
        
        return usage
    
    async def generate(
        self,
        request: CompletionRequest
    ) -> CompletionResponse:
        """
        Generate a response using LiteLLM.

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
        response = await litellm.acompletion(**params)
        
        # Calculate response time
        response_ms = (time.time() - start_time) * 1000
        
        # Convert LiteLLM response to our typed response
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
            
            # Calculate costs (set to 0 for LiteLLM)
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
        Stream a response using LiteLLM.

        Args:
            request: Validated CompletionRequest with all parameters

        Returns:
            AsyncGenerator yielding StreamingResponse chunks
        """
        # Prepare API parameters
        params = self._prepare_api_params(request, streaming=True)
        
        # Make the streaming API call
        stream = await litellm.acompletion(**params)
        
        chunk_count = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        
        # Process each chunk
        async for chunk in stream:
            chunk_count += 1
            
            # Convert LiteLLM chunk to our typed streaming response
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
                
                # Calculate costs (set to 0 for LiteLLM)
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
