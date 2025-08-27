"""
LangChain provider implementation.
"""
from collections.abc import AsyncGenerator

from langchain.chat_models.base import BaseChatModel

from ..base import LLMProvider


class LangChainProvider(LLMProvider):
    """LangChain LLM provider implementation."""
    
    def __init__(self, model: BaseChatModel, api_key: str | None = None, **kwargs):
        """Initialize the LangChain provider."""
        if not isinstance(model, BaseChatModel):
            raise ValueError("model must be an instance of BaseChatModel")
        
        self.model = model
    
    async def generate(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
        max_completion_tokens: int | None = None,
        reasoning_effort: str | None = None,
        **kwargs
    ) -> str:
        """Generate a response using LangChain."""
        langchain_messages = self._convert_messages(messages)
        
        if hasattr(self.model, 'ainvoke'):
            ai_message = await self.model.ainvoke(langchain_messages)
        else:
            # Fallback to sync method
            ai_message = self.model.invoke(langchain_messages)
        
        return ai_message.content
    
    async def stream_generate(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
        max_completion_tokens: int | None = None,
        reasoning_effort: str | None = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Stream a response using LangChain."""
        langchain_messages = self._convert_messages(messages)
        
        if hasattr(self.model, 'astream'):
            async for chunk in self.model.astream(langchain_messages):
                if chunk.content:
                    yield chunk.content
        else:
            # Fallback to sync streaming if available
            if hasattr(self.model, 'stream'):
                for chunk in self.model.stream(langchain_messages):
                    if chunk.content:
                        yield chunk.content
            else:
                # No streaming support, yield full response
                response = await self.generate(messages, model, temperature, max_tokens, **kwargs)
                yield response
    
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