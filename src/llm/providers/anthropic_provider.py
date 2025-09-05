"""
Anthropic LLM provider implementation.
"""
import os
import time
import logging
from collections.abc import AsyncGenerator

import anthropic

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


class AnthropicProvider(LLMProvider):
    """Anthropic API provider implementation."""

    # Default base URL for Anthropic API
    DEFAULT_BASE_URL = "https://api.anthropic.com"

    # Default models for Anthropic
    DEFAULT_MODEL = "claude-3-4-sonnet"
    
    # Model pricing per 1000 tokens
    MODEL_PRICING = {
        "claude-3-opus": {"input": 0.015, "output": 0.075},
        "claude-3-5-sonnet": {"input": 0.003, "output": 0.015},
        "claude-3-4-sonnet": {"input": 0.003, "output": 0.015},
        "claude-3-sonnet": {"input": 0.003, "output": 0.015},
        "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
        "claude-2.1": {"input": 0.008, "output": 0.024},
        "claude-2.0": {"input": 0.008, "output": 0.024},
        "claude-instant": {"input": 0.00163, "output": 0.00551},
    }

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        """Initialize the Anthropic provider."""
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("Anthropic API key is required")
            
        self.base_url = base_url or os.getenv("ANTHROPIC_BASE_URL", self.DEFAULT_BASE_URL)

        self.client = anthropic.AsyncAnthropic(
            api_key=self.api_key,
            base_url=self.base_url
        )

    def _prepare_messages(self, messages: list[dict]) -> tuple[str, list[dict]]:
        """Prepare messages for Anthropic API by separating system message."""
        system_message = ""
        filtered_messages = []
        
        for message in messages:
            if message.get("role") == "system":
                system_message = message.get("content", "")
            else:
                role = message.get("role", "user")
                if role == "tool":
                    role = "user"
                filtered_messages.append({
                    "role": role,
                    "content": message.get("content", "")
                })
                
        return system_message, filtered_messages
    
    def _prepare_api_params(self, request: CompletionRequest, streaming: bool = False) -> dict:
        """Prepare parameters for Anthropic API call."""
        model = request.model or os.getenv("ANTHROPIC_DEFAULT_MODEL", self.DEFAULT_MODEL)
        system_message, messages = self._prepare_messages(request.messages)
        
        params = {
            "model": model,
            "messages": messages,
        }
        
        if system_message:
            params["system"] = system_message
        
        if streaming:
            params["stream"] = True
        
        if request.max_tokens is not None:
            params["max_tokens"] = request.max_tokens
        elif request.max_completion_tokens is not None:
            params["max_tokens"] = request.max_completion_tokens
        else:
            params["max_tokens"] = 4096
        
        if request.temperature is not None:
            params["temperature"] = request.temperature
        
        if request.top_p is not None:
            params["top_p"] = request.top_p
        
        if request.stop:
            if isinstance(request.stop, str):
                params["stop_sequences"] = [request.stop]
            else:
                params["stop_sequences"] = request.stop
        
        return params
    
    def _calculate_costs(self, usage: TokenUsage, model: str) -> TokenUsage:
        """Calculate costs based on model pricing."""
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
        """Generate a response using Anthropic's API."""
        params = self._prepare_api_params(request)
        start_time = time.time()
        response = await self.client.messages.create(**params)
        response_ms = (time.time() - start_time) * 1000
        
        content = ""
        if response.content:
            for block in response.content:
                if hasattr(block, 'text'):
                    content += block.text
                elif hasattr(block, 'type') and block.type == 'text':
                    content += getattr(block, 'text', '')
        
        message = Message(
            role=MessageRole.ASSISTANT,
            content=content,
        )
        
        usage = None
        if hasattr(response, 'usage'):
            usage = TokenUsage(
                prompt_tokens=response.usage.input_tokens,
                completion_tokens=response.usage.output_tokens,
                total_tokens=response.usage.input_tokens + response.usage.output_tokens
            )
            usage = self._calculate_costs(usage, response.model)
        
        return CompletionResponse(
            id=response.id,
            model=response.model,
            created=int(time.time()),
            choices=[
                Choice(
                    index=0,
                    message=message,
                    finish_reason=response.stop_reason if hasattr(response, 'stop_reason') else "stop"
                )
            ],
            usage=usage,
            response_ms=response_ms
        )

    async def stream_generate(
        self,
        request: CompletionRequest
    ) -> AsyncGenerator[StreamingResponse, None]:
        """Stream a response using Anthropic's API."""
        params = self._prepare_api_params(request, streaming=True)
        start_time = time.time()
        chunk_count = 0
        total_content = ""
        stream_id = f"anthropic-{int(time.time() * 1000)}"
        created = int(time.time())
        model_name = params["model"]
        
        stream = await self.client.messages.create(**params)
        
        async for event in stream:
            chunk_count += 1
            
            if event.type == "message_start":
                if hasattr(event, 'message'):
                    stream_id = event.message.id
                    model_name = event.message.model
            
            elif event.type == "content_block_start":
                pass
            
            elif event.type == "content_block_delta":
                if hasattr(event, 'delta') and hasattr(event.delta, 'text'):
                    content = event.delta.text
                    total_content += content
                    
                    yield StreamingResponse(
                        id=stream_id,
                        model=model_name,
                        created=created,
                        choices=[
                            StreamChoice(
                                index=0,
                                delta={"content": content},
                                finish_reason=None
                            )
                        ]
                    )
            
            elif event.type == "content_block_stop":
                pass
            
            elif event.type == "message_delta":
                finish_reason = None
                if hasattr(event, 'delta') and hasattr(event.delta, 'stop_reason'):
                    finish_reason = event.delta.stop_reason
                
                yield StreamingResponse(
                    id=stream_id,
                    model=model_name,
                    created=created,
                    choices=[
                        StreamChoice(
                            index=0,
                            delta={},
                            finish_reason=finish_reason
                        )
                    ]
                )
            
            elif event.type == "message_stop":
                usage = None
                if hasattr(event, 'message') and hasattr(event.message, 'usage'):
                    usage = TokenUsage(
                        prompt_tokens=event.message.usage.input_tokens,
                        completion_tokens=event.message.usage.output_tokens,
                        total_tokens=event.message.usage.input_tokens + event.message.usage.output_tokens
                    )
                    usage = self._calculate_costs(usage, model_name)
                
                yield StreamingResponse(
                    id=stream_id,
                    model=model_name,
                    created=created,
                    choices=[
                        StreamChoice(
                            index=0,
                            delta={},
                            finish_reason="stop"
                        )
                    ],
                    usage=usage
                )