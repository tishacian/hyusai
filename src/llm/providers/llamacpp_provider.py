"""
llama.cpp provider implementation.
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


class LlamaCppProvider(LLMProvider):
    """llama.cpp LLM provider implementation."""
    
    # Default model
    DEFAULT_MODEL = "llamacpp"
    
    def __init__(
        self, 
        api_key: str | None = None,
        base_url: str | None = None,
        **kwargs
    ):
        """Initialize the llama.cpp provider."""
        self.api_key = api_key or "llamacpp-api-key"  # llama.cpp doesn't use API keys
        self.base_url = base_url or os.getenv("LLAMACPP_BASE_URL") or "http://localhost:8080"
        
        if not self.base_url:
            raise ValueError("llama.cpp base URL is required")
        
        # Create OpenAI client for consistency, even though we'll use custom logic
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=f"{self.base_url}/v1",  # Most llamacpp servers have v1 endpoint
            **kwargs
        )
    
    def _calculate_costs(self, usage: TokenUsage, model: str) -> TokenUsage:
        """Calculate costs based on model pricing."""
        usage.prompt_cost = 0.0
        usage.completion_cost = 0.0
        usage.total_cost = 0.0
        return usage
    
    async def generate(
        self,
        request: CompletionRequest
    ) -> CompletionResponse:
        """Generate a response using llama.cpp."""
        model = request.model or os.getenv("LLAMACPP_DEFAULT_MODEL", self.DEFAULT_MODEL)
        start_time = time.time()
        
        params = self._build_params(
            model=model,
            messages=request.messages,
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
        
        response = await self.client.chat.completions.create(**params)
        response_ms = (time.time() - start_time) * 1000
        
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
        
        usage = None
        if hasattr(response, 'usage') and response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens
            )
        else:
            prompt_text = " ".join([msg.get("content", "") for msg in request.messages])
            content = choices[0].message.content if choices else ""
            prompt_tokens = max(len(prompt_text.split()) * 1.3, 1)
            completion_tokens = max(len(content.split()) * 1.3, 1) if content else 0
            
            usage = TokenUsage(
                prompt_tokens=int(prompt_tokens),
                completion_tokens=int(completion_tokens),
                total_tokens=int(prompt_tokens + completion_tokens)
            )
        
        usage = self._calculate_costs(usage, model)
        
        return CompletionResponse(
            id=response.id if hasattr(response, 'id') else f"llamacpp-{int(time.time())}",
            model=model,
            created=response.created if hasattr(response, 'created') else int(time.time()),
            choices=choices,
            usage=usage,
            response_ms=response_ms
        )
    
    async def stream_generate(
        self,
        request: CompletionRequest
    ) -> AsyncGenerator[StreamingResponse, None]:
        """Stream a response using llama.cpp."""
        model = request.model
        
        params = self._build_params(
            model=model,
            messages=request.messages,
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
        
        chunk_count = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        
        stream = await self.client.chat.completions.create(**params)
        
        async for chunk in stream:
            chunk_count += 1
            
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
            
            usage = None
            if hasattr(chunk, 'usage') and chunk.usage:
                total_prompt_tokens = chunk.usage.prompt_tokens
                total_completion_tokens = chunk.usage.completion_tokens
                
                usage = TokenUsage(
                    prompt_tokens=total_prompt_tokens,
                    completion_tokens=total_completion_tokens,
                    total_tokens=total_prompt_tokens + total_completion_tokens
                )
                
                usage = self._calculate_costs(usage, model)
            
            yield StreamingResponse(
                id=chunk.id if hasattr(chunk, 'id') else f"llamacpp-{int(time.time())}-{chunk_count}",
                model=model,
                created=chunk.created if hasattr(chunk, 'created') else int(time.time()),
                choices=choices,
                usage=usage
            )
        
        logging.debug(f"llama.cpp streaming complete: {chunk_count} chunks")
    
    def _build_params(self, **kwargs) -> dict:
        """Build API parameters filtering out None values and unsupported parameters."""
        kwargs.pop('max_completion_tokens', None)
        kwargs.pop('reasoning_effort', None)
        return {k: v for k, v in kwargs.items() if v is not None}
    
