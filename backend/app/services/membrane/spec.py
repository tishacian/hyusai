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
from enum import Enum
from math import isfinite
from typing import Any, Dict, Iterable, List, Mapping, Optional


class EnforcementMode(str, Enum):
    """Runtime posture of an explicit MembraneSpec v2.

    Version 1 and read-through/derived specs are always evaluated as
    :attr:`COMPAT`, even if an untrusted payload happens to carry another
    value.  This is the compatibility boundary that keeps existing Andritz
    policies unchanged while v2 is rolled out on an explicitly selected
    System.
    """

    COMPAT = "compat"
    SHADOW = "shadow"
    ENFORCE = "enforce"


class FacetState(str, Enum):
    NOT_CONFIGURED = "not_configured"
    CONFIGURED = "configured"
    SHADOW = "shadow"
    ENFORCED = "enforced"
    BREACHED = "breached"


FACET_NAMES = ("inbound", "outbound", "capabilities", "provenance", "valves")


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
        parsed = float(value)
        return parsed if isfinite(parsed) else None
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
    v2 typed rules a subflow node may target. In authoritative shadow/enforce,
    an empty list authorizes no delegation; v1/derived compatibility specs keep
    their historical unrestricted behaviour.
    """

    allowed_skills: List[str] = field(default_factory=list)
    allowed_models: List[str] = field(default_factory=list)
    # v2 entries: {system_id, input_contract, output_contract, branches}.
    # Legacy strings remain readable in compat mode only.
    allowed_delegations: List[Any] = field(default_factory=list)
    allowed_actions: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CapabilityFacet":
        return cls(
            allowed_skills=_as_str_list(data.get("allowed_skills")),
            allowed_models=_as_str_list(data.get("allowed_models")),
            allowed_delegations=[dict(v) if isinstance(v, Mapping) else str(v)
                                 for v in (data.get("allowed_delegations") or [])],
            allowed_actions=_as_str_list(data.get("allowed_actions")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed_skills": list(self.allowed_skills),
            "allowed_models": list(self.allowed_models),
            "allowed_delegations": [dict(v) if isinstance(v, Mapping) else v
                                     for v in self.allowed_delegations],
            "allowed_actions": list(self.allowed_actions),
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
    enforcement_mode: EnforcementMode = EnforcementMode.COMPAT

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, authoritative: bool = True) -> "MembraneSpec":
        data = _as_mapping(data)
        version = _as_opt_int(data.get("version")) or 1
        if version >= 2:
            _validate_v2_payload(data)
        raw_mode = data.get("enforcement_mode", EnforcementMode.COMPAT.value)
        try:
            mode = EnforcementMode(str(raw_mode).strip().lower())
        except ValueError:
            # v1 is deliberately permissive and cannot activate enforcement.
            # v2 has already failed strict validation above.
            mode = EnforcementMode.COMPAT
        if version < 2 or not authoritative:
            mode = EnforcementMode.COMPAT
        return cls(
            inbound=InboundFacet.from_dict(_as_mapping(data.get("inbound"))),
            outbound=OutboundFacet.from_dict(_as_mapping(data.get("outbound"))),
            capabilities=CapabilityFacet.from_dict(_as_mapping(data.get("capabilities"))),
            provenance=ProvenanceFacet.from_dict(_as_mapping(data.get("provenance"))),
            valves=ValvesFacet.from_dict(_as_mapping(data.get("valves"))),
            authoritative=authoritative,
            version=version,
            enforcement_mode=mode,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Canonical JSON form persisted in ``ControlPolicy.extra``.

        ``authoritative`` is intentionally *not* serialised — it is a runtime
        property of *how* the spec was loaded, not part of the contract.
        """
        payload = {
            "version": self.version,
            "inbound": self.inbound.to_dict(),
            "outbound": self.outbound.to_dict(),
            "capabilities": self.capabilities.to_dict(),
            "provenance": self.provenance.to_dict(),
            "valves": self.valves.to_dict(),
        }
        # Do not rewrite existing v1 artifacts.  Their absence of a mode is a
        # useful, explicit proof that they remain on the compatibility path.
        if self.version >= 2:
            payload["enforcement_mode"] = self.effective_mode.value
        return payload

    @property
    def effective_mode(self) -> EnforcementMode:
        if not self.authoritative or self.version < 2:
            return EnforcementMode.COMPAT
        return self.enforcement_mode

    @property
    def enforcement_active(self) -> bool:
        return self.effective_mode is EnforcementMode.ENFORCE

    @property
    def shadow_active(self) -> bool:
        return self.effective_mode is EnforcementMode.SHADOW

    def configured_facets(self) -> set[str]:
        """Return facets that carry an effective constraint.

        Configuration is semantic rather than based on key presence because
        the canonical JSON contains all five facet objects.  This makes the
        answer stable across API normalisation and DB round-trips.
        """

        configured: set[str] = set()
        inbound = self.inbound
        if (
            inbound.collection_allowlist
            or inbound.reference_type_filters
            or inbound.reject_cross_project_sources
            or inbound.preserve_reference_types
            or inbound.expert_fiche_correction_enabled
            or inbound.industrial_grounding
        ):
            configured.add("inbound")
        outbound = self.outbound
        if outbound.expert_review_required or outbound.gate_if_confidence_below is not None:
            configured.add("outbound")
        caps = self.capabilities
        if (
            caps.allowed_skills
            or caps.allowed_models
            or caps.allowed_delegations
            or caps.allowed_actions
        ):
            configured.add("capabilities")
        provenance = self.provenance
        if provenance.require_citations or provenance.object_store_prefix:
            configured.add("provenance")
        valves = self.valves
        if any(
            value is not None
            for value in (
                valves.max_cost_per_decision,
                valves.max_latency_ms,
                valves.mandatory_hitl_if_confidence_below,
                valves.circuit_breaker,
                valves.token_budget,
            )
        ) or valves.hard_abort:
            configured.add("valves")
        return configured

    def facet_states(self, *, breached: Iterable[str] = ()) -> Dict[str, str]:
        """Compute the externally visible state of all five facets."""

        configured = self.configured_facets()
        breached_set = {str(name) for name in breached}
        states: Dict[str, str] = {}
        for name in FACET_NAMES:
            if name not in configured:
                state = FacetState.NOT_CONFIGURED
            elif name in breached_set:
                state = FacetState.BREACHED
            elif self.effective_mode is EnforcementMode.SHADOW:
                state = FacetState.SHADOW
            elif self.effective_mode is EnforcementMode.ENFORCE:
                state = FacetState.ENFORCED
            else:
                state = FacetState.CONFIGURED
            states[name] = state.value
        return states


def _validate_v2_payload(data: Mapping[str, Any]) -> None:
    """Reject ambiguous v2 contracts at their parsing boundary.

    V1 intentionally remains permissive.  V2 is an enforcement contract, so
    accepting a misspelled mode or malformed allow-list would otherwise turn a
    fail-closed policy into a silent allow-all policy.
    """

    if _as_opt_int(data.get("version")) != 2:
        raise ValueError("unsupported membrane_spec version")
    try:
        EnforcementMode(str(data.get("enforcement_mode", "compat")).strip().lower())
    except ValueError as exc:
        raise ValueError("enforcement_mode must be compat, shadow or enforce") from exc

    for facet_name in FACET_NAMES:
        value = data.get(facet_name, {})
        if value is not None and not isinstance(value, Mapping):
            raise ValueError(f"membrane_spec.{facet_name} must be an object")

    inbound = _as_mapping(data.get("inbound"))
    capabilities = _as_mapping(data.get("capabilities"))
    for path, value in (
        ("inbound.collection_allowlist", inbound.get("collection_allowlist", [])),
        ("inbound.reference_type_filters", inbound.get("reference_type_filters", [])),
        ("capabilities.allowed_skills", capabilities.get("allowed_skills", [])),
        ("capabilities.allowed_models", capabilities.get("allowed_models", [])),
        ("capabilities.allowed_actions", capabilities.get("allowed_actions", [])),
    ):
        if not isinstance(value, (list, tuple)) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            raise ValueError(f"membrane_spec.{path} must be a list of non-empty strings")

    delegations = capabilities.get("allowed_delegations", [])
    if not isinstance(delegations, (list, tuple)):
        raise ValueError("membrane_spec.capabilities.allowed_delegations must be a list")
    for rule in delegations:
        if not isinstance(rule, Mapping) or not str(rule.get("system_id") or "").strip():
            raise ValueError("v2 allowed_delegations entries require system_id")
        for contract in ("input_contract", "output_contract"):
            if rule.get(contract) is not None and not isinstance(rule.get(contract), Mapping):
                raise ValueError(f"allowed_delegations.{contract} must be an object")
        branches = rule.get("branches", [])
        if not isinstance(branches, (list, tuple)) or any(not isinstance(v, str) or not v for v in branches):
            raise ValueError("allowed_delegations.branches must be a list of strings")

    outbound = _as_mapping(data.get("outbound"))
    valves = _as_mapping(data.get("valves"))
    bounded = (
        ("outbound.gate_if_confidence_below", outbound.get("gate_if_confidence_below"), 0.0, 1.0),
        (
            "valves.mandatory_hitl_if_confidence_below",
            valves.get("mandatory_hitl_if_confidence_below"),
            0.0,
            1.0,
        ),
    )
    for path, raw, minimum, maximum in bounded:
        if raw is None:
            continue
        value = _as_opt_float(raw)
        if value is None or not minimum <= value <= maximum:
            raise ValueError(f"membrane_spec.{path} must be between {minimum} and {maximum}")
    for path, raw in (
        ("valves.max_cost_per_decision", valves.get("max_cost_per_decision")),
        ("valves.max_latency_ms", valves.get("max_latency_ms")),
    ):
        if raw is not None and (_as_opt_float(raw) is None or float(raw) < 0):
            raise ValueError(f"membrane_spec.{path} must be a non-negative number")
    token_budget = valves.get("token_budget")
    if token_budget is not None and (_as_opt_int(token_budget) is None or int(token_budget) <= 0):
        raise ValueError("membrane_spec.valves.token_budget must be a positive integer")
    circuit_breaker = valves.get("circuit_breaker")
    if circuit_breaker is not None and not isinstance(circuit_breaker, Mapping):
        raise ValueError("membrane_spec.valves.circuit_breaker must be an object")


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
