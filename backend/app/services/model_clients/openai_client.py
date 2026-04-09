"""OpenAI model client implementation"""
from typing import AsyncGenerator, Dict, Any, Optional
from app.core.logging import get_logger
from app.services.model_clients.base import ModelClient
import os

logger = get_logger(__name__)


class OpenAIClient(ModelClient):
    """Client for interacting with OpenAI API"""
    
    def __init__(self, api_key: Optional[str] = None, base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.logger = get_logger(__name__)
        
        if not self.api_key:
            self.logger.warning("OpenAI API key not provided")
    
    async def generate(
        self, 
        model: str, 
        prompt: str, 
        **kwargs
    ) -> Dict[str, Any]:
        """Generate a response"""
        if not self.api_key:
            raise RuntimeError("OpenAI API key not configured")
        
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
            
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                **kwargs
            )
            
            return {
                "content": response.choices[0].message.content,
                "model": response.model,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            }
        except ImportError:
            raise RuntimeError("OpenAI package not installed. Install with: pip install openai")
        except Exception as e:
            self.logger.error("OpenAI generation error", error=str(e))
            raise
    
    async def stream(
        self, 
        model: str, 
        prompt: str, 
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream response tokens"""
        if not self.api_key:
            raise RuntimeError("OpenAI API key not configured")
        
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
            
            stream = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
                **kwargs
            )
            
            sequence = 0
            async for chunk in stream:
                sequence += 1
                delta = chunk.choices[0].delta.content or ""
                yield {
                    "content": delta,
                    "delta": delta,
                    "sequence": sequence,
                    "done": chunk.choices[0].finish_reason is not None
                }
        except ImportError:
            raise RuntimeError("OpenAI package not installed. Install with: pip install openai")
        except Exception as e:
            self.logger.error("OpenAI streaming error", error=str(e))
            raise
    
    async def health_check(self) -> bool:
        """Check if OpenAI API is available"""
        if not self.api_key:
            return False
        
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
            # Simple health check - list models
            await client.models.list()
            return True
        except Exception:
            return False

