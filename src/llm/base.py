"""
Base abstract class for LLM providers.
"""
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

from .models import CompletionRequest, CompletionResponse, StreamingResponse


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.
    
    This class defines the common interface that all LLM provider implementations
    must adhere to, ensuring consistent integration across the application.
    All methods now use Pydantic models for type safety and validation.
    """
    
    @abstractmethod
    async def generate(
        self,
        request: CompletionRequest
    ) -> CompletionResponse:
        """
        Generate a response from the language model.
        
        Args:
            request: Validated CompletionRequest with all parameters
            
        Returns:
            CompletionResponse with full type safety and validation
        """
        pass
    
    @abstractmethod
    async def stream_generate(
        self,
        request: CompletionRequest
    ) -> AsyncGenerator[StreamingResponse, None]:
        """
        Stream a response from the language model.
        
        Args:
            request: Validated CompletionRequest with all parameters
            
        Returns:
            AsyncGenerator yielding StreamingResponse chunks
        """
        pass