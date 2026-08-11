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
