"""The one place that decides provider/model — order, governance, zero drift."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services.model_plane import workspace_config
from app.services.model_plane.routing_policy import (
    LANE_TO_TIER,
    MODEL_TIERS,
    ModelChoice,
    RoutingSnapshot,
    model_allowed,
    normalise_tiers,
    parse_model_spec,
    resolve_model,
    routing_snapshot,
    tier_for_answer_profile,
    tier_for_lane,
)


def _workspace(**settings_blob):
    return SimpleNamespace(id="ws-1", slug="acme", settings=settings_blob)


@pytest.fixture(autouse=True)
def _global_defaults(monkeypatch):
    monkeypatch.setattr(settings, "default_provider", "openai")
    monkeypatch.setattr(settings, "default_model", "gpt-5")
    monkeypatch.setattr(settings, "model_tier_fast", "")
    monkeypatch.setattr(settings, "model_tier_balanced", "")
    monkeypatch.setattr(settings, "model_tier_strong", "")


# --- parsing -------------------------------------------------------------------


def test_parse_model_spec_matches_the_historical_wrapper_contract():
    assert parse_model_spec("gpt-4o-mini") == {"provider": "openai", "model": "gpt-4o-mini"}
    assert parse_model_spec("ollama:deepseek-r1:14b") == {"provider": "ollama", "model": "deepseek-r1:14b"}
    assert parse_model_spec("openai/gpt-4o") == {"provider": "openai", "model": "gpt-4o"}
    assert parse_model_spec("azure:gpt-4o-mini")["provider"] == "openai"
    assert parse_model_spec("serving_node_1:llama3")["provider"] == "serving_node_1"
    assert parse_model_spec("") == {"provider": "openai", "model": "gpt-5"}
    assert parse_model_spec("mistral", default_provider="ollama") == {"provider": "ollama", "model": "mistral"}


def test_normalise_tiers_rejects_unknown_tier_and_provider():
    assert normalise_tiers({"fast": "ollama:qwen3:8b", "strong": ""}) == {"fast": "ollama:qwen3:8b"}
    with pytest.raises(ValueError):
        normalise_tiers({"turbo": "gpt-4o"})
    with pytest.raises(ValueError):
        normalise_tiers({"fast": "nope:gpt-4o"})
    with pytest.raises(ValueError):
        normalise_tiers(["fast"])


def test_lane_and_profile_bridges():
    assert set(LANE_TO_TIER.values()) <= set(MODEL_TIERS)
    assert tier_for_lane("deep") == "strong"
    assert tier_for_lane("balanced", has_sub_queries=True) == "strong"
    assert tier_for_lane("fast") == "fast"
    assert tier_for_lane(None) == "balanced"
    assert tier_for_answer_profile("comparison") == "strong"
    assert tier_for_answer_profile("technical") == "balanced"


# --- zero drift ----------------------------------------------------------------


def test_no_workspace_routing_and_no_tiers_is_the_legacy_answer():
    """Empty config must answer exactly what the four old routers answered."""
    choice = resolve_model(workspace=_workspace(), tier_hint="strong")
    assert (choice.provider, choice.model) == ("openai", "gpt-5")
    assert choice.source == "global"
    assert choice.reason == ""
    # A run outside the engine (no snapshot, no workspace) is the same answer.
    assert resolve_model(tier_hint="fast").preferences() == {"provider": "openai", "model": "gpt-5"}


def test_system_pin_still_beats_the_tier_table():
    ws = _workspace(llm_portal={"routing": {"default_provider": "openai", "default_model": "gpt-5",
                                            "tiers": {"strong": "openai:gpt-5", "fast": "ollama:qwen3:8b"}}})
    choice = resolve_model(workspace=ws, system_default_model="gpt-4o-mini", tier_hint="fast")
    assert choice.source == "system"
    assert choice.model == "gpt-4o-mini"


def test_explicit_model_equal_to_the_pin_is_reported_as_the_pin():
    choice = resolve_model(workspace=_workspace(), explicit_model="gpt-4o-mini", system_default_model="gpt-4o-mini")
    assert choice.source == "system"


# --- resolution order ----------------------------------------------------------


def test_resolution_order_explicit_then_system_then_tier_then_workspace():
    ws = _workspace(
        llm_portal={
            "routing": {
                "default_provider": "openai",
                "default_model": "gpt-4.1",
                "fallback_chain": ["openai", "ollama"],
                "tiers": {"fast": "ollama:qwen3:8b", "strong": "openai:gpt-5"},
            }
        }
    )
    explicit = resolve_model(workspace=ws, explicit_model="anthropic:claude-3-7", system_default_model="gpt-4o", tier_hint="fast")
    assert (explicit.source, explicit.provider, explicit.model) == ("explicit", "anthropic", "claude-3-7")

    system = resolve_model(workspace=ws, system_default_model="gpt-4o", tier_hint="fast")
    assert (system.source, system.model) == ("system", "gpt-4o")

    tier = resolve_model(workspace=ws, tier_hint="fast")
    assert (tier.source, tier.provider, tier.model, tier.tier) == ("tier", "ollama", "qwen3:8b", "fast")

    unset_tier = resolve_model(workspace=ws, tier_hint="balanced")
    assert (unset_tier.source, unset_tier.model) == ("workspace", "gpt-4.1")

    # The workspace chain is honoured as configured; the router skips the
    # primary provider when it walks it.
    assert tier.fallback_chain == ("openai", "ollama")
    assert explicit.fallback_chain == ("anthropic", "openai", "ollama")


def test_lane_names_are_accepted_as_tier_hints():
    ws = _workspace(llm_portal={"routing": {"default_provider": "openai", "default_model": "gpt-4.1",
                                            "tiers": {"strong": "openai:gpt-5"}}})
    assert resolve_model(workspace=ws, tier_hint="deep").model == "gpt-5"
    assert resolve_model(workspace=ws, tier_hint="multihop").tier == "strong"


def test_global_settings_fill_the_tiers_a_workspace_left_empty(monkeypatch):
    monkeypatch.setattr(settings, "model_tier_fast", "ollama:qwen3:8b")
    ws = _workspace(llm_portal={"routing": {"default_provider": "openai", "default_model": "gpt-4.1",
                                            "tiers": {"strong": "openai:gpt-5"}}})
    snap = routing_snapshot(ws)
    assert snap.tiers == {"fast": "ollama:qwen3:8b", "strong": "openai:gpt-5"}
    assert resolve_model(snapshot=snap.to_dict(), tier_hint="fast").provider == "ollama"


# --- governance ----------------------------------------------------------------


def test_model_allowed_matches_bare_names_and_specs():
    prefs = {"provider": "openai", "model": "gpt-5"}
    assert model_allowed(prefs, [])
    assert model_allowed(prefs, ["gpt-5"])
    assert model_allowed(prefs, ["openai:gpt-5"])
    assert not model_allowed(prefs, ["ollama:gpt-5"])
    assert not model_allowed(prefs, ["gpt-4o"])


def test_disallowed_pin_downgrades_to_an_allowed_tier_and_says_so():
    ws = _workspace(llm_portal={"routing": {"default_provider": "openai", "default_model": "gpt-5",
                                            "tiers": {"balanced": "ollama:qwen3:8b", "strong": "openai:gpt-5"}}})
    choice = resolve_model(
        workspace=ws,
        system_default_model="gpt-4o-mini",
        tier_hint="strong",
        allowed_models=["ollama:qwen3:8b"],
    )
    assert (choice.provider, choice.model, choice.source, choice.tier) == ("ollama", "qwen3:8b", "tier", "balanced")
    assert choice.reason.startswith("model_not_allowed_downgraded:openai:gpt-4o-mini")
    assert choice.requested == "openai:gpt-4o-mini"


def test_nothing_allowed_in_the_table_falls_back_to_the_allow_list_itself():
    choice = resolve_model(workspace=_workspace(), system_default_model="gpt-4o-mini", allowed_models=["anthropic:claude-3-5"])
    assert (choice.provider, choice.model, choice.source) == ("anthropic", "claude-3-5", "allowed_models")


def test_snapshot_round_trips_and_carries_allowed_models():
    ws = _workspace(llm_portal={"routing": {"default_provider": "openai", "default_model": "gpt-5", "tiers": {"fast": "ollama:qwen3:8b"}}})
    snap = routing_snapshot(ws, allowed_models=["ollama:qwen3:8b", "gpt-5"])
    again = RoutingSnapshot.from_mapping(snap.to_dict())
    assert again == snap
    choice = resolve_model(snapshot=snap.to_dict(), system_default_model="gpt-4o", tier_hint="fast")
    assert choice.model == "qwen3:8b" and choice.reason.startswith("model_not_allowed_downgraded")
    assert isinstance(choice, ModelChoice) and choice.to_dict()["spec"] == "ollama:qwen3:8b"


# --- ModelRouter.resolve ---------------------------------------------------------


class _FakeOllama:
    """Stands in for OllamaClient in the router (isinstance-compatible)."""

    def __init__(self, hosted):
        self.hosted = set(hosted)

    async def health_check(self):
        return True

    async def is_model_available(self, model_name):
        return model_name in self.hosted


class _DeadCloud:
    async def health_check(self):
        return False


@pytest.mark.asyncio
async def test_router_fallback_to_ollama_serves_the_local_default_model(monkeypatch):
    from app.services import model_router as mr

    monkeypatch.setattr(settings, "ollama_default_model", "qwen3:8b")
    monkeypatch.setattr(mr, "OllamaClient", _FakeOllama)
    router = mr.ModelRouter.__new__(mr.ModelRouter)
    router.logger = mr.logger
    router.clients = {"openai": _DeadCloud(), "ollama": _FakeOllama({"qwen3:8b"})}
    router.fallback_chain = ["ollama"]

    resolved = await router.resolve({"provider": "openai", "model": "gpt-5"}, fallback_chain=["openai", "ollama"])
    assert (resolved.provider, resolved.model, resolved.fallback) == ("ollama", "qwen3:8b", True)
    assert await router.get_client({"provider": "openai", "model": "gpt-5"}) is router.clients["ollama"]


@pytest.mark.asyncio
async def test_router_workspace_chain_can_exclude_a_provider(monkeypatch):
    from app.services import model_router as mr

    monkeypatch.setattr(mr, "OllamaClient", _FakeOllama)
    router = mr.ModelRouter.__new__(mr.ModelRouter)
    router.logger = mr.logger
    router.clients = {"openai": _DeadCloud(), "ollama": _FakeOllama({"qwen3:8b"})}
    router.fallback_chain = ["ollama"]
    with pytest.raises(RuntimeError):
        await router.resolve({"provider": "openai", "model": "gpt-5"}, fallback_chain=["openai"])


# --- persistence ---------------------------------------------------------------


class _FakeDb:
    def add(self, *_):
        pass

    def commit(self):
        pass

    def refresh(self, *_):
        pass


def test_set_routing_keeps_stored_tiers_unless_a_table_is_given():
    ws = _workspace(llm_portal={"routing": {"default_provider": "openai", "default_model": "gpt-5", "tiers": {"fast": "ollama:qwen3:8b"}}})
    workspace_config.set_routing(_FakeDb(), ws, default_provider="openai", default_model="gpt-4.1")
    assert ws.settings["llm_portal"]["routing"]["tiers"] == {"fast": "ollama:qwen3:8b"}
    workspace_config.set_routing(_FakeDb(), ws, default_provider="openai", default_model="gpt-4.1", tiers={"strong": "openai:gpt-5", "fast": ""})
    assert ws.settings["llm_portal"]["routing"]["tiers"] == {"strong": "openai:gpt-5"}
    with pytest.raises(ValueError):
        workspace_config.set_routing(_FakeDb(), ws, default_provider="openai", default_model="gpt-4.1", tiers={"x": "y"})
    assert workspace_config.get_routing(ws)["tiers"] == {"strong": "openai:gpt-5"}
