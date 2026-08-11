"""OpenAI model client implementation"""
from typing import AsyncGenerator, Dict, Any, Optional
from app.core.logging import get_logger
from app.services.model_clients.base import ModelClient
import json
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
    
    async def complete_with_tools(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        **kwargs,
    ) -> dict[str, Any]:
        """One chat completion turn that may answer or request tool calls.

        ``messages`` is passed through verbatim, so the caller owns the whole
        transcript including previous ``assistant`` messages carrying
        ``tool_calls`` and their matching ``tool`` results. Tool call arguments
        are returned both parsed (``arguments``) and raw (``arguments_json``);
        the raw form is what must be echoed back in the transcript so the
        provider can match a result to its call.
        """
        if not self.api_key:
            raise RuntimeError("OpenAI API key not configured")

        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

            request: dict[str, Any] = {"model": model, "messages": messages, **kwargs}
            if tools:
                request["tools"] = tools
                request["tool_choice"] = tool_choice
            response = await client.chat.completions.create(**request)
        except ImportError:
            raise RuntimeError("OpenAI package not installed. Install with: pip install openai")
        except Exception as e:
            self.logger.error("OpenAI tool completion error", error=str(e), model=model)
            raise

        choice = response.choices[0]
        message = choice.message
        tool_calls: list[dict[str, Any]] = []
        for call in getattr(message, "tool_calls", None) or []:
            function = getattr(call, "function", None)
            raw_arguments = getattr(function, "arguments", "") or ""
            try:
                parsed = json.loads(raw_arguments) if raw_arguments.strip() else {}
            except (TypeError, ValueError):
                parsed = None
            tool_calls.append(
                {
                    "id": getattr(call, "id", "") or "",
                    "name": getattr(function, "name", "") or "",
                    "arguments": parsed if isinstance(parsed, dict) else None,
                    "arguments_json": raw_arguments,
                }
            )
        usage = getattr(response, "usage", None)
        return {
            "content": getattr(message, "content", None) or "",
            "tool_calls": tool_calls,
            "finish_reason": getattr(choice, "finish_reason", None),
            "model": getattr(response, "model", model),
            "usage": {
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            },
        }

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

