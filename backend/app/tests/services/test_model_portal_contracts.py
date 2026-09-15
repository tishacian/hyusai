"""Catalogue isolation, compatible routing and truthful ledger projection."""
import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.run import SkillInvocation
from app.services.model_plane import distribution, providers, workspace_config


@pytest.mark.asyncio
async def test_probe_cache_isolates_concurrent_workspaces(monkeypatch):
    providers.clear_health_cache()
    calls = []

    async def probe(**kwargs):
        key = kwargs["headers"]["Authorization"]
        calls.append(key)
        await asyncio.sleep(0)
        return {"status": "active", "models": ["gpt-" + key[-1]], "latency_ms": 1, "error": None}

    def catalog(*, workspace=None, **kwargs):
        return [{"key": "openai", "label": "OpenAI", "kind": "cloud", "configured": True,
                 "fallback_models": [], "notes": None, "api_key_set": True, "credential_source": "workspace",
                 "health": lambda: providers._health_openai(api_key="fake-key-" + workspace.id)}]

    monkeypatch.setattr(providers, "_probe", probe)
    monkeypatch.setattr(providers, "_base_catalog", catalog)
    monkeypatch.setattr(providers, "_workspace_keys", lambda _: {})
    a, b = SimpleNamespace(id="A", settings={}), SimpleNamespace(id="B", settings={})
    first, second = await asyncio.gather(
        providers.list_providers(workspace=a, include_local_serving=False),
        providers.list_providers(workspace=b, include_local_serving=False),
    )
    assert first[0]["models"] == ["gpt-A"]
    assert second[0]["models"] == ["gpt-B"]
    await providers.list_providers(workspace=a, include_local_serving=False)
    assert len(calls) == 2
    providers.clear_health_cache(workspace=a)
    await providers.list_providers(workspace=b, include_local_serving=False)
    assert len(calls) == 2
    await providers.list_providers(workspace=a, include_local_serving=False)
    assert len(calls) == 3
    assert providers._cache_workspace.get() == "global"


@pytest.mark.asyncio
async def test_cloud_models_share_provider_catalogue_without_fake_generation_proof(monkeypatch):
    workspace = SimpleNamespace(id="ws")

    async def catalog(**kwargs):
        assert kwargs["workspace"] is workspace
        return [{"key": "openai", "status": "active", "configured": True,
                 "models_source": "provider_catalog", "runtime_available": True,
                 "credential_source": "workspace", "models": ["gpt-5", "text-embedding-3-large", "unfamiliar"]}]

    monkeypatch.setattr(providers, "list_providers", catalog)
    models = await providers.list_models(workspace=workspace)
    assert [row["compatibility"] for row in models] == ["text_generation", "other", "unknown"]
    assert all(row["discovered"] and row["generation_verified"] is False for row in models)
    assert models[0]["id"] == "openai:gpt-5"


@pytest.mark.parametrize("provider,model,fallbacks", [
    ("made-up", "gpt-5", []), ("openai", "text-embedding-3-small", []),
    ("openai", "anthropic:claude-3", []), ("openai", "gpt-5", ["made-up"]),
])
def test_bad_routing_never_persists_partial_configuration(provider, model, fallbacks):
    workspace = SimpleNamespace(settings={})
    with pytest.raises(ValueError):
        workspace_config.set_routing(None, workspace, default_provider=provider,
                                     default_model=model, fallback_chain=fallbacks)
    assert workspace.settings == {}


def test_distribution_distinguishes_unknown_zero_and_mixed_currencies():
    def invocation(cost, measured, currency="USD", method="catalog_unit_price"):
        return SkillInvocation(id=str(uuid4()), run_id="run-1", cost=cost, cost_measured=measured,
                               metrics={"cost_evidence": {"currency": currency, "method": method,
                               "state": "calculated" if method == "catalog_unit_price" else "measured"}})

    assert distribution._summary([invocation(0, False)])["cost"] is None
    zero = distribution._summary([invocation(0, True)])
    assert zero["cost"] == 0 and zero["cost_state"] == "calculated"
    assert zero["cost_source"] == "skill_catalog"
    mixed = distribution._summary([invocation(1, True), invocation(2, True, "EUR")])
    assert mixed["cost"] is None and mixed["cost_state"] == "mixed_currencies"
    assert mixed["costs_by_currency"] == {"USD": 1, "EUR": 2}
    partial = distribution._summary([invocation(.001, True, method="provider_measurement"), invocation(0, None)])
    assert partial["cost"] == .001 and partial["cost_state"] == "partial"
    assert partial["unknown_costs"] == 1
    assert partial["evidence"][0]["run_id"] == "run-1"
    tiny = distribution._summary([invocation(0.00000001, True, method="provider_measurement")])
    assert tiny["cost"] == 0.00000001
    assert tiny["costs_by_currency"]["USD"] == 0.00000001


def test_distribution_prefers_execution_proof_over_model_name_inference():
    invocation = SkillInvocation(trace={"effective_model": "gpt-5", "model_execution": {
        "provider": "azure_openai", "model": "deployment", "returned_model": "gpt-5-2026"}},
        output_ref={"model": "different"})
    assert distribution._model_identity(invocation) == ("azure_openai", "gpt-5-2026", "runtime_evidence")
    assert distribution._model_identity(SkillInvocation(trace={}, output_ref={"rows": 4})) is None


def test_skill_output_cannot_fabricate_server_model_provenance():
    invocation = SkillInvocation(trace={}, output_ref={"model_execution": {
        "provider": "azure_openai", "model": "invented"}})
    assert distribution._model_identity(invocation) is None
    invocation.output_ref = {"model": "gpt-5", "model_execution": {"provider": "azure_openai", "model": "invented"}}
    assert distribution._model_identity(invocation) == ("openai", "gpt-5", "legacy_inferred")


def test_resolving_a_model_without_dispatch_is_not_model_usage():
    invocation = SkillInvocation(trace={"model_resolution": {
        "provider": "openai", "model": "gpt-5"}}, output_ref={}, status="failed")
    assert distribution._model_identity(invocation) is None


@pytest.mark.asyncio
async def test_unreadable_workspace_key_never_probes_environment_fallback(monkeypatch):
    workspace = SimpleNamespace(id="broken", settings={"llm_portal": {"cloud_credentials": {"openai": {"api_key_encrypted": "unreadable"}}}})
    monkeypatch.setattr(providers, "_workspace_keys", lambda _: {})
    async def forbidden():
        pytest.fail("a stored unreadable workspace key must not fall back to the environment")
    monkeypatch.setattr(providers, "_base_catalog", lambda **_: [{
        "key": "openai", "label": "OpenAI", "kind": "cloud", "configured": True,
        "health": forbidden, "fallback_models": [], "notes": None,
        "credential_source": "env", "api_key_set": True,
    }])
    result = await providers.list_providers(workspace=workspace, include_local_serving=False)
    assert result[0]["status"] == "unreachable" and result[0]["credential_source"] == "workspace"
    assert result[0]["api_key_set"] is True
    assert "cannot be read" in result[0]["error"]


def test_explicit_empty_fallback_does_not_restore_ollama():
    workspace = SimpleNamespace(settings={"llm_portal": {"routing": {
        "default_provider": "openai", "default_model": "gpt-5", "fallback_chain": []}}})
    assert workspace_config.get_routing(workspace)["fallback_chain"] == []


@pytest.mark.asyncio
async def test_workspace_local_catalogues_ignore_polluted_global_registry(monkeypatch):
    monkeypatch.setattr(providers, "_base_catalog", lambda **_: [])
    monkeypatch.setattr(providers, "_workspace_keys", lambda _: {})
    monkeypatch.setattr(providers, "list_routable_providers", lambda: [{"key": "foreign", "models": ["private-model"]}])
    def nodes(label):
        return [{"name": "same-host-name", "status": "active", "instances": [
            {"id": label, "name": label, "provider": "vllm", "status": "running", "model": label + "-model"}]}]
    a = await providers.list_providers(workspace=SimpleNamespace(id="A", settings={}), node_snapshots=nodes("A"))
    b = await providers.list_providers(workspace=SimpleNamespace(id="B", settings={}), node_snapshots=nodes("B"))
    assert a[0]["models"] == ["A-model"]
    assert b[0]["models"] == ["B-model"]
    assert a[0]["runtime_available"] is False and b[0]["runtime_available"] is False
    assert "private-model" not in str(a) + str(b)
