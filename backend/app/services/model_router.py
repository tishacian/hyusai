"""Model connections; explicit providers never silently fall back."""

import os
from typing import Any, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.services.model_clients.base import ModelClient
from app.services.model_clients.ollama_client import OllamaClient

logger = get_logger(__name__)


class ModelRouter:
    """Routes requests to appropriate model providers with fallback"""

    def __init__(self, workspace=None, *, workspace_id: Optional[str] = None):
        self.workspace = workspace
        self.workspace_id = workspace_id or getattr(workspace, "id", None)
        self.clients: dict[str, ModelClient] = {}
        self.fallback_chain: list[str] = ["ollama"]  # Default fallback order
        self.logger = get_logger(__name__)
        self._initialize_clients()

    def _provider_api_key(self, provider: str, env_name: str) -> tuple[Optional[str], bool]:
        """Resolve a workspace credential before falling back to the process environment."""
        if self.workspace_id:
            try:
                from app.services.model_plane.workspace_config import get_runtime_provider_config

                runtime = get_runtime_provider_config(self.workspace_id, provider)
                if runtime.get("api_key"):
                    return runtime["api_key"], True
            except Exception as exc:
                self.logger.warning(
                    "Workspace model credential lookup failed",
                    workspace_id=self.workspace_id,
                    provider=provider,
                    error_type=type(exc).__name__,
                )
        return os.getenv(env_name), False

    def _initialize_clients(self):
        """Initialize model clients"""
        # Initialize Ollama client (always available)
        ollama_client = OllamaClient(base_url=settings.ollama_base_url)
        self.clients["ollama"] = ollama_client

        # Initialize OpenAI client if API key is available
        try:
            from app.services.model_clients.openai_client import OpenAIClient

            openai_key, _ = self._provider_api_key("openai", "OPENAI_API_KEY")
            if openai_key:
                openai_client = OpenAIClient(api_key=openai_key)
                self.clients["openai"] = openai_client
                self.fallback_chain.append("openai")
        except Exception as e:
            self.logger.debug("OpenAI client not initialized", error=str(e))

        # Initialize Anthropic client if API key is available
        try:
            from app.services.model_clients.anthropic_client import AnthropicClient

            anthropic_key, workspace_credential = self._provider_api_key(
                "anthropic", "ANTHROPIC_API_KEY"
            )
            if anthropic_key:
                base_url = AnthropicClient.DEFAULT_BASE_URL if workspace_credential else None
                anthropic_client = AnthropicClient(api_key=anthropic_key, base_url=base_url)
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

    async def get_client(self, preferences: Optional[dict[str, Any]] = None) -> ModelClient:
        """Return the exact selected connection; completion owns fallback attempts.

        A raw client cannot swap provider safely: its caller still holds the
        original model name. Workspace-routed Skills use complete_model, which
        resolves/checks each provider/model pair and records every attempt.
        """
        from app.services.model_plane.execution import build_model_client, resolve_model_execution

        preferences = preferences or {}
        provider = preferences.get("provider")
        if provider in {
            None,
            "workspace",
            "openai",
            "azure_openai",
            "azure",
            "ollama",
            "anthropic",
        }:
            execution = resolve_model_execution(
                self.workspace,
                provider=provider,
                model=preferences.get("model"),
            )
            client = build_model_client(execution)
            client.model_execution = execution
            return client
        if self.workspace is not None:
            raise RuntimeError("This provider has no workspace-scoped text runtime.")
        client = self.clients.get(provider)
        if client is not None and await self._check_client_health(
            client, preferences.get("model", "")
        ):
            return client
        raise RuntimeError(f"The selected provider is unavailable: {provider}")

    async def _check_client_health(self, client: ModelClient, model_name: str) -> bool:
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

    def set_fallback_chain(self, chain: list[str]):
        """Set the fallback chain"""
        self.fallback_chain = chain
        self.logger.info("Fallback chain updated", chain=chain)

    async def list_available_models(self) -> dict[str, list[dict[str, Any]]]:
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
                            "modified_at": model.get("modified_at", ""),
                        }
                        for model in models
                    ]
            except Exception as e:
                self.logger.warning("Failed to list models", provider=provider, error=str(e))
                all_models[provider] = []

        return all_models
