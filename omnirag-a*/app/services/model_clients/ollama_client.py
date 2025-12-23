"""Ollama model client implementation"""
import httpx
from typing import AsyncGenerator, Dict, Any, List
from app.core.logging import get_logger

logger = get_logger(__name__)


class OllamaClient:
    """Client for interacting with Ollama API"""

    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url.rstrip("/")
        # Increased timeout for reasoning models like DeepSeek-R1
        # 5 minutes for reasoning models
        self.client = httpx.AsyncClient(timeout=300.0)
    
    async def list_models(self) -> List[Dict[str, Any]]:
        """List available models"""
        try:
            response = await self.client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            data = response.json()
            return data.get("models", [])
        except Exception as e:
            logger.error("Failed to list Ollama models", error=str(e))
            return []
    
    async def is_model_available(self, model_name: str) -> bool:
        """Check if a model is available"""
        try:
            models = await self.list_models()
            return any(model["name"] == model_name for model in models)
        except Exception as e:
            logger.error("Failed to check model availability", model=model_name, error=str(e))
            return False
    
    async def generate(
        self,
        model: str,
        prompt: str,
        num_ctx: int = None,
        rope_scale: float = None,
        rope_alpha: float = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate a response
        
        Args:
            model: Model name
            prompt: Input prompt
            num_ctx: Context window size (default: model's default, can be up to 1M for supported models)
            rope_scale: Rope scaling factor for extended context (optional)
            rope_alpha: Rope alpha parameter for scaling (optional)
            **kwargs: Additional Ollama API parameters
        """
        try:
            # For reasoning models, use longer timeout (5 minutes)
            timeout = 300.0
            client = httpx.AsyncClient(timeout=timeout)
            try:
                # Build options dict for Ollama
                options = kwargs.pop("options", {})
                
                # Add context window parameters
                if num_ctx is not None:
                    options["num_ctx"] = num_ctx
                if rope_scale is not None:
                    options["rope_freq_base"] = rope_scale
                    # Set rope scaling type if not specified
                    if "rope_scaling_type" not in options:
                        options["rope_scaling_type"] = "linear"  # Options: linear, yarn, dynamic
                if rope_alpha is not None:
                    options["rope_alpha"] = rope_alpha
                
                # Merge any remaining kwargs into options
                if options:
                    kwargs["options"] = options
                
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                        **kwargs
                    }
                )
                response.raise_for_status()
                return response.json()
            finally:
                await client.aclose()
        except httpx.TimeoutException as e:
            logger.error(
                "Timeout while generating response",
                model=model,
                error=str(e)
            )
            msg = (
                f"Model {model} timed out after {timeout} seconds. "
                "This may happen with reasoning models on complex queries."
            )
            raise TimeoutError(msg)
        except Exception as e:
            logger.error(
                "Failed to generate response",
                model=model,
                error=str(e)
            )
            raise
    
    async def stream(
        self,
        model: str,
        prompt: str,
        num_ctx: int = None,
        rope_scale: float = None,
        rope_alpha: float = None,
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Stream response tokens
        
        Args:
            model: Model name
            prompt: Input prompt
            num_ctx: Context window size (default: model's default, can be up to 1M for supported models)
            rope_scale: Rope scaling factor for extended context (optional)
            rope_alpha: Rope alpha parameter for scaling (optional)
            **kwargs: Additional Ollama API parameters
        """
        try:
            # For reasoning models, increase timeout (5 minutes)
            timeout = 300.0
            
            # Build options dict for Ollama
            options = kwargs.pop("options", {})
            
            # Add context window parameters
            if num_ctx is not None:
                options["num_ctx"] = num_ctx
            if rope_scale is not None:
                options["rope_freq_base"] = rope_scale
                # Set rope scaling type if not specified
                if "rope_scaling_type" not in options:
                    options["rope_scaling_type"] = "linear"  # Options: linear, yarn, dynamic
            if rope_alpha is not None:
                options["rope_alpha"] = rope_alpha
            
            # Merge any remaining kwargs into options
            if options:
                kwargs["options"] = options
            
            async with httpx.AsyncClient(timeout=timeout).stream(
                "POST",
                f"{self.base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": True,
                    **kwargs
                }
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        import json
                        try:
                            chunk = json.loads(line)
                            yield {
                                "content": chunk.get("response", ""),
                                "done": chunk.get("done", False),
                                "model": chunk.get("model", model),
                            }
                        except json.JSONDecodeError:
                            logger.warning(
                                "Failed to parse Ollama response chunk",
                                line=line
                            )
        except httpx.TimeoutException as e:
            logger.error(
                "Timeout while streaming response",
                model=model,
                error=str(e)
            )
            msg = (
                f"Model {model} timed out after {timeout} seconds. "
                "This may happen with reasoning models on complex queries."
            )
            raise TimeoutError(msg)
        except Exception as e:
            logger.error(
                "Failed to stream response",
                model=model,
                error=str(e)
            )
            raise
    
    async def health_check(self) -> bool:
        """Check if Ollama is available"""
        try:
            response = await self.client.get(f"{self.base_url}/api/tags")
            return response.status_code == 200
        except Exception:
            return False
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()
