"""Base agent class"""
from abc import ABC, abstractmethod
from typing import Dict, Any, AsyncGenerator
from app.core.logging import get_logger

logger = get_logger(__name__)


class BaseAgent(ABC):
    """Base class for all agents"""
    
    def __init__(self, agent_id: str, name: str, agent_type: str):
        self.agent_id = agent_id
        self.name = name
        self.agent_type = agent_type
        self.status = "inactive"
        self.logger = get_logger(f"{__name__}.{self.__class__.__name__}")
    
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the agent"""
        pass
    
    @abstractmethod
    async def process(
        self, 
        request: Dict[str, Any]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Process a request and yield streaming chunks"""
        pass
    
    @abstractmethod
    async def cleanup(self) -> None:
        """Cleanup agent resources"""
        pass
    
    async def health_check(self) -> bool:
        """Check agent health"""
        return self.status == "active"

