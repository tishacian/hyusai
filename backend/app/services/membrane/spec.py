"""Typed MembraneSpec + read-through resolver (P3).

``MembraneSpec`` is the authoritative process-membrane contract. It is stored
as canonical JSON in ``ControlPolicy.extra["membrane_spec"]`` and parsed back
via :meth:`MembraneSpec.from_dict`. When no explicit spec exists,
:func:`resolve_membrane_spec` *derives* one from the existing ``source_policy``
and ``ControlPolicy`` fields (``authoritative=False``) — the read-through path
that keeps non-opted-in workspaces unchanged.

The dataclasses are deliberately permissive: unknown keys are ignored on parse
and the facets default to "do nothing", so a partial spec is always valid and a
missing facet never enables enforcement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_str_list(value: Any) -> List[str]:
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if v is not None]
    return []


def _as_opt_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_opt_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Facets
# ---------------------------------------------------------------------------
@dataclass
class InboundFacet:
    """Retrieval permeability — what evidence may cross into the System."""

    collection_allowlist: List[str] = field(default_factory=list)
    reference_type_filters: List[str] = field(default_factory=list)
    reject_cross_project_sources: bool = False
    preserve_reference_types: bool = False
    expert_fiche_correction_enabled: bool = False
    industrial_grounding: bool = False

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InboundFacet":
        return cls(
            collection_allowlist=_as_str_list(data.get("collection_allowlist")),
            reference_type_filters=_as_str_list(data.get("reference_type_filters")),
            reject_cross_project_sources=bool(data.get("reject_cross_project_sources")),
            preserve_reference_types=bool(data.get("preserve_reference_types")),
            expert_fiche_correction_enabled=bool(data.get("expert_fiche_correction_enabled")),
            industrial_grounding=bool(data.get("industrial_grounding")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "collection_allowlist": list(self.collection_allowlist),
            "reference_type_filters": list(self.reference_type_filters),
            "reject_cross_project_sources": self.reject_cross_project_sources,
            "preserve_reference_types": self.preserve_reference_types,
            "expert_fiche_correction_enabled": self.expert_fiche_correction_enabled,
            "industrial_grounding": self.industrial_grounding,
        }


@dataclass
class OutboundFacet:
    """Egress gate — when a verdict must be held for human approval."""

    expert_review_required: bool = True
    gate_if_confidence_below: Optional[float] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OutboundFacet":
        review = data.get("expert_review_required")
        return cls(
            expert_review_required=bool(review) if review is not None else True,
            gate_if_confidence_below=_as_opt_float(data.get("gate_if_confidence_below")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "expert_review_required": self.expert_review_required,
            "gate_if_confidence_below": self.gate_if_confidence_below,
        }


@dataclass
class CapabilityFacet:
    """What skills / models the System may invoke + who it may delegate to.

    ``allowed_delegations`` is the typed-edge delegation ACL (P4): the set of
    System ids (or ``subflow:<id>`` tokens) a subflow node may target. Empty =
    no restriction (the default for derived specs), so existing flows delegate
    freely.
    """

    allowed_skills: List[str] = field(default_factory=list)
    allowed_models: List[str] = field(default_factory=list)
    allowed_delegations: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CapabilityFacet":
        return cls(
            allowed_skills=_as_str_list(data.get("allowed_skills")),
            allowed_models=_as_str_list(data.get("allowed_models")),
            allowed_delegations=_as_str_list(data.get("allowed_delegations")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed_skills": list(self.allowed_skills),
            "allowed_models": list(self.allowed_models),
            "allowed_delegations": list(self.allowed_delegations),
        }


@dataclass
class ProvenanceFacet:
    """Audit / lineage requirements attached to every decision."""

    require_citations: bool = False
    object_store_prefix: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProvenanceFacet":
        prefix = data.get("object_store_prefix")
        return cls(
            require_citations=bool(data.get("require_citations")),
            object_store_prefix=str(prefix) if prefix else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "require_citations": self.require_citations,
            "object_store_prefix": self.object_store_prefix,
        }


@dataclass
class ValvesFacet:
    """Hard guardrails + adaptive circuit-breaker / token budget.

    ``hard_abort`` is the opt-in upgrade over the post-hoc ``policy_breach``
    Decision: when True a breach aborts the run instead of merely logging it.
    Default ``False`` keeps the legacy log-only behaviour.
    """

    max_cost_per_decision: Optional[float] = None
    max_latency_ms: Optional[float] = None
    mandatory_hitl_if_confidence_below: Optional[float] = None
    hard_abort: bool = False
    circuit_breaker: Optional[Dict[str, Any]] = None
    token_budget: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ValvesFacet":
        cb = data.get("circuit_breaker")
        return cls(
            max_cost_per_decision=_as_opt_float(data.get("max_cost_per_decision")),
            max_latency_ms=_as_opt_float(data.get("max_latency_ms")),
            mandatory_hitl_if_confidence_below=_as_opt_float(
                data.get("mandatory_hitl_if_confidence_below")
            ),
            hard_abort=bool(data.get("hard_abort")),
            circuit_breaker=_as_mapping(cb) or None,
            token_budget=_as_opt_int(data.get("token_budget")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_cost_per_decision": self.max_cost_per_decision,
            "max_latency_ms": self.max_latency_ms,
            "mandatory_hitl_if_confidence_below": self.mandatory_hitl_if_confidence_below,
            "hard_abort": self.hard_abort,
            "circuit_breaker": self.circuit_breaker,
            "token_budget": self.token_budget,
        }


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------
@dataclass
class MembraneSpec:
    inbound: InboundFacet = field(default_factory=InboundFacet)
    outbound: OutboundFacet = field(default_factory=OutboundFacet)
    capabilities: CapabilityFacet = field(default_factory=CapabilityFacet)
    provenance: ProvenanceFacet = field(default_factory=ProvenanceFacet)
    valves: ValvesFacet = field(default_factory=ValvesFacet)
    # ``True`` only when parsed from an explicit ``extra.membrane_spec`` — the
    # signal every hook checks before tightening behaviour. A *derived* spec is
    # always read-through (no behaviour change).
    authoritative: bool = False
    version: int = 1

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, authoritative: bool = True) -> "MembraneSpec":
        data = _as_mapping(data)
        return cls(
            inbound=InboundFacet.from_dict(_as_mapping(data.get("inbound"))),
            outbound=OutboundFacet.from_dict(_as_mapping(data.get("outbound"))),
            capabilities=CapabilityFacet.from_dict(_as_mapping(data.get("capabilities"))),
            provenance=ProvenanceFacet.from_dict(_as_mapping(data.get("provenance"))),
            valves=ValvesFacet.from_dict(_as_mapping(data.get("valves"))),
            authoritative=authoritative,
            version=_as_opt_int(data.get("version")) or 1,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Canonical JSON form persisted in ``ControlPolicy.extra``.

        ``authoritative`` is intentionally *not* serialised — it is a runtime
        property of *how* the spec was loaded, not part of the contract.
        """
        return {
            "version": self.version,
            "inbound": self.inbound.to_dict(),
            "outbound": self.outbound.to_dict(),
            "capabilities": self.capabilities.to_dict(),
            "provenance": self.provenance.to_dict(),
            "valves": self.valves.to_dict(),
        }


def _derive_from_sources(
    source_policy: Optional[Mapping[str, Any]],
    control: Optional[Any],
) -> MembraneSpec:
    """Read-through derivation from the existing knobs (non-authoritative).

    This is the equivalence guarantee: a workspace with no ``membrane_spec``
    yields a spec whose facets *mirror* its current ``source_policy`` /
    ``ControlPolicy`` — so a hook reading the derived spec sees exactly the
    values it would have read directly.
    """
    sp = _as_mapping(source_policy)
    inbound = InboundFacet(
        reject_cross_project_sources=bool(sp.get("reject_cross_project_sources")),
        preserve_reference_types=bool(sp.get("preserve_reference_types")),
        expert_fiche_correction_enabled=bool(sp.get("expert_fiche_correction_enabled")),
        industrial_grounding=bool(sp.get("industrial_grounding")),
    )
    # ``expert_review_required`` defaults True (matches knowledge_capture); only
    # an explicit key flips it.
    review = sp.get("expert_review_required")
    outbound = OutboundFacet(
        expert_review_required=bool(review) if review is not None else True,
    )
    provenance = ProvenanceFacet(require_citations=bool(sp.get("require_citations")))

    capabilities = CapabilityFacet()
    valves = ValvesFacet()
    if control is not None:
        capabilities = CapabilityFacet(
            allowed_skills=_as_str_list(getattr(control, "allowed_skills", None)),
            allowed_models=_as_str_list(getattr(control, "allowed_models", None)),
        )
        valves = ValvesFacet(
            max_cost_per_decision=_as_opt_float(getattr(control, "max_cost_per_decision", None)),
            max_latency_ms=_as_opt_float(getattr(control, "max_latency_ms", None)),
            mandatory_hitl_if_confidence_below=_as_opt_float(
                getattr(control, "mandatory_hitl_if_confidence_below", None)
            ),
        )
    return MembraneSpec(
        inbound=inbound,
        outbound=outbound,
        capabilities=capabilities,
        provenance=provenance,
        valves=valves,
        authoritative=False,
    )


def resolve_membrane_spec(
    *,
    control: Optional[Any] = None,
    source_policy: Optional[Mapping[str, Any]] = None,
) -> MembraneSpec:
    """Resolve the effective MembraneSpec for a System / chat turn.

    Authoritative when ``control.extra["membrane_spec"]`` is present (the
    canonical store) or when a spec has been surfaced into
    ``source_policy["membrane_spec"]``; otherwise read-through derived from
    ``source_policy`` + ``control``.
    """
    extra = getattr(control, "extra", None)
    if isinstance(extra, Mapping):
        raw = extra.get("membrane_spec")
        if isinstance(raw, Mapping) and raw:
            return MembraneSpec.from_dict(raw, authoritative=True)
    if isinstance(source_policy, Mapping):
        raw = source_policy.get("membrane_spec")
        if isinstance(raw, Mapping) and raw:
            return MembraneSpec.from_dict(raw, authoritative=True)
    return _derive_from_sources(source_policy, control)
