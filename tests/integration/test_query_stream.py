"""Integration tests for POST /query/stream (SSE endpoint).

External dependencies (Celery task dispatch, OpenAI Responses API) are mocked so
the tests run without any live services.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from connections.fastapi.main import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _AsyncIter:
    """Minimal async iterator that wraps a plain list."""

    def __init__(self, items):
        self._it = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


def _mock_stream_cm(events):
    """Build an async context-manager mock that yields *events* on iteration."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=_AsyncIter(events))
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _delta_event(text: str):
    """Create a mock Responses-API output_text.delta event."""
    event = MagicMock()
    event.type = "response.output_text.delta"
    event.delta = text
    return event


def _parse_sse(lines) -> list[dict]:
    """Parse raw SSE lines into a list of ``{"event": str, "data": dict}``."""
    result: list[dict] = []
    current: dict = {}
    for line in lines:
        if line.startswith("event:"):
            current["event"] = line[6:].strip()
        elif line.startswith("data:"):
            current["data"] = json.loads(line[5:].strip())
        elif line == "" and current:
            result.append(current)
            current = {}
    if current:
        result.append(current)
    return result


# ---------------------------------------------------------------------------
# Fixtures & constants
# ---------------------------------------------------------------------------

VALID_PAYLOAD = {
    "collection_uuid": "00000000-0000-0000-0000-000000000001",
    "user_prompt": "What is RAG?",
}

FAKE_RETRIEVAL = {
    "combined_context": "RAG stands for Retrieval-Augmented Generation.",
    "system_prompt": "You are a helpful assistant.",
    "contexts": ["RAG stands for Retrieval-Augmented Generation."],
}


@pytest.fixture
def http():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_query_stream_success(http):
    """Happy path: retrieval_done → token events → done."""
    mock_task = MagicMock()
    mock_task.id = "task-abc"
    mock_task.get.return_value = FAKE_RETRIEVAL

    stream_events = [_delta_event("Hello"), _delta_event(","), _delta_event(" world")]

    with (
        patch(
            "connections.celery.tasks.retrieve_rag_context.apply_async",
            return_value=mock_task,
        ),
        patch("connections.fastapi.api.endpoints.query.openai_client") as mock_oai,
    ):
        mock_oai.responses.stream.return_value = _mock_stream_cm(stream_events)

        with http.stream("POST", "/query/stream", json=VALID_PAYLOAD) as resp:
            assert resp.status_code == 200
            events = _parse_sse(list(resp.iter_lines()))

    # retrieval_done event
    assert events[0]["event"] == "retrieval_done"
    assert events[0]["data"]["task_id"] == "task-abc"

    # token events
    token_events = [e for e in events if e["event"] == "token"]
    assert [e["data"]["content"] for e in token_events] == ["Hello", ",", " world"]

    # done event
    done = events[-1]
    assert done["event"] == "done"
    assert done["data"]["answer"] == "Hello, world"
    assert done["data"]["context"] == FAKE_RETRIEVAL["contexts"]

    # ZDR: store=False is always set; include is absent for non-reasoning models
    call_kwargs = mock_oai.responses.stream.call_args.kwargs
    assert call_kwargs["store"] is False
    assert "include" not in call_kwargs


def test_query_stream_uses_instructions_and_input(http):
    """Verify Chat Completions `messages` is replaced by `instructions` + `input`."""
    mock_task = MagicMock()
    mock_task.id = "task-xyz"
    mock_task.get.return_value = FAKE_RETRIEVAL

    with (
        patch(
            "connections.celery.tasks.retrieve_rag_context.apply_async",
            return_value=mock_task,
        ),
        patch("connections.fastapi.api.endpoints.query.openai_client") as mock_oai,
    ):
        mock_oai.responses.stream.return_value = _mock_stream_cm([])

        with http.stream("POST", "/query/stream", json=VALID_PAYLOAD) as resp:
            resp.read()  # consume stream

    call_kwargs = mock_oai.responses.stream.call_args.kwargs
    assert call_kwargs["instructions"] == FAKE_RETRIEVAL["system_prompt"]
    assert VALID_PAYLOAD["user_prompt"] in call_kwargs["input"]
    assert "messages" not in call_kwargs


def test_query_stream_reasoning_model_includes_encrypted_content(http):
    """Reasoning models (o-series, gpt-5) get include=["reasoning.encrypted_content"]."""
    mock_task = MagicMock()
    mock_task.id = "task-reasoning"
    mock_task.get.return_value = FAKE_RETRIEVAL

    reasoning_payload = {**VALID_PAYLOAD, "generation": {"model_name": "o3"}}

    with (
        patch(
            "connections.celery.tasks.retrieve_rag_context.apply_async",
            return_value=mock_task,
        ),
        patch("connections.fastapi.api.endpoints.query.openai_client") as mock_oai,
    ):
        mock_oai.responses.stream.return_value = _mock_stream_cm([])

        with http.stream("POST", "/query/stream", json=reasoning_payload) as resp:
            resp.read()

    call_kwargs = mock_oai.responses.stream.call_args.kwargs
    assert call_kwargs["store"] is False
    assert call_kwargs.get("include") == ["reasoning.encrypted_content"]


def test_query_stream_retrieval_timeout(http):
    """Retrieval timeout → single error event, no crash."""
    mock_task = MagicMock()
    mock_task.id = "task-timeout"
    mock_task.get.side_effect = TimeoutError

    with patch(
        "connections.celery.tasks.retrieve_rag_context.apply_async",
        return_value=mock_task,
    ):
        with http.stream("POST", "/query/stream", json=VALID_PAYLOAD) as resp:
            assert resp.status_code == 200
            events = _parse_sse(list(resp.iter_lines()))

    assert events[0]["event"] == "retrieval_done"
    error_event = next(e for e in events if e["event"] == "error")
    assert "timed out" in error_event["data"]["message"]
    # no done event after a timeout
    assert not any(e["event"] == "done" for e in events)


def test_query_stream_retrieval_exception(http):
    """Arbitrary retrieval error → error event with message."""
    mock_task = MagicMock()
    mock_task.id = "task-err"
    mock_task.get.side_effect = RuntimeError("qdrant unreachable")

    with patch(
        "connections.celery.tasks.retrieve_rag_context.apply_async",
        return_value=mock_task,
    ):
        with http.stream("POST", "/query/stream", json=VALID_PAYLOAD) as resp:
            assert resp.status_code == 200
            events = _parse_sse(list(resp.iter_lines()))

    error_event = next(e for e in events if e["event"] == "error")
    assert "qdrant unreachable" in error_event["data"]["message"]
