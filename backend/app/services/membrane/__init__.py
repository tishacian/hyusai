"""Membrane — declarative process-membrane contract (Sympozium pattern, P3).

The membrane materialises the per-System process contract as a typed
:class:`~app.services.membrane.spec.MembraneSpec` stored canonically in
``ControlPolicy.extra["membrane_spec"]``. A *read-through* resolver derives the
spec from the existing ``source_policy`` / ``ControlPolicy`` fields when no
explicit spec is present, so workspaces that never opted in are byte-for-byte
unchanged.

Five enforcement facets — ``inbound`` / ``outbound`` / ``capabilities`` /
``provenance`` / ``valves`` — are consulted by in-app hooks. Every hook is
additive and fail-soft: a *derived* (non-authoritative) spec never changes
behaviour, and even an *authoritative* spec only tightens things it explicitly
opts into.
"""
from .enforcement import (  # noqa: F401
    CapabilityDecision,
    EgressDecision,
    EgressDisposition,
    InboundDecision,
    MembraneEnforcementError,
    ProvenanceArtifact,
    ValveDecision,
    ValveUsage,
    collect_valve_usage,
    decide_egress,
    enforce_inbound_collections,
    enforce_inbound_sources,
    evaluate_capability,
    evaluate_valves,
    persist_provenance_artifact,
    token_count_from_payload,
)
from .spec import (  # noqa: F401
    CapabilityFacet,
    EnforcementMode,
    FacetState,
    InboundFacet,
    MembraneSpec,
    OutboundFacet,
    ProvenanceFacet,
    ValvesFacet,
    resolve_membrane_spec,
)

__all__ = [
    "CapabilityFacet",
    "EnforcementMode",
    "FacetState",
    "InboundFacet",
    "MembraneSpec",
    "OutboundFacet",
    "ProvenanceFacet",
    "ValvesFacet",
    "resolve_membrane_spec",
    "CapabilityDecision",
    "EgressDecision",
    "EgressDisposition",
    "InboundDecision",
    "MembraneEnforcementError",
    "ProvenanceArtifact",
    "ValveDecision",
    "ValveUsage",
    "decide_egress",
    "collect_valve_usage",
    "enforce_inbound_collections",
    "enforce_inbound_sources",
    "evaluate_capability",
    "evaluate_valves",
    "persist_provenance_artifact",
    "token_count_from_payload",
]
