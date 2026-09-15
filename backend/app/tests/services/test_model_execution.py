"""Hermetic resolution, credential isolation, routing and dispatch contracts."""
from types import SimpleNamespace

import pytest

from app.services.membrane.enforcement import MembraneEnforcementError
from app.services.model_plane import execution as runtime


@pytest.fixture(autouse=True)
def synthetic_connections(monkeypatch):
    for key in (
        "OPENAI_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_DEPLOYMENT",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-global-key")
    for name, value in {
        "default_provider": "openai",
        "default_model": "gpt-global",
        "ollama_default_model": "qwen3:8b",
        "ollama_base_url": "http://synthetic-ollama:11434",
    }.items():
        monkeypatch.setattr(runtime.settings, name, value)


def workspace(provider="openai", model="gpt-workspace"):
    return SimpleNamespace(
        id="isolated-workspace",
        settings={
            "llm_portal": {
                "routing": {
                    "default_provider": provider,
                    "default_model": model,
                    "fallback_chain": [provider, "ollama"],
                }
            }
        },
    )


def binding(provider="openai", model=None):
    return {
        "kind": "prompt_template",
        "params": {
            "provider": provider,
            "template": "Hello {name}",
            **({"model": model} if model else {}),
        },
    }


@pytest.mark.parametrize(
    "payload,pinned,system,expected,source",
    [
        ({"model": "gpt-input"}, "gpt-pinned", "gpt-system", "gpt-input", "input"),
        ({}, "gpt-pinned", "gpt-system", "gpt-pinned", "executor"),
        ({}, None, "gpt-system", "gpt-system", "system"),
        ({}, None, None, "gpt-workspace", "workspace"),
        ({"model": {"model_id": "scoring-result"}}, "gpt-pinned", None, "gpt-pinned", "executor"),
    ],
)
def test_priority_does_not_mutate_closed_input(payload, pinned, system, expected, source):
    original = dict(payload)
    resolved = runtime.resolve_skill_model_execution(
        workspace(), executor=binding(model=pinned), input_ref=payload, system_default_model=system
    )
    assert (resolved.provider, resolved.model, resolved.model_source) == (
        "openai",
        expected,
        source,
    )
    assert payload == original


def test_workspace_credentials_are_isolated_and_never_serialized(monkeypatch):
    monkeypatch.setattr(
        runtime.workspace_config,
        "get_cloud_credentials_public",
        lambda ws: [{"key": "openai", "api_key_set": ws.id == "isolated-workspace"}],
    )
    monkeypatch.setattr(
        runtime.workspace_config,
        "get_decrypted_api_key",
        lambda ws, provider: "synthetic-workspace-key",
    )
    first = runtime.resolve_model_execution(workspace(), provider="openai")
    other = workspace()
    other.id = "other-workspace"
    second = runtime.resolve_model_execution(other, provider="openai")
    assert first._api_key == "synthetic-workspace-key" and first.credential_source == "workspace"
    assert second._api_key == "synthetic-global-key" and second.credential_source == "env"
    assert "synthetic-" not in str(first.public()) + repr(first)


def test_unreadable_workspace_key_never_falls_back_to_env(monkeypatch):
    monkeypatch.setattr(
        runtime.workspace_config,
        "get_cloud_credentials_public",
        lambda ws: [{"key": "openai", "api_key_set": True}],
    )
    monkeypatch.setattr(runtime.workspace_config, "get_decrypted_api_key", lambda *args: None)
    with pytest.raises(runtime.ModelExecutionError, match="reconnect"):
        runtime.resolve_model_execution(workspace(), provider="openai")


def test_published_azure_keeps_historical_openai_connection(monkeypatch):
    monkeypatch.setattr(
        runtime.workspace_config,
        "get_decrypted_api_key",
        lambda *args: (_ for _ in ()).throw(AssertionError("legacy does not read workspace key")),
    )
    resolved = runtime.resolve_skill_model_execution(
        workspace("azure_openai", "deployment-a"),
        executor=binding("azure"),
        input_ref={},
        system_default_model="different-system-model",
        published=True,
    )
    assert (resolved.provider, resolved.model, resolved.legacy_provider, resolved.model_source) == (
        "openai",
        "gpt-4o-mini",
        "azure",
        "legacy_default",
    )
    assert resolved._api_key == "synthetic-global-key"


def test_published_ollama_retains_default_and_endpoint():
    old = runtime.resolve_skill_model_execution(
        workspace(),
        executor=binding("ollama"),
        input_ref={},
        system_default_model="gpt-system",
        published=True,
    )
    assert (old.model, old._endpoint, old.model_source) == (
        "deepseek-r1:14b",
        "http://localhost:11434",
        "published_legacy_default",
    )
    new = runtime.resolve_skill_model_execution(
        workspace(), executor=binding("ollama", "qwen3:8b"), input_ref={}, published=True
    )
    assert new.model == "qwen3:8b" and new._endpoint == "http://synthetic-ollama:11434"


def test_azure_openai_uses_azure_sdk_endpoint_and_deployment(monkeypatch):
    import openai

    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "synthetic-azure-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://synthetic.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "deployment-a")
    captured = {}
    monkeypatch.setattr(openai, "AsyncAzureOpenAI", lambda **kwargs: captured.update(kwargs))
    resolved = runtime.resolve_model_execution(workspace(), provider="azure_openai")
    runtime.build_model_client(resolved)._sdk_client()
    assert resolved.model == "deployment-a"
    assert captured == {
        "api_key": "synthetic-azure-key",
        "azure_endpoint": "https://synthetic.openai.azure.com",
        "api_version": "2024-02-01",
    }
    assert "synthetic-azure-key" not in str(resolved.public())


@pytest.mark.parametrize(
    "provider,model",
    [("openai", "ollama:qwen3:8b"), ("openai", "text-embedding-3-small"), ("gemini", "gemini-pro")],
)
def test_invalid_text_provider_or_model_fails_closed(provider, model):
    with pytest.raises(runtime.ModelExecutionError):
        runtime.resolve_model_execution(workspace(), provider=provider, model=model)


def test_provider_qualified_policies_do_not_allow_other_provider_same_model():
    resolved = runtime.resolve_model_execution(
        workspace(), provider="azure_openai", model="gpt-4o-mini"
    )
    assert resolved.policy_model(["openai:gpt-4o-mini"]) == "azure_openai:gpt-4o-mini"
    assert resolved.policy_model(["gpt-4o-mini"]) == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_explicit_provider_never_falls_back(monkeypatch):
    calls = []

    class Client:
        async def generate(self, **kwargs):
            calls.append(kwargs)
            raise RuntimeError("untrusted provider error content")

    monkeypatch.setattr(runtime, "build_model_client", lambda candidate: Client())
    ctx = {}
    with pytest.raises(
        runtime.ModelExecutionError, match=r"openai: generation failed \(RuntimeError\)"
    ):
        await runtime.complete_model(
            runtime.resolve_model_execution(workspace(), provider="openai"), "private prompt", ctx
        )
    assert len(calls) == 1 and len(ctx["_model_execution_evidence"]["attempts"]) == 1
    assert "untrusted" not in str(ctx["_model_execution_evidence"])


@pytest.mark.asyncio
async def test_workspace_fallback_uses_own_model_policy_and_partial_usage(monkeypatch):
    checked, calls = [], []

    class Client:
        def __init__(self, candidate):
            self.candidate = candidate

        async def generate(self, **kwargs):
            calls.append((self.candidate.provider, kwargs["model"]))
            if self.candidate.provider == "openai":
                raise TimeoutError()
            return {"response": "ok", "model": "qwen3:8b", "prompt_eval_count": 2, "eval_count": 3}

    monkeypatch.setattr(runtime, "build_model_client", Client)
    ctx = {
        "_model_policy_check": lambda candidate: checked.append(
            (candidate.provider, candidate.model)
        )
    }
    result = await runtime.complete_model(
        runtime.resolve_model_execution(workspace(), provider="workspace"), "x", ctx
    )
    assert calls == checked == [("openai", "gpt-workspace"), ("ollama", "qwen3:8b")]
    assert result["model_execution"]["fallback"] is True
    assert [row["status"] for row in result["model_execution"]["attempts"]] == [
        "failed",
        "completed",
    ]
    assert "usage" not in result
    assert (
        result["provider_usage"]["measurement_coverage"] == "partial"
        and result["provider_usage"]["reported_total"] == 5
    )


@pytest.mark.asyncio
async def test_denied_fallback_never_opens_connection(monkeypatch):
    calls = []

    class Client:
        async def generate(self, **kwargs):
            raise TimeoutError()

    monkeypatch.setattr(
        runtime,
        "build_model_client",
        lambda candidate: calls.append(candidate.provider) or Client(),
    )

    def check(candidate):
        if candidate.provider != "openai":
            raise MembraneEnforcementError("not allowed")

    ctx = {"_model_policy_check": check}
    with pytest.raises(MembraneEnforcementError):
        await runtime.complete_model(
            runtime.resolve_model_execution(workspace(), provider="workspace"), "x", ctx
        )
    assert (
        calls == ["openai"]
        and ctx["_model_execution_evidence"]["attempts"][-1]["status"] == "blocked"
    )


@pytest.mark.asyncio
async def test_stream_keeps_provenance_and_never_reissues_after_first_token(monkeypatch):
    calls, tokens = [], []

    class Client:
        async def stream(self, **kwargs):
            calls.append(kwargs["model"])
            yield {"delta": "first"}
            raise TimeoutError()

    monkeypatch.setattr(runtime, "build_model_client", lambda candidate: Client())
    ctx = {"token_sink": tokens.append}
    with pytest.raises(runtime.ModelExecutionError):
        await runtime.complete_model(
            runtime.resolve_model_execution(workspace(), provider="workspace"), "x", ctx
        )
    assert tokens == ["first"] and calls == ["gpt-workspace"]
    assert len(ctx["_model_execution_evidence"]["attempts"]) == 1


@pytest.mark.asyncio
async def test_stream_and_generate_share_resolution_and_measured_usage(monkeypatch):
    class Client:
        async def stream(self, **kwargs):
            assert kwargs["model"] == "gpt-pinned"
            yield {"delta": "hello", "model": "gpt-pinned-revision"}
            yield {"usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}}

    monkeypatch.setattr(runtime, "build_model_client", lambda candidate: Client())
    result = await runtime.complete_model(
        runtime.resolve_model_execution(workspace(), provider="openai", model="gpt-pinned"),
        "x",
        {"token_sink": lambda token: None},
    )
    assert (
        result["completion"] == "hello"
        and result["model_execution"]["returned_model"] == "gpt-pinned-revision"
    )
    assert result["usage"]["total_tokens"] == 3


def test_seeded_ollama_keeps_legacy_default_when_system_default_changes():
    resolved = runtime.resolve_skill_model_execution(
        workspace(),
        executor=None,
        input_ref={},
        system_default_model="gpt-changed",
        slug="ollama_llm_v1",
        published=True,
    )
    assert (resolved.provider, resolved.model, resolved.model_source) == (
        "ollama",
        "deepseek-r1:14b",
        "legacy_default",
    )


@pytest.mark.asyncio
async def test_router_returns_exact_workspace_connection_without_cross_provider_probe(monkeypatch):
    from app.services.model_router import ModelRouter

    monkeypatch.setattr(ModelRouter, "_initialize_clients", lambda self: None)
    seen = []
    monkeypatch.setattr(
        runtime, "build_model_client", lambda resolved: seen.append(resolved) or SimpleNamespace()
    )
    client = await ModelRouter(workspace()).get_client(
        {"provider": "openai", "model": "gpt-pinned"}
    )
    assert len(seen) == 1
    assert client.model_execution.model == "gpt-pinned"
    assert client.model_execution._fallbacks == ()


@pytest.mark.asyncio
async def test_generic_wrapper_uses_server_workspace_and_model_policy(monkeypatch):
    from app.services.skills_registry import wrappers

    checks = []

    class Client:
        async def generate(self, **kwargs):
            assert kwargs["model"] == "gpt-workspace"
            return {"content": "ok", "usage": {"total_tokens": 2}}

    monkeypatch.setattr(runtime, "build_model_client", lambda resolved: Client())
    ctx = {
        "_model_workspace": workspace(),
        "_model_policy_check": lambda resolved: checks.append(resolved.public()),
    }
    assert await wrappers._route_llm_complete("x", None, ctx) == "ok"
    assert checks[0]["model_source"] == "workspace"
    assert ctx["_model_execution_evidence"]["requested_provider"] == "workspace"


@pytest.mark.asyncio
async def test_legacy_azure_stream_preserves_closed_output_with_counters_in_context(monkeypatch):
    from app.services.skills_registry import wrappers

    class Client:
        async def stream(self, **kwargs):
            yield {"delta": "ok", "model": "gpt-returned"}
            yield {"usage": {"total_tokens": 2}}

    monkeypatch.setattr(runtime, "build_model_client", lambda resolved: Client())
    ctx = {"token_sink": lambda token: None}
    result = await wrappers._azure_llm_v1({"prompt": "x"}, ctx)
    assert result == {"completion": "ok", "model": "gpt-4o-mini", "streamed": True}
    assert ctx["_provider_usage_v1"]["calls"][0]["usage"]["total_tokens"] == 2
    assert ctx["_model_execution_evidence"]["returned_model"] == "gpt-returned"


@pytest.mark.asyncio
async def test_workspace_wrapper_never_uses_global_serving_registry(monkeypatch):
    from app.services.model_router import ModelRouter
    from app.services.skills_registry import wrappers

    def forbidden(*args, **kwargs):
        raise AssertionError("A global connection must never be constructed")

    monkeypatch.setattr(ModelRouter, "__init__", forbidden)
    monkeypatch.setattr(runtime, "build_model_client", forbidden)
    ctx = {"_model_workspace": workspace()}
    with pytest.raises(runtime.ModelExecutionError, match="workspace-scoped"):
        await wrappers._route_llm_complete("x", "serving_other_workspace:private-model", ctx)


@pytest.mark.asyncio
async def test_workspace_router_refuses_even_a_registered_global_serving_client(monkeypatch):
    from app.services.model_router import ModelRouter

    monkeypatch.setattr(ModelRouter, "_initialize_clients", lambda self: None)
    router = ModelRouter(workspace())
    router.clients["serving_other_workspace"] = SimpleNamespace()
    with pytest.raises(RuntimeError, match="workspace-scoped"):
        await router.get_client({"provider": "serving_other_workspace", "model": "private-model"})
