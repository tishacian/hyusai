"""Model service for managing AI models"""
from typing import List, Dict, Any
from app.core.logging import get_logger
from app.services.model_router import ModelRouter
from app.core.config import settings

logger = get_logger(__name__)


class ModelService:
    """Service for managing and interacting with AI models"""
    
    def __init__(self):
        self.model_router = ModelRouter()
        self.ollama_client = self.model_router.clients.get("ollama")
        self._models_cache: Dict[str, Dict[str, Any]] = {}
    
    async def list_models(self) -> List[Dict[str, Any]]:
        """List all available models"""
        try:
            all_models = await self.model_router.list_available_models()
            
            # Flatten models from all providers
            models = []
            for provider, provider_models in all_models.items():
                models.extend(provider_models)
            
            return models
        except Exception as e:
            logger.error("Failed to list models", error=str(e))
            return []
    
    async def get_model_status(self, model_id: str) -> str:
        """Get status of a specific model"""
        try:
            if ":" in model_id:
                provider, model_name = model_id.split(":", 1)
                client = self.model_router.clients.get(provider)
                
                if client and isinstance(client, type(self.ollama_client)):
                    is_available = await client.is_model_available(model_name)
                    return "available" if is_available else "unavailable"
            
            return "unknown"
        except Exception as e:
            logger.error("Failed to get model status", model_id=model_id, error=str(e))
            return "error"
    
    async def get_client(self, preferences: Dict[str, Any] = None):
        """Get model client using router"""
        return await self.model_router.get_client(preferences)

