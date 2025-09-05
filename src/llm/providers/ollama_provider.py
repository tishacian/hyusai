"""
Ollama LLM provider implementation.
"""
import os
import time
import logging
from collections.abc import AsyncGenerator

from ollama import AsyncClient

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


class OllamaProvider(LLMProvider):
    """
    Ollama LLM provider implementation.
    
    Handles communication with Ollama's API for text generation.
    Uses Pydantic models for type-safe request/response handling.
    """
    
    # Default model and host
    DEFAULT_MODEL = "qwen2.5:0.6b"
    DEFAULT_HOST = "http://localhost:11434"
    
    def __init__(self, host: str | None = None, api_key: str | None = None):
        """
        Initialize the Ollama provider.
        
        Args:
            host: Ollama host URL (defaults to OLLAMA_HOST environment variable or localhost)
            api_key: Not used by Ollama, included for compatibility
        """
        self.host = host or os.getenv("OLLAMA_HOST", self.DEFAULT_HOST)
        self.client = AsyncClient(host=self.host)
    
    def _prepare_api_params(self, request: CompletionRequest, streaming: bool = False) -> tuple[str, dict]:
        """
        Prepare parameters for Ollama API call.
        
        Args:
            request: Validated CompletionRequest
            streaming: Whether this is for streaming
            
        Returns:
            Tuple of (model, options)
        """
        # Use default model if not specified
        model = request.model or os.getenv("OLLAMA_DEFAULT_MODEL", self.DEFAULT_MODEL)
        
        options = {}
        
        if request.temperature is not None:
            options["temperature"] = request.temperature
        
        if request.max_tokens is not None:
            options["num_predict"] = request.max_tokens  # Ollama uses num_predict for max tokens
        
        if request.top_p is not None:
            options["top_p"] = request.top_p
        
        if request.seed is not None:
            options["seed"] = request.seed
        
        return model, options
    
    def _calculate_costs(self, usage: TokenUsage, model: str) -> TokenUsage:
        """
        Calculate costs based on model pricing.
        
        Args:
            usage: Token usage object
            model: Model name
            
        Returns:
            Updated usage with costs (always 0 for local Ollama)
        """
        # Ollama is free/local, so costs are always 0
        usage.prompt_cost = 0.0
        usage.completion_cost = 0.0
        usage.total_cost = 0.0
        
        return usage
    
    async def generate(
        self,
        request: CompletionRequest
    ) -> CompletionResponse:
        """
        Generate a response using Ollama's API.
        
        Args:
            request: Validated CompletionRequest with all parameters
        
        Returns:
            CompletionResponse with choices, usage, and metadata
        """
        # Prepare API parameters
        model, options = self._prepare_api_params(request)
        
        # Track timing
        start_time = time.time()
        
        # Make the API call
        response = await self.client.chat(
            model=model,
            messages=request.messages,
            options=options,
            stream=False
        )
        
        # Calculate response time
        response_ms = (time.time() - start_time) * 1000
        
        # Get content from response
        content = response.get("message", {}).get("content", "")
        
        # Create message
        message = Message(
            role=MessageRole.ASSISTANT,
            content=content
        )
        
        # Create choice
        choice = Choice(
            index=0,
            message=message,
            finish_reason="stop"
        )
        
        # Estimate token usage (Ollama doesn't provide exact counts)
        prompt_text = " ".join([msg.get("content", "") for msg in request.messages])
        prompt_tokens = max(len(prompt_text.split()) * 1.3, 1)  # Rough approximation
        completion_tokens = max(len(content.split()) * 1.3, 1) if content else 0
        
        usage = TokenUsage(
            prompt_tokens=int(prompt_tokens),
            completion_tokens=int(completion_tokens),
            total_tokens=int(prompt_tokens + completion_tokens)
        )
        
        # Calculate costs (always 0 for local Ollama)
        usage = self._calculate_costs(usage, model)
        
        return CompletionResponse(
            id=f"ollama-{int(time.time())}",
            model=model,
            created=int(time.time()),
            choices=[choice],
            usage=usage,
            response_ms=response_ms
        )
    
    async def stream_generate(
        self,
        request: CompletionRequest
    ) -> AsyncGenerator[StreamingResponse, None]:
        """
        Stream a response using Ollama's API.
        
        Args:
            request: Validated CompletionRequest with all parameters
        
        Returns:
            AsyncGenerator yielding StreamingResponse chunks
        """
        # Prepare API parameters
        model, options = self._prepare_api_params(request)
        
        chunk_count = 0
        accumulated_content = ""
        total_completion_tokens = 0
        
        # Make the streaming API call
        async for chunk in await self.client.chat(
            model=model,
            messages=request.messages,
            options=options,
            stream=True
        ):
            content = chunk.get("message", {}).get("content", "")
            
            if content:
                chunk_count += 1
                accumulated_content += content
                
                # Estimate tokens for this chunk
                chunk_tokens = max(len(content.split()) * 1.3, 1)
                total_completion_tokens += chunk_tokens
                
                # Create streaming choice
                choice = StreamChoice(
                    index=0,
                    delta={"content": content},
                    finish_reason=None
                )
                
                yield StreamingResponse(
                    id=f"ollama-{int(time.time())}-{chunk_count}",
                    model=model,
                    created=int(time.time()),
                    choices=[choice]
                )
        
        # Send final chunk with usage info
        if chunk_count > 0:
            # Estimate final usage
            prompt_text = " ".join([msg.get("content", "") for msg in request.messages])
            prompt_tokens = max(len(prompt_text.split()) * 1.3, 1)
            
            usage = TokenUsage(
                prompt_tokens=int(prompt_tokens),
                completion_tokens=int(total_completion_tokens),
                total_tokens=int(prompt_tokens + total_completion_tokens)
            )
            
            # Calculate costs (always 0 for local Ollama)
            usage = self._calculate_costs(usage, model)
            
            # Final chunk with finish reason and usage
            choice = StreamChoice(
                index=0,
                delta={},
                finish_reason="stop"
            )
            
            yield StreamingResponse(
                id=f"ollama-{int(time.time())}-final",
                model=model,
                created=int(time.time()),
                choices=[choice],
                usage=usage
            )
        
        logging.debug(f"Ollama streaming complete: {chunk_count} chunks")