"""Base model client interface"""
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, Any, List


class ModelClient(ABC):
    """Abstract base class for model clients"""
    
    @abstractmethod
    async def generate(
        self, 
        prompt: str, 
        **kwargs
    ) -> Dict[str, Any]:
        """Generate a single response"""
        pass
    
    @abstractmethod
    async def stream(
        self, 
        prompt: str, 
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream response tokens"""
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """Check if model is available"""
        pass

