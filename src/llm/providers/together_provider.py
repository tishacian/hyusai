"""
Together AI LLM provider implementation.
"""
import os
import time
import logging
from collections.abc import AsyncGenerator

from together import AsyncTogether

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


class TogetherProvider(LLMProvider):
    """
    Together AI LLM provider implementation.
    
    Handles communication with Together AI's API for text generation.
    Uses Pydantic models for type-safe request/response handling.
    """
    
    # Default model
    DEFAULT_MODEL = "mistralai/Mixtral-8x7B-Instruct-v0.1"
    
    # Model pricing per 1000 tokens (approximate)
    MODEL_PRICING = {
        "mixtral": {"input": 0.0006, "output": 0.0006},
        "llama-2": {"input": 0.0002, "output": 0.0002},
        "llama-3": {"input": 0.0002, "output": 0.0002},
        "mistral": {"input": 0.0002, "output": 0.0002},
        "code-llama": {"input": 0.0002, "output": 0.0002},
    }
    
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        """
        Initialize the Together provider.
        
        Args:
            api_key: Together API key (defaults to TOGETHER_API_KEY environment variable)
            base_url: Together API base URL (defaults to TOGETHER_BASE_URL environment variable)
        """
        self.api_key = api_key or os.getenv("TOGETHER_API_KEY")
        
        if not self.api_key:
            raise ValueError("Together API key is required")
        
        # Initialize client with optional base_url
        client_kwargs = {"api_key": self.api_key}
        if base_url or os.getenv("TOGETHER_BASE_URL"):
            client_kwargs["base_url"] = base_url or os.getenv("TOGETHER_BASE_URL")
            
        self.client = AsyncTogether(**client_kwargs)
    
    def _prepare_api_params(self, request: CompletionRequest, streaming: bool = False) -> dict:
        """
        Prepare parameters for Together API call.
        
        Args:
            request: Validated CompletionRequest
            streaming: Whether this is for streaming
            
        Returns:
            Dictionary of parameters for Together API
        """
        # Use default model if not specified
        model = request.model or os.getenv("TOGETHER_DEFAULT_MODEL", self.DEFAULT_MODEL)
        
        params = {
            "model": model,
            "messages": request.messages,
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
        Generate a response using Together AI's API.
        
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
        
        # Convert Together response to our typed response
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
        
        # Build usage info
        usage = None
        if response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens
            )
            
            # Calculate costs
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
        Stream a response using Together AI's API.
        
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
            
            # Convert Together chunk to our typed streaming response
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
                
                # Calculate costs
                usage = self._calculate_costs(usage, chunk.model)
            
            yield StreamingResponse(
                id=chunk.id,
                model=chunk.model,
                created=chunk.created,
                choices=choices,
                usage=usage
            )
        
        logging.debug(f"Together streaming complete: {chunk_count} chunks")
