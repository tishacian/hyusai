"""
Base abstract class for LLM providers.
"""
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.
    
    This class defines the common interface that all LLM provider implementations
    must adhere to, ensuring consistent integration across the application.
    """
    
    @abstractmethod
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
        """
        Generate a response from the language model.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            model: The model identifier to use
            temperature: Controls randomness (0.0 to 1.0), not used for thinking models
            max_tokens: Maximum number of tokens to generate (for non-thinking models)
            max_completion_tokens: Maximum number of tokens to generate (for thinking models)
            reasoning_effort: Reasoning effort for thinking models (low, medium, high)
            **kwargs: Additional provider-specific parameters
            
        Returns:
            Generated text response
        """
        pass
    
    @abstractmethod
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
        """
        Stream a response from the language model.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            model: The model identifier to use
            temperature: Controls randomness (0.0 to 1.0), not used for thinking models
            max_tokens: Maximum number of tokens to generate (for non-thinking models)
            max_completion_tokens: Maximum number of tokens to generate (for thinking models)
            reasoning_effort: Reasoning effort for thinking models (low, medium, high)
            **kwargs: Additional provider-specific parameters
            
        Returns:
            AsyncGenerator yielding chunks of the response as they become available
        """
        pass 