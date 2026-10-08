"""Structured calls retain the model policy, reservations and provider ledger."""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from app.services.model_plane import execution as runtime


SCHEMA = {
    "type": "object", "properties": {"label": {"type": "string"}},
    "required": ["label"], "additionalProperties": False,
}


def execution(provider="openai", **overrides):
    return runtime.ModelExecution(
        provider=provider, model="configured-model", credential_source="workspace",
        model_source="workspace", _api_key="synthetic-key",
        _endpoint="https://synthetic.openai.azure.com", _api_version="2024-10-21",
        **overrides,
    )


def test_label_skill_is_resolved_before_policy_including_frozen_binding(monkeypatch):
    requests = []
    monkeypatch.setattr(runtime, "resolve_model_execution", lambda workspace, **kwargs: requests.append(kwargs))
    runtime.resolve_skill_model_execution(
        object(), executor=None, input_ref={}, slug="llm_label_dataset_v1",
        system_default_model="system-model",
    )
    runtime.resolve_skill_model_execution(
        object(), slug="ws.bound.label", input_ref={"model": "caller-model"},
        executor={"kind": "registry_call", "params": {
            "skill_slug": "llm_label_dataset_v1", "frozen_input": {"model": "pinned-model"},
        }},
    )
    assert [(r["provider"], r["model"], r["model_source"]) for r in requests] == [
        ("workspace", "system-model", "system"), ("workspace", "pinned-model", "executor"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai", "azure_openai", "ollama"])
async def test_schema_translation_and_reservation_order(monkeypatch, provider):
    events, requests = [], []
    options = {"json_schema": copy.deepcopy(SCHEMA), "max_tokens": 40, "temperature": 0}
    original = copy.deepcopy(options)
    resolved = execution(provider)

    class Client:
        async def generate(self, **kwargs):
            events.append("dispatch")
            requests.append(kwargs)
            return {"content": '{"label":"ok"}', "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}

    def build(actual):
        assert actual is resolved
        events.append("build")
        return Client()

    def reserve(actual, prompt, neutral):
        assert actual is resolved and prompt == "private input" and neutral == original
        assert ctx["_provider_usage_v1"]["calls"] == []
        assert ctx["_model_resolution_evidence"]["attempts"][-1]["dispatch_started"] is False
        events.append("reserve")
        neutral["json_schema"]["properties"].clear()
        neutral["max_tokens"] = 1

    monkeypatch.setattr(runtime, "build_model_client", build)
    ctx = {"_model_policy_check": lambda _: events.append("policy"), "_model_before_dispatch": reserve}
    result = await runtime.complete_model(resolved, "private input", ctx, generation_options=options, stream=False)
    assert events == ["policy", "build", "reserve", "dispatch"]
    request = requests[0]
    assert "json_schema" not in request
    if provider == "ollama":
        assert request["format"] == SCHEMA
        assert request["options"] == {"num_predict": 40, "temperature": 0}
        assert "max_tokens" not in request and "response_format" not in request
    else:
        assert request["max_tokens"] == 40
        assert request["response_format"] == {
            "type": "json_schema", "json_schema": {"name": "structured_response", "strict": True, "schema": SCHEMA},
        }
    assert options == original
    assert result["usage"]["total_tokens"] == 5 and result["usage"]["provider_calls"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,options,reason", [
    ("anthropic", {"json_schema": SCHEMA}, "not supported"),
    ("openai", {"json_schema": {"$ref": "https://untrusted.test/schema"}}, "local"),
    ("openai", {"json_schema": SCHEMA, "response_format": {"type": "json_object"}}, "cannot be combined"),
])
async def test_invalid_structured_configuration_refuses_before_reservation_or_fallback(monkeypatch, provider, options, reason):
    def forbidden(*args, **kwargs):
        raise AssertionError("No client or reservation is allowed")

    monkeypatch.setattr(runtime, "build_model_client", forbidden)
    ctx = {"_model_before_dispatch": forbidden}
    resolved = execution(provider, _fallbacks=(execution("ollama"),))
    with pytest.raises(ValueError, match=reason):
        await runtime.complete_model(resolved, "x", ctx, generation_options=options)
    assert ctx["_provider_usage_v1"]["calls"] == []
    assert "_model_execution_evidence" not in ctx
    attempts = ctx["_model_resolution_evidence"]["attempts"]
    assert len(attempts) == 1 and attempts[0]["status"] == "blocked"


@pytest.mark.asyncio
async def test_budget_refusal_is_not_a_provider_error_or_a_reason_to_fallback(monkeypatch):
    built = []
    refusal = ValueError("label_budget_exhausted")

    def build(candidate):
        built.append(candidate.provider)
        return SimpleNamespace()

    def reserve(*_):
        raise refusal

    monkeypatch.setattr(runtime, "build_model_client", build)
    ctx = {"_model_before_dispatch": reserve}
    with pytest.raises(ValueError) as caught:
        await runtime.complete_model(execution(_fallbacks=(execution("ollama"),)), "x", ctx)
    assert caught.value is refusal and built == ["openai"]
    assert ctx["_provider_usage_v1"]["calls"] == []
    assert "_model_execution_evidence" not in ctx
    assert ctx["_model_resolution_evidence"]["attempts"][-1]["dispatch_started"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("refuse_at", [None, "policy", "reservation"])
async def test_every_fallback_is_rechecked_reserved_and_translated(monkeypatch, refuse_at):
    events = []
    resolved = execution(_fallbacks=(execution("ollama"),))

    class Client:
        def __init__(self, candidate):
            self.provider = candidate.provider
            events.append((self.provider, "build"))

        async def generate(self, **kwargs):
            events.append((self.provider, "dispatch"))
            if self.provider == "openai":
                assert kwargs["response_format"]["type"] == "json_schema"
                raise TimeoutError("transport")
            assert kwargs["format"] == SCHEMA and "response_format" not in kwargs
            return {"response": '{"label":"ok"}', "prompt_eval_count": 2, "eval_count": 3}

    def policy(candidate):
        events.append((candidate.provider, "policy"))
        if candidate.provider == "ollama" and refuse_at == "policy":
            raise ValueError("fallback denied")

    def reserve(candidate, prompt, options):
        events.append((candidate.provider, "reservation"))
        if candidate.provider == "ollama":
            assert len(ctx["_provider_usage_v1"]["calls"]) == 1
            if refuse_at == "reservation":
                raise ValueError("fallback denied")

    monkeypatch.setattr(runtime, "build_model_client", Client)
    ctx = {"_model_policy_check": policy, "_model_before_dispatch": reserve}
    call = runtime.complete_model(resolved, "x", ctx, generation_options={"json_schema": SCHEMA}, stream=False)
    if refuse_at:
        with pytest.raises(ValueError, match="fallback denied"):
            await call
        assert len(ctx["_provider_usage_v1"]["calls"]) == 1
        assert ctx["_model_execution_evidence"]["provider"] == "openai"
        assert ctx["_model_resolution_evidence"]["attempts"][-1]["status"] == "blocked"
    else:
        result = await call
        assert result["provider_usage"]["measurement_coverage"] == "partial"
        assert result["provider_usage"]["provider_calls"] == 2
        assert result["provider_usage"]["reported_total"] == 5
        assert "usage" not in result
    expected = [("openai", step) for step in ("policy", "build", "reservation", "dispatch")]
    expected += [("ollama", step) for step in (
        ("policy",) if refuse_at == "policy" else
        ("policy", "build", "reservation") if refuse_at == "reservation" else
        ("policy", "build", "reservation", "dispatch")
    )]
    assert events == expected


@pytest.mark.asyncio
async def test_client_configuration_failure_does_not_reserve_or_count_a_call(monkeypatch):
    def build(_):
        raise runtime.ModelExecutionError("connection not configured")

    def forbidden(*_):
        raise AssertionError("No reservation before successful client construction")

    monkeypatch.setattr(runtime, "build_model_client", build)
    ctx = {"_model_before_dispatch": forbidden}
    with pytest.raises(runtime.ModelExecutionError, match="not configured"):
        await runtime.complete_model(execution(), "x", ctx)
    assert ctx["_provider_usage_v1"]["calls"] == []


@pytest.mark.asyncio
async def test_workspace_private_options_use_original_context_and_accumulate_once(monkeypatch):
    from app.services.skills_registry import wrappers

    calls, reservations, deltas = [], [], []

    class Client:
        async def generate(self, **kwargs):
            calls.append(kwargs)
            assert kwargs["max_tokens"] == 10 and kwargs["response_format"]["type"] == "json_schema"
            return {"content": '{"label":"ok"}', "usage": {"total_tokens": 3}}

        async def stream(self, **kwargs):
            raise AssertionError("Batch calls must not stream")
            yield

    monkeypatch.setattr(runtime, "build_model_client", lambda _: Client())
    ctx = {
        "_model_execution": execution(), "_model_stream": False,
        "_model_generation_options": {"json_schema": SCHEMA, "max_tokens": 10},
        "_model_before_dispatch": lambda *args: reservations.append(len(ctx["_provider_usage_v1"]["calls"])),
        "token_sink": deltas.append,
    }
    payload = {"instruction": "Label", "prompt": "row", "_model_generation_options": {"max_tokens": 999}}
    first = await wrappers._workspace_llm_v1(payload, ctx)
    second = await wrappers._workspace_llm_v1(payload, ctx)
    assert calls[0]["prompt"] == "Label\n\nrow"
    assert reservations == [0, 1] and deltas == []
    assert first["usage"]["total_tokens"] == 3 and second["usage"]["total_tokens"] == 6
    assert len(ctx["_provider_usage_v1"]["calls"]) == 2
    assert ctx["_model_execution_evidence"]["dispatch_started"] is True
    assert "model_execution" not in second


@pytest.mark.asyncio
async def test_workspace_default_stream_and_payload_cannot_override_options(monkeypatch):
    from app.services.skills_registry import wrappers

    received, deltas = [], []

    class Client:
        async def stream(self, **kwargs):
            received.append(kwargs)
            yield {"delta": "ok"}
            yield {"usage": {"total_tokens": 1}}

    monkeypatch.setattr(runtime, "build_model_client", lambda _: Client())
    ctx = {"_model_execution": execution(), "token_sink": deltas.append}
    result = await wrappers._workspace_llm_v1({"prompt": "x", "_model_stream": False,
        "_model_generation_options": {"max_tokens": 99}}, ctx)
    assert result["streamed"] is True and deltas == ["ok"]
    assert received == [{"model": "configured-model", "prompt": "x"}]


@pytest.mark.parametrize("provider", ["openai", "azure_openai"])
@pytest.mark.parametrize("no_retries", [False, True])
def test_sdk_retry_setting_is_opt_in(monkeypatch, provider, no_retries):
    import openai

    constructed = []
    sdk = "AsyncAzureOpenAI" if provider == "azure_openai" else "AsyncOpenAI"
    monkeypatch.setattr(openai, sdk, lambda **kwargs: constructed.append(kwargs))
    runtime.build_model_client(execution(provider), no_retries=no_retries)._sdk_client()
    assert (constructed[0].get("max_retries") == 0) is no_retries
    if not no_retries:
        assert "max_retries" not in constructed[0]


@pytest.mark.asyncio
async def test_private_retry_control_reaches_sdk_but_never_provider_request(monkeypatch):
    import openai

    constructed, requests = [], []

    async def generate(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(model="configured-model", usage=SimpleNamespace(prompt_tokens=2, completion_tokens=1, total_tokens=3),
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

    def sdk(**kwargs):
        constructed.append(kwargs)
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=generate)))

    monkeypatch.setattr(openai, "AsyncOpenAI", sdk)
    ctx = {"_model_no_retries": True}
    await runtime.complete_model(execution(), "x", ctx, generation_options={"max_tokens": 4}, stream=False)
    assert constructed[0]["max_retries"] == 0
    assert "max_retries" not in requests[0] and "_model_no_retries" not in requests[0]
    assert len(ctx["_provider_usage_v1"]["calls"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("no_retries", [False, True])
async def test_anthropic_plain_generation_preserves_retry_default(monkeypatch, no_retries):
    import sys

    constructed = []

    async def generate(**kwargs):
        assert "max_retries" not in kwargs
        return SimpleNamespace(model="configured-model", content=[SimpleNamespace(text="ok")],
                               usage=SimpleNamespace(input_tokens=2, output_tokens=1))

    def sdk(**kwargs):
        constructed.append(kwargs)
        return SimpleNamespace(messages=SimpleNamespace(create=generate))

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(AsyncAnthropic=sdk))
    result = await runtime.complete_model(execution("anthropic"), "x", {"_model_no_retries": no_retries}, stream=False)
    assert (constructed[0].get("max_retries") == 0) is no_retries
    if not no_retries:
        assert "max_retries" not in constructed[0]
    assert result["usage"]["total_tokens"] == 3


@pytest.mark.asyncio
async def test_no_retries_means_one_real_sdk_transport_attempt(monkeypatch):
    import httpx
    import openai

    sdk = openai.AsyncOpenAI
    requests, clients = [], []

    def respond(request):
        requests.append(request)
        return httpx.Response(500, json={"error": {"message": "synthetic unavailable", "type": "server_error"}})

    def build(**kwargs):
        client = sdk(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
        clients.append(client)
        return client

    monkeypatch.setattr(openai, "AsyncOpenAI", build)
    ctx = {"_model_no_retries": True}
    try:
        with pytest.raises(runtime.ModelExecutionError, match="generation failed"):
            await runtime.complete_model(execution(), "x", ctx, stream=False)
    finally:
        for client in clients:
            await client.close()
    assert len(requests) == 1
    assert len(ctx["_provider_usage_v1"]["calls"]) == 1
    assert ctx["_provider_usage_v1"]["calls"][0]["reported"] is False
