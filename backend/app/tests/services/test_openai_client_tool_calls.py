"""``OpenAIClient.complete_with_tools`` — the only tool-calling seam in the repo."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services.model_clients.openai_client import OpenAIClient


class _Recorder:
    """Minimal stand-in for ``AsyncOpenAI`` capturing the outgoing request."""

    def __init__(self, response, sink: dict) -> None:
        self._response = response
        self._sink = sink

    def __call__(self, **kwargs):
        self._sink["client_kwargs"] = kwargs
        return self

    @property
    def chat(self):
        return SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self._sink["request"] = kwargs
        return self._response


def _response(*, content=None, tool_calls=(), finish_reason="stop"):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=list(tool_calls)),
                finish_reason=finish_reason,
            )
        ],
        model="gpt-test",
        usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3, total_tokens=10),
    )


def _tool_call(call_id: str, name: str, arguments: str):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _install(monkeypatch, response) -> dict:
    sink: dict = {}
    monkeypatch.setattr("openai.AsyncOpenAI", _Recorder(response, sink))
    return sink


async def test_a_plain_answer_is_returned_with_no_tool_calls(monkeypatch):
    sink = _install(monkeypatch, _response(content="hello"))
    client = OpenAIClient(api_key="test-key")

    result = await client.complete_with_tools("gpt-test", [{"role": "user", "content": "hi"}])

    assert result["content"] == "hello"
    assert result["tool_calls"] == []
    assert result["finish_reason"] == "stop"
    assert result["usage"] == {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}
    assert "tools" not in sink["request"]


async def test_tool_specifications_and_choice_are_forwarded(monkeypatch):
    sink = _install(monkeypatch, _response(content="ok"))
    client = OpenAIClient(api_key="test-key")
    tools = [{"type": "function", "function": {"name": "search", "parameters": {}}}]

    await client.complete_with_tools(
        "gpt-test",
        [{"role": "user", "content": "hi"}],
        tools=tools,
    )

    assert sink["request"]["tools"] == tools
    assert sink["request"]["tool_choice"] == "auto"
    assert sink["request"]["model"] == "gpt-test"


async def test_tool_calls_are_returned_parsed_and_raw(monkeypatch):
    arguments = {"query": "réinitialiser", "top_k": 3}
    _install(
        monkeypatch,
        _response(
            tool_calls=[_tool_call("call_1", "search_knowledge", json.dumps(arguments))],
            finish_reason="tool_calls",
        ),
    )
    client = OpenAIClient(api_key="test-key")

    result = await client.complete_with_tools("gpt-test", [{"role": "user", "content": "hi"}])

    assert result["finish_reason"] == "tool_calls"
    assert result["tool_calls"] == [
        {
            "id": "call_1",
            "name": "search_knowledge",
            "arguments": arguments,
            # The raw form is what must be echoed back so the provider can match
            # a tool result to its call.
            "arguments_json": json.dumps(arguments),
        }
    ]


async def test_unparseable_arguments_are_surfaced_without_raising(monkeypatch):
    _install(
        monkeypatch,
        _response(tool_calls=[_tool_call("call_2", "search_knowledge", "{not json")]),
    )
    client = OpenAIClient(api_key="test-key")

    result = await client.complete_with_tools("gpt-test", [{"role": "user", "content": "hi"}])

    assert result["tool_calls"][0]["arguments"] is None
    assert result["tool_calls"][0]["arguments_json"] == "{not json"


async def test_empty_arguments_parse_to_an_empty_mapping(monkeypatch):
    _install(monkeypatch, _response(tool_calls=[_tool_call("call_3", "list_systems", "")]))
    client = OpenAIClient(api_key="test-key")

    result = await client.complete_with_tools("gpt-test", [{"role": "user", "content": "hi"}])

    assert result["tool_calls"][0]["arguments"] == {}


async def test_a_missing_api_key_fails_before_any_network_call():
    client = OpenAIClient(api_key="")
    client.api_key = None

    with pytest.raises(RuntimeError, match="API key"):
        await client.complete_with_tools("gpt-test", [{"role": "user", "content": "hi"}])


@pytest.mark.parametrize("method", ["generate", "complete_with_tools"])
@pytest.mark.parametrize("model", ["gpt-5", "gpt-5-mini-2025-08-07", "o3-mini"])
async def test_reasoning_models_use_completion_token_budget(monkeypatch, method, model):
    sink = _install(monkeypatch, _response(content="ok"))
    client = OpenAIClient(api_key="test-key")
    payload = "hello" if method == "generate" else [{"role": "user", "content": "hello"}]
    await getattr(client, method)(model, payload, max_tokens=10000)
    assert sink["request"]["max_completion_tokens"] == 10000
    assert "max_tokens" not in sink["request"]


def test_explicit_completion_budget_wins_and_legacy_models_keep_their_limit():
    assert OpenAIClient._chat_options("gpt-5", {"max_tokens": 10000, "max_completion_tokens": 500}) == {"max_completion_tokens": 500}
    assert OpenAIClient._chat_options("gpt-4o", {"max_tokens": 500}) == {"max_tokens": 500}
    assert OpenAIClient._chat_options(
        "gpt-5", {"max_tokens": 2000, "reasoning_effort": "minimal", "response_format": {"type": "json_object"}}
    ) == {
        "max_completion_tokens": 2000,
        "reasoning_effort": "minimal",
        "response_format": {"type": "json_object"},
    }


async def test_streaming_reasoning_model_uses_same_token_budget(monkeypatch):
    async def chunks():
        yield SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content="ok"), finish_reason="stop")], usage=None)
    sink = _install(monkeypatch, chunks())
    result = [chunk async for chunk in OpenAIClient(api_key="test-key").stream(
        "gpt-5", "hello", max_tokens=10000)]
    assert result[0]["content"] == "ok"
    assert sink["request"]["max_completion_tokens"] == 10000
    assert "max_tokens" not in sink["request"]
