from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.llm.models import CompletionRequest
import app.llm.providers.openai_provider as openai_provider
from app.llm.providers.openai_provider import OpenAIProvider


class FakeResponses:
    def __init__(self):
        self.create_kwargs = None
        self.stream_kwargs = None

    async def create(self, **kwargs):
        self.create_kwargs = kwargs
        return SimpleNamespace(
            id="resp-1",
            model=kwargs["model"],
            created_at=123,
            output_text="response answer",
            status="completed",
            usage=SimpleNamespace(input_tokens=4, output_tokens=2, total_tokens=6),
        )

    def stream(self, **kwargs):
        self.stream_kwargs = kwargs
        return FakeResponsesStream()


class FakeResponsesStream:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def __aiter__(self):
        async def _events():
            yield SimpleNamespace(type="response.output_text.delta", delta="hel")
            yield SimpleNamespace(type="response.output_text.delta", delta="lo")
            yield SimpleNamespace(type="response.completed", delta="")

        return _events()


class FakeAsyncOpenAI:
    last_instance = None

    def __init__(self, **_kwargs):
        self.responses = FakeResponses()
        FakeAsyncOpenAI.last_instance = self


def _request() -> CompletionRequest:
    return CompletionRequest(
        model="gpt-5",
        messages=[
            {"role": "system", "content": "System instructions"},
            {"role": "user", "content": "Hello"},
        ],
        temperature=0.3,
        max_tokens=20,
    )


@pytest.fixture(autouse=True)
def _fake_openai(monkeypatch):
    monkeypatch.setattr(openai_provider, "AsyncOpenAI", FakeAsyncOpenAI)
    monkeypatch.setattr(settings, "openai_responses_api_enabled", True)
    monkeypatch.setattr(
        settings,
        "openai_responses_include_reasoning_encrypted_content",
        True,
    )


async def test_openai_generate_uses_responses_api_store_false():
    provider = OpenAIProvider(api_key="test-key")

    response = await provider.generate(_request())

    kwargs = FakeAsyncOpenAI.last_instance.responses.create_kwargs
    assert kwargs["store"] is False
    assert kwargs["instructions"] == "System instructions"
    assert kwargs["input"] == [{"role": "user", "content": "Hello"}]
    assert kwargs["max_output_tokens"] == 20
    assert kwargs["include"] == ["reasoning.encrypted_content"]
    assert response.choices[0].message.content == "response answer"
    assert response.usage.total_tokens == 6


async def test_openai_stream_uses_responses_api_deltas():
    provider = OpenAIProvider(api_key="test-key")

    chunks = [chunk async for chunk in provider.stream_generate(_request())]

    kwargs = FakeAsyncOpenAI.last_instance.responses.stream_kwargs
    assert kwargs["store"] is False
    assert [c.choices[0].delta["content"] for c in chunks] == ["hel", "lo"]
