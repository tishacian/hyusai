"""Model router for intelligent model selection and fallback"""
from typing import Any, Dict, List, Optional
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
        self.credential_sources: Dict[str, str] = {}
        self.fallback_chain: List[str] = ["ollama"]  # Default fallback order
        self.last_route: Optional[Dict[str, Any]] = None
        self.logger = get_logger(__name__)
        self._initialize_clients()
    
    def _initialize_clients(self):
        """Initialize model clients from process env, then local serving."""
        # Initialize Ollama client (always available)
        ollama_client = OllamaClient(base_url=settings.ollama_base_url)
        self.clients["ollama"] = ollama_client
        self.credential_sources["ollama"] = "env"
        
        # Initialize OpenAI client if API key is available
        try:
            from app.services.model_clients.openai_client import OpenAIClient
            openai_client = OpenAIClient(api_key=os.getenv("OPENAI_API_KEY"))
            self.clients["openai"] = openai_client
            if getattr(openai_client, "api_key", None):
                self.credential_sources["openai"] = "env"
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
                self.credential_sources["anthropic"] = "env"
                self.fallback_chain.append("anthropic")
        except Exception as e:
            self.logger.debug("Anthropic client not initialized", error=str(e))

        self._register_env_cloud_clients()

        # Active serving instances (vLLM / OpenAI-compatible) from model_plane.
        self._register_serving_providers()
        
        self.logger.info("Model router initialized", clients=list(self.clients.keys()))

    def _register_env_cloud_clients(self) -> None:
        """Cloud clients the portal also probes, when only env keys are set."""
        from app.services.model_clients.openai_client import OpenAIClient

        azure_key = os.getenv("AZURE_OPENAI_API_KEY")
        azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        if azure_key and azure_endpoint and "azure_openai" not in self.clients:
            self.clients["azure_openai"] = OpenAIClient(
                api_key=azure_key,
                azure_endpoint=azure_endpoint,
                api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
            )
            self.credential_sources["azure_openai"] = "env"

        foundry_key = os.getenv("AZURE_FOUNDRY_API_KEY")
        foundry_endpoint = os.getenv("AZURE_FOUNDRY_ENDPOINT")
        if foundry_key and foundry_endpoint and "azure_foundry" not in self.clients:
            self.clients["azure_foundry"] = OpenAIClient(
                api_key=foundry_key,
                azure_endpoint=foundry_endpoint,
                api_version=os.getenv("AZURE_FOUNDRY_API_VERSION"),
            )
            self.credential_sources["azure_foundry"] = "env"

        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        if openrouter_key and "openrouter" not in self.clients:
            self.clients["openrouter"] = OpenAIClient(
                api_key=openrouter_key,
                base_url="https://openrouter.ai/api/v1",
            )
            self.credential_sources["openrouter"] = "env"

    def apply_workspace(self, workspace: Any) -> None:
        """Overlay workspace ``llm_portal`` credentials and routing on env clients."""
        from app.services.model_plane import workspace_config as ws_cfg
        from app.services.model_clients.openai_client import OpenAIClient
        from app.services.model_clients.anthropic_client import AnthropicClient

        routing = ws_cfg.get_routing(workspace)
        chain = routing.get("fallback_chain")
        if isinstance(chain, list) and chain:
            self.set_fallback_chain([str(item) for item in chain if str(item).strip()])

        for provider in ws_cfg.CLOUD_PROVIDERS:
            key = ws_cfg.get_decrypted_api_key(workspace, provider)
            if not key:
                continue
            meta = ws_cfg.get_provider_meta(workspace, provider)
            try:
                if provider == "openai":
                    self.clients[provider] = OpenAIClient(api_key=key)
                elif provider == "anthropic":
                    self.clients[provider] = AnthropicClient(api_key=key)
                elif provider in {"azure_openai", "azure_foundry"}:
                    endpoint = meta.get("endpoint") or (
                        os.getenv("AZURE_OPENAI_ENDPOINT")
                        if provider == "azure_openai"
                        else os.getenv("AZURE_FOUNDRY_ENDPOINT")
                    )
                    if not endpoint:
                        continue
                    self.clients[provider] = OpenAIClient(
                        api_key=key,
                        azure_endpoint=endpoint,
                        api_version=meta.get("api_version"),
                    )
                elif provider == "openrouter":
                    self.clients[provider] = OpenAIClient(
                        api_key=key,
                        base_url="https://openrouter.ai/api/v1",
                    )
                else:
                    continue
                self.credential_sources[provider] = "workspace"
            except Exception as exc:  # noqa: BLE001
                self.logger.debug(
                    "Workspace provider client skipped",
                    provider=provider,
                    error=str(exc),
                )

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
                self.credential_sources[key] = "env"
            except Exception as e:
                self.logger.debug(
                    "Failed to register serving provider",
                    key=key,
                    error=str(e),
                )
    
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
                self.last_route = {
                    "provider": provider,
                    "model": model_name,
                    "effective_model": model_name,
                    "credential_source": self.credential_sources.get(provider),
                }
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
                    self.last_route = {
                        "provider": fallback_provider,
                        "model": model_name,
                        "effective_model": model_name,
                        "credential_source": self.credential_sources.get(fallback_provider),
                    }
                    return client
        
        # If no client available, raise error
        self.last_route = None
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

