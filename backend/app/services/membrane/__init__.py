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
from .spec import (  # noqa: F401
    CapabilityFacet,
    InboundFacet,
    MembraneSpec,
    OutboundFacet,
    ProvenanceFacet,
    ValvesFacet,
    resolve_membrane_spec,
)

__all__ = [
    "CapabilityFacet",
    "InboundFacet",
    "MembraneSpec",
    "OutboundFacet",
    "ProvenanceFacet",
    "ValvesFacet",
    "resolve_membrane_spec",
]
