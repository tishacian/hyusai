"""
Sarvam AI provider implementation.
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


class SarvamProvider(LLMProvider):
    """Sarvam AI LLM provider implementation."""
    
    # Default model
    DEFAULT_MODEL = "sarvam-m"
    
    def __init__(self, api_key: str | None = None, base_url: str | None = None, **kwargs):
        """Initialize the Sarvam provider."""
        self.api_key = api_key or os.getenv("SARVAM_API_KEY")
        self.base_url = base_url or os.getenv("SARVAM_API_BASE") or "https://api.sarvam.ai/v1"
        
        if not self.api_key:
            raise ValueError("Sarvam API key is required")
        
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            **kwargs
        )
    
    def _calculate_costs(self, usage: TokenUsage, model: str) -> TokenUsage:
        """
        Calculate costs based on model pricing.
        
        Args:
            usage: Token usage object
            model: Model name
            
        Returns:
            Updated usage with costs (using estimated pricing)
        """
        # Sarvam pricing not publicly available, using estimated values
        # These should be updated when actual pricing is available
        COST_PER_1K_INPUT = 0.001  # $0.001 per 1K input tokens (estimated)
        COST_PER_1K_OUTPUT = 0.002  # $0.002 per 1K output tokens (estimated)
        
        usage.prompt_cost = (usage.prompt_tokens / 1000) * COST_PER_1K_INPUT
        usage.completion_cost = (usage.completion_tokens / 1000) * COST_PER_1K_OUTPUT
        usage.total_cost = usage.prompt_cost + usage.completion_cost
        
        return usage
    
    async def generate(
        self,
        request: CompletionRequest
    ) -> CompletionResponse:
        """Generate a response using Sarvam AI."""
        # Use default model if not specified
        model = request.model or os.getenv("SARVAM_DEFAULT_MODEL", self.DEFAULT_MODEL)
        
        # Track timing
        start_time = time.time()
        
        # Build parameters
        params = self._build_params(
            model=model,
            messages=request.messages_as_dicts(),
            temperature=request.temperature,
            max_tokens=request.max_tokens or request.max_completion_tokens,
            top_p=request.top_p,
            n=request.n,
            stop=request.stop,
            presence_penalty=request.presence_penalty,
            frequency_penalty=request.frequency_penalty,
            seed=request.seed,
            logit_bias=request.logit_bias
        )
        
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
            # Calculate costs
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
        """Stream a response using Sarvam AI."""
        # Use the model from request
        model = request.model
        
        # Build parameters
        params = self._build_params(
            model=model,
            messages=request.messages_as_dicts(),
            temperature=request.temperature,
            max_tokens=request.max_tokens or request.max_completion_tokens,
            top_p=request.top_p,
            n=request.n,
            stop=request.stop,
            presence_penalty=request.presence_penalty,
            frequency_penalty=request.frequency_penalty,
            seed=request.seed,
            logit_bias=request.logit_bias,
            stream=True
        )
        
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
            
            # Build usage info if present
            usage = None
            if hasattr(chunk, 'usage') and chunk.usage:
                total_prompt_tokens = chunk.usage.prompt_tokens
                total_completion_tokens = chunk.usage.completion_tokens
                
                usage = TokenUsage(
                    prompt_tokens=total_prompt_tokens,
                    completion_tokens=total_completion_tokens,
                    total_tokens=total_prompt_tokens + total_completion_tokens
                )
                
                # Calculate costs
                usage = self._calculate_costs(usage, model)
            
            yield StreamingResponse(
                id=chunk.id,
                model=chunk.model,
                created=chunk.created,
                choices=choices,
                usage=usage
            )
        
        logging.debug(f"Sarvam streaming complete: {chunk_count} chunks")
    
    def _build_params(self, **kwargs) -> dict:
        """Build API parameters filtering out None values and unsupported parameters."""
        # Remove unsupported parameters
        kwargs.pop('max_completion_tokens', None)
        kwargs.pop('reasoning_effort', None)
        
        # Filter out None values
        return {k: v for k, v in kwargs.items() if v is not None}
