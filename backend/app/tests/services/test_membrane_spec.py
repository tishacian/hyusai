"""P3 tests — MembraneSpec parsing + read-through resolver equivalence.

The central guarantee: a workspace with NO explicit ``membrane_spec`` resolves
to a *derived* (non-authoritative) spec whose facets mirror its existing
``source_policy`` / ``ControlPolicy`` exactly — so every membrane-aware hook
sees the same values it would have read directly (non-Andritz unchanged).
"""
from __future__ import annotations

from types import SimpleNamespace

from app.services.membrane.spec import MembraneSpec, resolve_membrane_spec


def _control(**kw) -> SimpleNamespace:
    base = dict(
        extra={},
        allowed_skills=[],
        allowed_models=[],
        max_cost_per_decision=None,
        max_latency_ms=None,
        mandatory_hitl_if_confidence_below=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Read-through derivation (non-authoritative)
# ---------------------------------------------------------------------------
def test_derive_is_non_authoritative() -> None:
    spec = resolve_membrane_spec(control=None, source_policy={})
    assert spec.authoritative is False


def test_derive_mirrors_source_policy_inbound() -> None:
    sp = {
        "reject_cross_project_sources": True,
        "preserve_reference_types": True,
        "expert_fiche_correction_enabled": True,
        "industrial_grounding": True,
    }
    spec = resolve_membrane_spec(control=None, source_policy=sp)
    assert spec.inbound.reject_cross_project_sources is True
    assert spec.inbound.preserve_reference_types is True
    assert spec.inbound.expert_fiche_correction_enabled is True
    assert spec.inbound.industrial_grounding is True
    # Nothing the existing retrieval path doesn't already read.
    assert spec.inbound.collection_allowlist == []


def test_derive_expert_review_default_true() -> None:
    # No key → matches knowledge_capture's default-True review gate.
    assert resolve_membrane_spec(source_policy={}).outbound.expert_review_required is True
    # Explicit opt-out is honoured (Andritz turns review OFF).
    spec = resolve_membrane_spec(source_policy={"expert_review_required": False})
    assert spec.outbound.expert_review_required is False


def test_derive_provenance_require_citations() -> None:
    assert resolve_membrane_spec(source_policy={"require_citations": True}).provenance.require_citations is True
    assert resolve_membrane_spec(source_policy={}).provenance.require_citations is False


def test_derive_capabilities_and_valves_mirror_control() -> None:
    control = _control(
        allowed_skills=["a_v1", "b_v1"],
        allowed_models=["gpt"],
        max_cost_per_decision=1.5,
        max_latency_ms=9000.0,
        mandatory_hitl_if_confidence_below=0.4,
    )
    spec = resolve_membrane_spec(control=control, source_policy={})
    assert spec.capabilities.allowed_skills == ["a_v1", "b_v1"]
    assert spec.capabilities.allowed_models == ["gpt"]
    assert spec.valves.max_cost_per_decision == 1.5
    assert spec.valves.max_latency_ms == 9000.0
    assert spec.valves.mandatory_hitl_if_confidence_below == 0.4
    # Derived valves never opt into hard-abort.
    assert spec.valves.hard_abort is False
    assert spec.authoritative is False


# ---------------------------------------------------------------------------
# Authoritative parsing
# ---------------------------------------------------------------------------
def test_authoritative_from_control_extra() -> None:
    control = _control(
        extra={
            "membrane_spec": {
                "capabilities": {"allowed_skills": ["only_this_v1"]},
                "valves": {"hard_abort": True, "max_cost_per_decision": 2.0},
                "inbound": {"collection_allowlist": ["andritz_docs"]},
            }
        },
        allowed_skills=["ignored_when_authoritative"],
    )
    spec = resolve_membrane_spec(control=control, source_policy={})
    assert spec.authoritative is True
    # Authoritative capabilities override the legacy allowed_skills column.
    assert spec.capabilities.allowed_skills == ["only_this_v1"]
    assert spec.valves.hard_abort is True
    assert spec.valves.max_cost_per_decision == 2.0
    assert spec.inbound.collection_allowlist == ["andritz_docs"]


def test_authoritative_from_source_policy_surface() -> None:
    sp = {"membrane_spec": {"inbound": {"collection_allowlist": ["c1"]}}}
    spec = resolve_membrane_spec(control=None, source_policy=sp)
    assert spec.authoritative is True
    assert spec.inbound.collection_allowlist == ["c1"]


def test_from_dict_to_dict_round_trip_is_stable() -> None:
    raw = {
        "version": 1,
        "inbound": {"collection_allowlist": ["c1"], "reject_cross_project_sources": True},
        "outbound": {"expert_review_required": False, "gate_if_confidence_below": 0.5},
        "capabilities": {"allowed_skills": ["x_v1"], "allowed_models": ["m"]},
        "provenance": {"require_citations": True, "object_store_prefix": "membrane/andritz/"},
        "valves": {"hard_abort": True, "token_budget": 1000, "circuit_breaker": {"failures": 3}},
    }
    once = MembraneSpec.from_dict(raw).to_dict()
    twice = MembraneSpec.from_dict(once).to_dict()
    assert once == twice
    assert once["valves"]["token_budget"] == 1000
    assert once["valves"]["circuit_breaker"] == {"failures": 3}
    assert once["provenance"]["object_store_prefix"] == "membrane/andritz/"


def test_malformed_facets_degrade_to_defaults() -> None:
    # Garbage values must not raise — facets fall back to safe defaults.
    spec = MembraneSpec.from_dict(
        {
            "inbound": {"collection_allowlist": "not-a-list"},
            "valves": {"max_cost_per_decision": "nan-ish"},
            "outbound": "totally-wrong-type",
        }
    )
    assert spec.inbound.collection_allowlist == []
    assert spec.valves.max_cost_per_decision is None
    assert spec.outbound.expert_review_required is True
