"""Anthropic (Claude) model client implementation"""
from typing import AsyncGenerator, Dict, Any, Optional
from app.core.logging import get_logger
from app.services.model_clients.base import ModelClient
import os

logger = get_logger(__name__)


class AnthropicClient(ModelClient):
    """Client for interacting with Anthropic API"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.logger = get_logger(__name__)
        
        if not self.api_key:
            self.logger.warning("Anthropic API key not provided")
    
    async def generate(
        self, 
        model: str, 
        prompt: str, 
        **kwargs
    ) -> Dict[str, Any]:
        """Generate a response"""
        if not self.api_key:
            raise RuntimeError("Anthropic API key not configured")
        
        try:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=self.api_key)
            
            response = await client.messages.create(
                model=model,
                max_tokens=kwargs.get("max_tokens", 1024),
                messages=[{"role": "user", "content": prompt}],
                **{k: v for k, v in kwargs.items() if k != "max_tokens"}
            )
            
            return {
                "content": response.content[0].text,
                "model": response.model,
                "usage": {
                    "prompt_tokens": response.usage.input_tokens,
                    "completion_tokens": response.usage.output_tokens,
                    "total_tokens": response.usage.input_tokens + response.usage.output_tokens
                }
            }
        except ImportError:
            raise RuntimeError("Anthropic package not installed. Install with: pip install anthropic")
        except Exception as e:
            self.logger.error("Anthropic generation error", error=str(e))
            raise
    
    async def stream(
        self, 
        model: str, 
        prompt: str, 
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream response tokens"""
        if not self.api_key:
            raise RuntimeError("Anthropic API key not configured")
        
        try:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=self.api_key)
            
            stream = await client.messages.create(
                model=model,
                max_tokens=kwargs.get("max_tokens", 1024),
                messages=[{"role": "user", "content": prompt}],
                stream=True,
                **{k: v for k, v in kwargs.items() if k != "max_tokens"}
            )
            
            sequence = 0
            async for event in stream:
                if event.type == "content_block_delta":
                    sequence += 1
                    delta = event.delta.text or ""
                    yield {
                        "content": delta,
                        "delta": delta,
                        "sequence": sequence,
                        "done": False
                    }
                elif event.type == "message_stop":
                    yield {
                        "content": "",
                        "delta": "",
                        "sequence": sequence + 1,
                        "done": True
                    }
        except ImportError:
            raise RuntimeError("Anthropic package not installed. Install with: pip install anthropic")
        except Exception as e:
            self.logger.error("Anthropic streaming error", error=str(e))
            raise
    
    async def health_check(self) -> bool:
        """Check if Anthropic API is available"""
        if not self.api_key:
            return False
        
        try:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=self.api_key)
            # Simple health check - try to list models (if API supports it)
            # For now, just check if we can create a client
            return True
        except Exception:
            return False

