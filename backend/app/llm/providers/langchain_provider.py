"""
LangChain provider implementation.
"""
import time
import logging
from collections.abc import AsyncGenerator

from langchain.chat_models.base import BaseChatModel

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


class LangChainProvider(LLMProvider):
    """LangChain LLM provider implementation."""
    
    def __init__(self, model: BaseChatModel, api_key: str | None = None, **kwargs):
        """Initialize the LangChain provider."""
        if not isinstance(model, BaseChatModel):
            raise ValueError("model must be an instance of BaseChatModel")
        
        self.model = model
    
    def _calculate_costs(self, usage: TokenUsage, model: str) -> TokenUsage:
        """
        Calculate costs based on model pricing.
        
        Args:
            usage: Token usage object
            model: Model name
            
        Returns:
            Updated usage with costs (depends on underlying LangChain model)
        """
        # LangChain costs depend on the underlying model being used
        # We can't determine costs without knowing the specific model
        usage.prompt_cost = 0.0
        usage.completion_cost = 0.0
        usage.total_cost = 0.0
        
        return usage
    
    async def generate(
        self,
        request: CompletionRequest
    ) -> CompletionResponse:
        """Generate a response using LangChain."""
        # Track timing
        start_time = time.time()
        
        # Convert messages to LangChain format
        langchain_messages = self._convert_messages(request.messages_as_dicts())
        
        # Configure model if possible
        if hasattr(self.model, 'temperature') and request.temperature is not None:
            self.model.temperature = request.temperature
        if hasattr(self.model, 'max_tokens') and request.max_tokens is not None:
            self.model.max_tokens = request.max_tokens
        
        # Generate response
        if hasattr(self.model, 'ainvoke'):
            ai_message = await self.model.ainvoke(langchain_messages)
        else:
            # Fallback to sync method
            ai_message = self.model.invoke(langchain_messages)
        
        # Calculate response time
        response_ms = (time.time() - start_time) * 1000
        
        # Create response
        message = Message(
            role=MessageRole.ASSISTANT,
            content=ai_message.content
        )
        
        choice = Choice(
            index=0,
            message=message,
            finish_reason="stop"
        )
        
        # Estimate token usage (LangChain doesn't always provide this)
        prompt_text = " ".join([msg.get("content", "") for msg in request.messages_as_dicts()])
        content = ai_message.content or ""
        prompt_tokens = max(len(prompt_text.split()) * 1.3, 1)
        completion_tokens = max(len(content.split()) * 1.3, 1) if content else 0
        
        usage = TokenUsage(
            prompt_tokens=int(prompt_tokens),
            completion_tokens=int(completion_tokens),
            total_tokens=int(prompt_tokens + completion_tokens)
        )
        
        # Calculate costs
        usage = self._calculate_costs(usage, request.model or "unknown")
        
        return CompletionResponse(
            id=f"langchain-{int(time.time())}",
            model=request.model or "langchain-model",
            created=int(time.time()),
            choices=[choice],
            usage=usage,
            response_ms=response_ms
        )
    
    async def stream_generate(
        self,
        request: CompletionRequest
    ) -> AsyncGenerator[StreamingResponse, None]:
        """Stream a response using LangChain."""
        # Convert messages to LangChain format
        langchain_messages = self._convert_messages(request.messages_as_dicts())
        
        # Configure model if possible
        if hasattr(self.model, 'temperature') and request.temperature is not None:
            self.model.temperature = request.temperature
        if hasattr(self.model, 'max_tokens') and request.max_tokens is not None:
            self.model.max_tokens = request.max_tokens
        
        chunk_count = 0
        accumulated_content = ""
        
        if hasattr(self.model, 'astream'):
            async for chunk in self.model.astream(langchain_messages):
                if chunk.content:
                    chunk_count += 1
                    accumulated_content += chunk.content
                    
                    # Create streaming choice
                    choice = StreamChoice(
                        index=0,
                        delta={"content": chunk.content},
                        finish_reason=None
                    )
                    
                    yield StreamingResponse(
                        id=f"langchain-{int(time.time())}-{chunk_count}",
                        model=request.model or "langchain-model",
                        created=int(time.time()),
                        choices=[choice]
                    )
        else:
            # Fallback to sync streaming if available
            if hasattr(self.model, 'stream'):
                for chunk in self.model.stream(langchain_messages):
                    if chunk.content:
                        chunk_count += 1
                        accumulated_content += chunk.content
                        
                        # Create streaming choice
                        choice = StreamChoice(
                            index=0,
                            delta={"content": chunk.content},
                            finish_reason=None
                        )
                        
                        yield StreamingResponse(
                            id=f"langchain-{int(time.time())}-{chunk_count}",
                            model=request.model or "langchain-model",
                            created=int(time.time()),
                            choices=[choice]
                        )
            else:
                # No streaming support, yield full response as single chunk
                response = await self.generate(request)
                
                # Create streaming choice with full content
                choice = StreamChoice(
                    index=0,
                    delta={"content": response.choices[0].message.content},
                    finish_reason="stop"
                )
                
                yield StreamingResponse(
                    id=response.id,
                    model=response.model,
                    created=response.created,
                    choices=[choice],
                    usage=response.usage
                )
                return
        
        # Send final chunk with usage info
        if accumulated_content:
            # Estimate usage
            prompt_text = " ".join([msg.get("content", "") for msg in request.messages_as_dicts()])
            prompt_tokens = max(len(prompt_text.split()) * 1.3, 1)
            completion_tokens = max(len(accumulated_content.split()) * 1.3, 1)
            
            usage = TokenUsage(
                prompt_tokens=int(prompt_tokens),
                completion_tokens=int(completion_tokens),
                total_tokens=int(prompt_tokens + completion_tokens)
            )
            
            # Calculate costs
            usage = self._calculate_costs(usage, request.model or "unknown")
            
            # Final chunk with finish reason and usage
            choice = StreamChoice(
                index=0,
                delta={},
                finish_reason="stop"
            )
            
            yield StreamingResponse(
                id=f"langchain-{int(time.time())}-final",
                model=request.model or "langchain-model",
                created=int(time.time()),
                choices=[choice],
                usage=usage
            )
        
        logging.debug(f"LangChain streaming complete: {chunk_count} chunks")
    
    def _convert_messages(self, messages: list[dict[str, str]]) -> list[tuple[str, str]]:
        """Convert messages to LangChain tuple format."""
        langchain_messages = []
        
        for message in messages:
            role = message["role"]
            content = message["content"]
            
            if role == "system":
                langchain_messages.append(("system", content))
            elif role == "user":
                langchain_messages.append(("human", content))
            elif role == "assistant":
                langchain_messages.append(("ai", content))
        
        return langchain_messages
