"""Anthropic (Claude) model client implementation"""

import os
from typing import Any, AsyncGenerator, Optional

from app.core.logging import get_logger
from app.services.model_clients.base import ModelClient
from app.services.model_usage_transport import metered_model_method, response_usage, tracking_active

logger = get_logger(__name__)


class AnthropicClient(ModelClient):
    """Client for interacting with Anthropic API"""

    def __init__(self, api_key: Optional[str] = None, *, max_retries: Optional[int] = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.max_retries = max_retries
        self.logger = get_logger(__name__)

        if not self.api_key:
            self.logger.warning("Anthropic API key not provided")

    @metered_model_method("anthropic", default_output=1024)
    async def generate(self, model: str, prompt: str, **kwargs) -> dict[str, Any]:
        """Generate a response"""
        if not self.api_key:
            raise RuntimeError("Anthropic API key not configured")

        try:
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(
                api_key=self.api_key,
                **(
                    {"max_retries": 0}
                    if tracking_active()
                    else ({"max_retries": self.max_retries} if self.max_retries is not None else {})
                ),
            )

            response = await client.messages.create(
                model=model,
                max_tokens=kwargs.get("max_tokens", 1024),
                messages=[{"role": "user", "content": prompt}],
                **{k: v for k, v in kwargs.items() if k != "max_tokens"},
            )

            return {
                "content": response.content[0].text,
                "model": response.model,
                "id": getattr(response, "id", None),
                "output_truncated": getattr(response, "stop_reason", None) == "max_tokens",
                "usage": response_usage(response, provider="anthropic"),
            }
        except ImportError:
            raise RuntimeError(
                "Anthropic package not installed. Install with: pip install anthropic"
            )
        except Exception as e:
            self.logger.error("Anthropic generation error", error=str(e))
            raise

    @metered_model_method("anthropic", default_output=1024)
    async def stream(
        self, model: str, prompt: str, **kwargs
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream response tokens"""
        if not self.api_key:
            raise RuntimeError("Anthropic API key not configured")

        try:
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(
                api_key=self.api_key,
                **(
                    {"max_retries": 0}
                    if tracking_active()
                    else ({"max_retries": self.max_retries} if self.max_retries is not None else {})
                ),
            )

            stream = await client.messages.create(
                model=model,
                max_tokens=kwargs.get("max_tokens", 1024),
                messages=[{"role": "user", "content": prompt}],
                stream=True,
                **{k: v for k, v in kwargs.items() if k != "max_tokens"},
            )

            sequence = 0
            reported = {}
            returned_model = model
            async for event in stream:
                if event.type == "message_start":
                    message = event.message
                    returned_model = getattr(message, "model", model)
                    source = getattr(message, "usage", None)
                    for key in (
                        "input_tokens",
                        "output_tokens",
                        "cache_read_input_tokens",
                        "cache_creation_input_tokens",
                    ):
                        value = getattr(source, key, None)
                        if type(value) is int:
                            reported[key] = value
                elif event.type == "message_delta":
                    value = getattr(getattr(event, "usage", None), "output_tokens", None)
                    if type(value) is int:
                        reported["output_tokens"] = value
                elif event.type == "content_block_delta":
                    sequence += 1
                    delta = event.delta.text or ""
                    yield {"content": delta, "delta": delta, "sequence": sequence, "done": False}
                elif event.type == "message_stop":
                    counters = response_usage({"usage": reported}, provider="anthropic")
                    if counters is not None:
                        yield {"usage": counters, "model": returned_model}
                    yield {"content": "", "delta": "", "sequence": sequence + 1, "done": True}
        except ImportError:
            raise RuntimeError(
                "Anthropic package not installed. Install with: pip install anthropic"
            )
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
