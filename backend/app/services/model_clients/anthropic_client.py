"""Anthropic (Claude) model client implementation"""

import inspect
import os
import re
from typing import Any, AsyncGenerator, Optional

from app.core.logging import get_logger
from app.services.model_clients.base import ModelClient

logger = get_logger(__name__)


class AnthropicClient(ModelClient):
    """Client for interacting with Anthropic API"""

    DEFAULT_BASE_URL = "https://api.anthropic.com"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.base_url = base_url
        self.logger = get_logger(__name__)

        if not self.api_key:
            self.logger.warning("Anthropic API key not provided")

    @staticmethod
    def _supports_configurable_temperature(model: str) -> bool:
        """Return whether Anthropic accepts an explicit temperature value."""

        match = re.match(
            r"^claude-(opus|sonnet)-(\d+)(?:-(\d+))?",
            str(model or "").strip().lower(),
        )
        if match:
            major = int(match.group(2))
            minor = int(match.group(3) or 0)
            return major < 5 and not (major == 4 and minor >= 7)
        return not str(model or "").strip().lower().startswith(("claude-fable-", "claude-mythos-"))

    @classmethod
    def _generation_options(cls, model: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Translate Agentium generation options to the selected Claude model."""

        options = {key: value for key, value in kwargs.items() if key != "max_tokens"}
        if not cls._supports_configurable_temperature(model):
            options.pop("temperature", None)
        return options

    @staticmethod
    def _text_content(blocks: Any) -> str:
        """Return user-visible text while ignoring adaptive-thinking blocks."""

        return "".join(text for block in (blocks or []) if (text := getattr(block, "text", "")))

    @staticmethod
    def _supported_options(create_method: Any, options: dict[str, Any]) -> dict[str, Any]:
        """Keep only options supported by the installed Anthropic SDK."""

        signature = inspect.signature(create_method)
        if any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        ):
            return options
        accepted = set(signature.parameters)
        return {key: value for key, value in options.items() if key in accepted}

    async def generate(self, model: str, prompt: str, **kwargs) -> dict[str, Any]:
        """Generate a response"""
        if not self.api_key:
            raise RuntimeError("Anthropic API key not configured")

        try:
            from anthropic import AsyncAnthropic

            client_options = {"api_key": self.api_key}
            if self.base_url:
                client_options["base_url"] = self.base_url
            client = AsyncAnthropic(**client_options)

            options = self._supported_options(
                client.messages.create,
                self._generation_options(model, kwargs),
            )
            response = await client.messages.create(
                model=model,
                max_tokens=kwargs.get("max_tokens", 1024),
                messages=[{"role": "user", "content": prompt}],
                **options,
            )

            return {
                "content": self._text_content(response.content),
                "model": response.model,
                "usage": {
                    "prompt_tokens": response.usage.input_tokens,
                    "completion_tokens": response.usage.output_tokens,
                    "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
                },
            }
        except ImportError:
            raise RuntimeError(
                "Anthropic package not installed. Install with: pip install anthropic"
            )
        except Exception as e:
            self.logger.error("Anthropic generation error", error=str(e))
            raise

    async def stream(
        self, model: str, prompt: str, **kwargs
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream response tokens"""
        if not self.api_key:
            raise RuntimeError("Anthropic API key not configured")

        try:
            from anthropic import AsyncAnthropic

            client_options = {"api_key": self.api_key}
            if self.base_url:
                client_options["base_url"] = self.base_url
            client = AsyncAnthropic(**client_options)

            options = self._supported_options(
                client.messages.create,
                self._generation_options(model, kwargs),
            )
            stream = await client.messages.create(
                model=model,
                max_tokens=kwargs.get("max_tokens", 1024),
                messages=[{"role": "user", "content": prompt}],
                stream=True,
                **options,
            )

            sequence = 0
            async for event in stream:
                if event.type == "content_block_delta":
                    delta = getattr(event.delta, "text", "") or ""
                    if not delta:
                        continue
                    sequence += 1
                    yield {"content": delta, "delta": delta, "sequence": sequence, "done": False}
                elif event.type == "message_stop":
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

            client_options = {"api_key": self.api_key}
            if self.base_url:
                client_options["base_url"] = self.base_url
            client = AsyncAnthropic(**client_options)
            # Simple health check - try to list models (if API supports it)
            # For now, just check if we can create a client
            return True
        except Exception:
            return False
