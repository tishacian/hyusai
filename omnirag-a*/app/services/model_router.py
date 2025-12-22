"""Model router for intelligent model selection and fallback"""
from typing import Dict, Any, Optional, List
import os
from app.core.logging import get_logger
from app.services.model_clients.base import ModelClient
from app.services.model_clients.ollama_client import OllamaClient
from app.core.config import settings

logger = get_logger(__name__)


class ModelRouter:
    """Routes requests to appropriate model providers with fallback"""
    
    def __init__(self):
        self.clients: Dict[str, ModelClient] = {}
        self.fallback_chain: List[str] = ["ollama"]  # Default fallback order
        self.logger = get_logger(__name__)
        self._initialize_clients()
    
    def _initialize_clients(self):
        """Initialize model clients"""
        # Initialize Ollama client (always available)
        ollama_client = OllamaClient(base_url=settings.ollama_base_url)
        self.clients["ollama"] = ollama_client
        
        # Initialize OpenAI client if API key is available
        try:
            from app.services.model_clients.openai_client import OpenAIClient
            openai_key = os.getenv("OPENAI_API_KEY")
            if openai_key:
                openai_client = OpenAIClient(api_key=openai_key)
                self.clients["openai"] = openai_client
                self.fallback_chain.append("openai")
        except Exception as e:
            self.logger.debug("OpenAI client not initialized", error=str(e))
        
        # Initialize Anthropic client if API key is available
        try:
            from app.services.model_clients.anthropic_client import AnthropicClient
            anthropic_key = os.getenv("ANTHROPIC_API_KEY")
            if anthropic_key:
                anthropic_client = AnthropicClient(api_key=anthropic_key)
                self.clients["anthropic"] = anthropic_client
                self.fallback_chain.append("anthropic")
        except Exception as e:
            self.logger.debug("Anthropic client not initialized", error=str(e))
        
        self.logger.info("Model router initialized", clients=list(self.clients.keys()))
    
    async def get_client(
        self, 
        preferences: Optional[Dict[str, Any]] = None
    ) -> ModelClient:
        """Get appropriate model client based on preferences"""
        if not preferences:
            preferences = {
                "provider": "ollama",
                "model": settings.ollama_default_model
            }
        
        provider = preferences.get("provider", "ollama")
        model_name = preferences.get("model", settings.ollama_default_model)
        
        # Try primary provider
        if provider in self.clients:
            client = self.clients[provider]
            if await self._check_client_health(client, model_name):
                self.logger.info("Using primary provider", provider=provider, model=model_name)
                return client
        
        # Try fallback providers
        for fallback_provider in self.fallback_chain:
            if fallback_provider == provider:
                continue  # Skip if already tried
            
            if fallback_provider in self.clients:
                client = self.clients[fallback_provider]
                if await self._check_client_health(client, model_name):
                    self.logger.info(
                        "Using fallback provider", 
                        fallback=fallback_provider, 
                        original=provider,
                        model=model_name
                    )
                    return client
        
        # If no client available, raise error
        raise RuntimeError(f"No available model clients. Tried: {provider} and fallbacks: {self.fallback_chain}")
    
    async def _check_client_health(
        self, 
        client: ModelClient, 
        model_name: str
    ) -> bool:
        """Check if client is healthy and model is available"""
        try:
            if hasattr(client, "health_check"):
                is_healthy = await client.health_check()
                if not is_healthy:
                    return False
            
            # For Ollama, check if model is available
            if isinstance(client, OllamaClient):
                is_available = await client.is_model_available(model_name)
                return is_available
            
            return True
        except Exception as e:
            self.logger.warning("Client health check failed", error=str(e))
            return False
    
    def register_client(self, provider: str, client: ModelClient):
        """Register a new model client"""
        self.clients[provider] = client
        self.logger.info("Model client registered", provider=provider)
    
    def set_fallback_chain(self, chain: List[str]):
        """Set the fallback chain"""
        self.fallback_chain = chain
        self.logger.info("Fallback chain updated", chain=chain)
    
    async def list_available_models(self) -> Dict[str, List[Dict[str, Any]]]:
        """List all available models across providers"""
        all_models = {}
        
        for provider, client in self.clients.items():
            try:
                if isinstance(client, OllamaClient):
                    models = await client.list_models()
                    all_models[provider] = [
                        {
                            "id": f"{provider}:{model['name']}",
                            "name": model["name"],
                            "provider": provider,
                            "size": model.get("size", 0),
                            "modified_at": model.get("modified_at", "")
                        }
                        for model in models
                    ]
            except Exception as e:
                self.logger.warning("Failed to list models", provider=provider, error=str(e))
                all_models[provider] = []
        
        return all_models

