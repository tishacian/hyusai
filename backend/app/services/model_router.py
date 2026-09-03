"""Model router for intelligent model selection and fallback"""
from dataclasses import dataclass
from typing import Dict, Any, Optional, List
import os
from app.core.logging import get_logger
from app.services.model_clients.base import ModelClient
from app.services.model_clients.ollama_client import OllamaClient
from app.core.config import settings

logger = get_logger(__name__)


@dataclass(frozen=True)
class ResolvedClient:
    """A healthy client plus the model name it will actually serve."""

    client: ModelClient
    provider: str
    model: str
    fallback: bool = False


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

        # Active serving instances (vLLM / OpenAI-compatible) from model_plane.
        self._register_serving_providers()
        
        self.logger.info("Model router initialized", clients=list(self.clients.keys()))

    def _register_serving_providers(self) -> None:
        """Attach cached local serving endpoints as OpenAI-compatible clients."""
        try:
            from app.services.model_clients.openai_client import OpenAIClient
            from app.services.model_plane.registration import list_routable_providers
        except Exception as e:
            self.logger.debug("Serving provider registration skipped", error=str(e))
            return

        for meta in list_routable_providers():
            key = meta.get("key")
            base_url = meta.get("openai_base_url")
            if not key or not base_url:
                continue
            try:
                self.clients[key] = OpenAIClient(
                    api_key=str(meta.get("api_key") or "local"),
                    base_url=str(base_url),
                )
            except Exception as e:
                self.logger.debug(
                    "Failed to register serving provider",
                    key=key,
                    error=str(e),
                )
    
    async def get_client(
        self,
        preferences: Optional[Dict[str, Any]] = None,
        *,
        fallback_chain: Optional[List[str]] = None,
    ) -> ModelClient:
        """Get appropriate model client based on preferences"""
        return (await self.resolve(preferences, fallback_chain=fallback_chain)).client

    async def resolve(
        self,
        preferences: Optional[Dict[str, Any]] = None,
        *,
        fallback_chain: Optional[List[str]] = None,
    ) -> "ResolvedClient":
        """Pick a healthy client and the model name it should actually serve.

        ``fallback_chain`` (workspace routing policy) overrides the instance
        chain for this call.  When the walk lands on Ollama with a model that
        the local daemon does not host (typically a cloud model name), the
        deployment's ``ollama_default_model`` is served instead — the same
        degradation the evaluation judge already applied by hand.
        """
        if not preferences:
            preferences = {
                "provider": "ollama",
                "model": settings.ollama_default_model
            }

        provider = preferences.get("provider", "ollama")
        model_name = preferences.get("model", settings.ollama_default_model)
        chain = [p for p in (fallback_chain or self.fallback_chain) if p]

        # Try primary provider
        if provider in self.clients:
            client = self.clients[provider]
            if await self._check_client_health(client, model_name):
                self.logger.info("Using primary provider", provider=provider, model=model_name)
                return ResolvedClient(client=client, provider=provider, model=model_name, fallback=False)

        # Try fallback providers
        for fallback_provider in chain:
            if fallback_provider == provider:
                continue  # Skip if already tried

            if fallback_provider in self.clients:
                client = self.clients[fallback_provider]
                served_model = model_name
                healthy = await self._check_client_health(client, model_name)
                if (
                    not healthy
                    and isinstance(client, OllamaClient)
                    and model_name != settings.ollama_default_model
                ):
                    served_model = settings.ollama_default_model
                    healthy = await self._check_client_health(client, served_model)
                if healthy:
                    self.logger.info(
                        "Using fallback provider",
                        fallback=fallback_provider,
                        original=provider,
                        model=served_model,
                        requested_model=model_name,
                    )
                    return ResolvedClient(
                        client=client,
                        provider=fallback_provider,
                        model=served_model,
                        fallback=True,
                    )

        # If no client available, raise error
        raise RuntimeError(f"No available model clients. Tried: {provider} and fallbacks: {chain}")
    
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

