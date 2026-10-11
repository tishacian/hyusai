"""Authoritative MembraneSpec v2 enforcement helpers.

The functions in this module are deliberately framework-neutral.  API, RAG,
the DAG walker and Knowledge Capture all receive the same decisions instead of
re-implementing subtly different policy branches.

Compatibility rule:

* derived and v1 specs retain their pre-v2 behaviour;
* v2 ``shadow`` reports the decision it *would* take but never tightens data;
* only explicit, authoritative v2 ``enforce`` contracts fail closed.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.object_store import ObjectStore

from .spec import EnforcementMode, MembraneSpec


class MembraneEnforcementError(RuntimeError):
    """Raised when a mandatory v2 facet cannot be enforced safely."""


class EgressDisposition(str, Enum):
    ALLOW = "allow"
    HOLD = "hold"
    BLOCK = "block"


class MeasurementCoverage(str, Enum):
    """How completely a persisted ledger covers one valve measurement.

    ``0`` is a valid, complete measurement.  ``UNAVAILABLE`` and ``PARTIAL``
    therefore cannot be inferred from the aggregate numeric value; they must
    travel alongside it.
    """

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class InboundDecision:
    collections: list[str]
    sources: list[Mapping[str, Any]] = field(default_factory=list)
    violations: tuple[str, ...] = ()
    would_block: bool = False
    blocked: bool = False
    mode: str = EnforcementMode.COMPAT.value


@dataclass(frozen=True)
class CapabilityDecision:
    allowed: bool
    would_block: bool
    violations: tuple[str, ...]
    mode: str


@dataclass(frozen=True)
class EgressDecision:
    disposition: EgressDisposition
    would_disposition: EgressDisposition
    reasons: tuple[str, ...]
    mode: str


@dataclass(frozen=True)
class ValveUsage:
    cost: float = 0.0
    latency_ms: float = 0.0
    tokens: int = 0
    cost_coverage: MeasurementCoverage = MeasurementCoverage.UNAVAILABLE
    token_coverage: MeasurementCoverage = MeasurementCoverage.UNAVAILABLE
    latency_coverage: MeasurementCoverage = MeasurementCoverage.UNAVAILABLE
    invocation_count: int = 0
    measurement_gap_count: int = 0
    cost_measurement_count: int = 0
    token_measurement_count: int = 0
    latency_measurement_count: int = 0
    # Kept outside ``cost`` so v2 enforcement never treats an unverified
    # catalogue/default value as measured.  Compat can still reproduce the
    # historical threshold calculation during migration.
    legacy_unverified_cost: float = 0.0
    failures: int = 0
    retries: int = 0
    loops: int = 0
    autocorrections: int = 0

    @property
    def attempts(self) -> int:
        return 1 + self.retries + self.loops + self.autocorrections


@dataclass(frozen=True)
class ValveDecision:
    allowed: bool
    would_block: bool
    breaches: tuple[str, ...]
    usage: ValveUsage
    mode: str


@dataclass(frozen=True)
class ProvenanceArtifact:
    uri: str
    key: str
    sha256: str
    size_bytes: int
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def enforce_inbound_collections(
    spec: MembraneSpec,
    collections: Iterable[str],
) -> InboundDecision:
    """Apply the collection allow-list with v1 compatibility and v2 safety."""

    original = list(dict.fromkeys(str(item) for item in collections if str(item)))
    allowlist = list(dict.fromkeys(spec.inbound.collection_allowlist))
    if not spec.authoritative or not allowlist:
        return InboundDecision(collections=original, mode=spec.effective_mode.value)

    allowed = set(allowlist)
    filtered = [item for item in original if item in allowed]
    violations = tuple(f"collection_not_allowed:{item}" for item in original if item not in allowed)
    empty_intersection = bool(original) and not filtered
    if empty_intersection:
        violations = (*violations, "collection_allowlist_empty_intersection")

    if spec.effective_mode is EnforcementMode.ENFORCE:
        return InboundDecision(
            collections=filtered,
            violations=violations,
            would_block=empty_intersection,
            blocked=empty_intersection,
            mode=spec.effective_mode.value,
        )
    if spec.effective_mode is EnforcementMode.SHADOW:
        return InboundDecision(
            collections=original,
            violations=violations,
            would_block=empty_intersection,
            blocked=False,
            mode=spec.effective_mode.value,
        )

    # Authoritative v1 kept its historic fail-soft fallback when the
    # intersection was empty.  Non-empty intersections are still narrowed.
    return InboundDecision(
        collections=filtered or original,
        violations=violations,
        would_block=False,
        blocked=False,
        mode=spec.effective_mode.value,
    )


def enforce_inbound_sources(
    spec: MembraneSpec,
    sources: Sequence[Mapping[str, Any]],
    *,
    expected_project: str | None = None,
) -> InboundDecision:
    """Filter reference types and cross-project evidence for v2 contracts."""

    original = [item for item in sources if isinstance(item, Mapping)]
    if not spec.authoritative or spec.effective_mode is EnforcementMode.COMPAT:
        return InboundDecision(collections=[], sources=original, mode=spec.effective_mode.value)

    allowed_types = set(spec.inbound.reference_type_filters)
    project = str(expected_project or "").strip().casefold()
    kept: list[Mapping[str, Any]] = []
    violations: list[str] = []
    for index, source in enumerate(original):
        metadata = source.get("metadata") if isinstance(source.get("metadata"), Mapping) else source
        reference_type = str(
            metadata.get("reference_type")
            or metadata.get("source_type")
            or metadata.get("semantic_type")
            or ""
        ).strip()
        source_project = str(
            metadata.get("project_code") or metadata.get("project") or ""
        ).strip().casefold()
        reasons: list[str] = []
        if allowed_types and reference_type not in allowed_types:
            reasons.append(f"reference_type_not_allowed:{reference_type or 'missing'}")
        if spec.inbound.reject_cross_project_sources:
            # Project separation is a fail-closed boundary in v2.  Missing
            # tenant metadata is not proof that a source belongs to the
            # requested project, and a missing expected project makes the
            # comparison itself unenforceable.
            if not project:
                reasons.append("expected_project_missing")
            elif not source_project:
                reasons.append("source_project_missing")
            elif source_project != project:
                reasons.append(f"cross_project_source:{source_project}")
        if reasons:
            violations.extend(f"source[{index}]:{reason}" for reason in reasons)
        else:
            kept.append(source)

    would_block = bool(original) and not kept
    if spec.effective_mode is EnforcementMode.SHADOW:
        return InboundDecision(
            collections=[],
            sources=original,
            violations=tuple(violations),
            would_block=would_block,
            mode=spec.effective_mode.value,
        )
    return InboundDecision(
        collections=[],
        sources=kept,
        violations=tuple(violations),
        would_block=would_block,
        blocked=would_block,
        mode=spec.effective_mode.value,
    )


def evaluate_capability(
    spec: MembraneSpec,
    *,
    skill: str | None = None,
    model: str | None = None,
    action: str | None = None,
) -> CapabilityDecision:
    """Evaluate the capability allow-lists through one shared policy gate."""

    violations: list[str] = []
    facet = spec.capabilities
    if skill and facet.allowed_skills and skill not in facet.allowed_skills:
        violations.append(f"skill_not_allowed:{skill}")
    if facet.allowed_models and (not model or model not in facet.allowed_models):
        violations.append(f"model_not_allowed:{model or 'missing'}")
    if action and facet.allowed_actions and action not in facet.allowed_actions:
        violations.append(f"action_not_allowed:{action}")
    would_block = bool(violations)

    # Skill allow-listing existed before v2.  Preserve it in compat; model and
    # action enforcement are activated only by v2 enforce.
    compat_skill_block = bool(skill and violations and any(v.startswith("skill_") for v in violations))
    blocked = compat_skill_block if spec.effective_mode is EnforcementMode.COMPAT else False
    if spec.effective_mode is EnforcementMode.ENFORCE:
        blocked = would_block
    return CapabilityDecision(
        allowed=not blocked,
        would_block=would_block,
        violations=tuple(violations),
        mode=spec.effective_mode.value,
    )


def decide_egress(
    spec: MembraneSpec,
    *,
    confidence: float | None = None,
    citations: Sequence[Any] | None = None,
    legacy_review_required: bool | None = None,
    include_provenance: bool = True,
) -> EgressDecision:
    """Resolve ALLOW/HOLD/BLOCK for every egress surface.

    ``legacy_review_required`` is used by Knowledge Capture in compat/shadow
    mode.  In v2 enforce the membrane becomes the sole owner of the decision.
    """

    reasons: list[str] = []
    requested = EgressDisposition.ALLOW
    review_required = spec.outbound.expert_review_required
    threshold = spec.outbound.gate_if_confidence_below
    if review_required:
        reasons.append("expert_review_required")
        requested = EgressDisposition.HOLD
    if threshold is not None and (confidence is None or float(confidence) < threshold):
        reasons.append("confidence_below_gate")
        requested = EgressDisposition.HOLD
    valve_threshold = spec.valves.mandatory_hitl_if_confidence_below
    if valve_threshold is not None and (
        confidence is None or float(confidence) < valve_threshold
    ):
        reasons.append("confidence_below_mandatory_hitl_valve")
        requested = EgressDisposition.HOLD
    if include_provenance and spec.provenance.require_citations and not citations:
        reasons.append("citations_required")
        requested = EgressDisposition.BLOCK

    if spec.effective_mode is EnforcementMode.ENFORCE:
        actual = requested
    elif spec.effective_mode is EnforcementMode.SHADOW:
        actual = (
            EgressDisposition.HOLD
            if legacy_review_required
            else EgressDisposition.ALLOW
        )
    else:
        actual = (
            EgressDisposition.HOLD
            if legacy_review_required is True
            else requested
            if legacy_review_required is None
            else EgressDisposition.ALLOW
        )
    return EgressDecision(
        disposition=actual,
        would_disposition=requested,
        reasons=tuple(reasons),
        mode=spec.effective_mode.value,
    )


def evaluate_valves(spec: MembraneSpec, usage: ValveUsage) -> ValveDecision:
    """Consume cost/latency/token/attempt counters against the v2 valves."""

    valves = spec.valves
    breaches: list[str] = []
    strict_measurements = (
        spec.authoritative
        and spec.version >= 2
        and spec.effective_mode is not EnforcementMode.COMPAT
    )
    if valves.max_cost_per_decision is not None:
        if strict_measurements and usage.cost_coverage is not MeasurementCoverage.COMPLETE:
            breaches.append("cost_measurement_unavailable")
        comparable_cost = (
            usage.cost + usage.legacy_unverified_cost
            if spec.effective_mode is EnforcementMode.COMPAT
            else usage.cost
        )
        if comparable_cost > valves.max_cost_per_decision:
            breaches.append("max_cost_per_decision")
    if valves.max_latency_ms is not None:
        if strict_measurements and usage.latency_coverage is not MeasurementCoverage.COMPLETE:
            breaches.append("latency_measurement_unavailable")
        if usage.latency_ms > valves.max_latency_ms:
            breaches.append("max_latency_ms")
    if valves.token_budget is not None:
        if strict_measurements and usage.token_coverage is not MeasurementCoverage.COMPLETE:
            breaches.append("token_measurement_unavailable")
        if usage.tokens > valves.token_budget:
            breaches.append("token_budget")
    circuit = valves.circuit_breaker or {}
    failure_threshold = circuit.get("failure_threshold", circuit.get("failures"))
    max_attempts = circuit.get("max_attempts")
    try:
        if failure_threshold is not None and usage.failures >= int(failure_threshold):
            breaches.append("circuit_breaker_failures")
    except (TypeError, ValueError):
        breaches.append("circuit_breaker_invalid")
    try:
        if max_attempts is not None and usage.attempts > int(max_attempts):
            breaches.append("circuit_breaker_attempts")
    except (TypeError, ValueError):
        breaches.append("circuit_breaker_invalid")

    breaches = list(dict.fromkeys(breaches))
    would_block = bool(breaches)
    if spec.effective_mode is EnforcementMode.ENFORCE:
        blocked = would_block
    elif spec.effective_mode is EnforcementMode.COMPAT:
        blocked = bool(valves.hard_abort and breaches)
    else:
        blocked = False
    return ValveDecision(
        allowed=not blocked,
        would_block=would_block,
        breaches=tuple(breaches),
        usage=usage,
        mode=spec.effective_mode.value,
    )


_INCOMPLETE_TOKEN_COVERAGE = frozenset(
    {"partial", "unavailable", "not_measured", "not_configured", "restricted"}
)


def _declares_incomplete_token_coverage(payload: Any) -> bool:
    """Recognize an explicit incomplete marker before reading mirrored totals."""

    if not isinstance(payload, Mapping):
        return False
    coverage = str(payload.get("measurement_coverage") or "").strip().lower()
    if coverage in _INCOMPLETE_TOKEN_COVERAGE:
        return True
    for key in (
        "usage",
        "token_usage",
        "provider_usage",
        "token_evidence",
        "metrics",
        "meta",
    ):
        if _declares_incomplete_token_coverage(payload.get(key)):
            return True
    return False


def token_measurement_from_payload(payload: Any) -> tuple[int, bool]:
    """Return ``(token_count, reported)`` without conflating missing and zero."""

    if not isinstance(payload, Mapping):
        return 0, False
    if _declares_incomplete_token_coverage(payload):
        return 0, False
    containers: list[Mapping[str, Any]] = [payload]
    for key in ("usage", "token_usage", "metrics", "meta"):
        candidate = payload.get(key)
        if isinstance(candidate, Mapping):
            containers.append(candidate)
            nested = candidate.get("usage")
            if isinstance(nested, Mapping):
                containers.append(nested)
    for container in containers:
        for key in ("total_tokens", "tokens_total", "token_count"):
            parsed = _non_negative_int(container.get(key))
            if parsed is not None:
                return parsed, True
        prompt = _first_int(container, ("prompt_tokens", "input_tokens"))
        completion = _first_int(container, ("completion_tokens", "output_tokens"))
        if prompt is not None and completion is not None:
            return prompt + completion, True
    return 0, False


def token_count_from_payload(payload: Any) -> int:
    """Return one reported token total without double counting mirrors.

    Providers and wrappers expose usage under a handful of stable containers.
    We prefer an explicit total, otherwise sum prompt/input and
    completion/output counts within the first container that reports them.
    """

    return token_measurement_from_payload(payload)[0]


def collect_valve_usage(
    invocations: Iterable[Any],
    *,
    duration_ms: float | None = None,
    measurement_gaps: int = 0,
) -> ValveUsage:
    """Aggregate persisted invocation ledgers into the v2 valve contract.

    ``Any`` is intentional: this helper accepts SQLAlchemy rows as well as
    mappings used by unit tests and offline attestation jobs.
    """

    rows = list(invocations)
    cost = 0.0
    legacy_unverified_cost = 0.0
    tokens = 0
    cost_measurements = 0
    token_measurements = 0
    latency_measurements = 0
    invocation_latency_ms = 0.0
    failures = 0
    retries = 0
    loops = 0
    autocorrections = 0
    for invocation in rows:
        getter = invocation.get if isinstance(invocation, Mapping) else None

        def value(name: str, default: Any = None) -> Any:
            if getter is not None:
                return getter(name, default)
            return getattr(invocation, name, default)

        parsed_cost = _non_negative_float(value("cost"))
        if value("cost_measured") is True and parsed_cost is not None:
            cost += parsed_cost
            cost_measurements += 1
        elif parsed_cost is not None:
            legacy_unverified_cost += parsed_cost
        status = str(value("status", "") or "").lower()
        if status in {"failed", "cancelled"}:
            failures += 1
        output = value("output_ref", {})
        metrics = value("metrics", {})
        output_tokens, output_reported = token_measurement_from_payload(output)
        metric_tokens, metrics_reported = token_measurement_from_payload(metrics)
        explicitly_incomplete = _declares_incomplete_token_coverage(
            output
        ) or _declares_incomplete_token_coverage(metrics)
        if not explicitly_incomplete and (output_reported or metrics_reported):
            tokens += max(output_tokens, metric_tokens)
            token_measurements += 1
        invocation_latency = _non_negative_float(value("latency_ms"))
        if invocation_latency is not None:
            invocation_latency_ms += invocation_latency
            latency_measurements += 1
        trace = value("trace", {})
        if not isinstance(trace, Mapping):
            trace = {}
        attempt_kind = str(trace.get("membrane_attempt_kind") or "").lower()
        if attempt_kind == "retry":
            retries += 1
        elif attempt_kind == "loop":
            loops += 1
        autocorrections += _non_negative_int(trace.get("membrane_autocorrections")) or 0

    gaps = _non_negative_int(measurement_gaps) or 0
    measurement_subjects = len(rows) + gaps
    explicit_duration = _non_negative_float(duration_ms)
    if explicit_duration is not None:
        latency_ms = explicit_duration
        latency_coverage = MeasurementCoverage.COMPLETE
        latency_measurements = measurement_subjects
    else:
        latency_ms = invocation_latency_ms
        latency_coverage = _coverage(measurement_subjects, latency_measurements)

    return ValveUsage(
        cost=cost,
        latency_ms=latency_ms,
        tokens=tokens,
        cost_coverage=_coverage(measurement_subjects, cost_measurements),
        token_coverage=_coverage(measurement_subjects, token_measurements),
        latency_coverage=latency_coverage,
        invocation_count=len(rows),
        measurement_gap_count=gaps,
        cost_measurement_count=cost_measurements,
        token_measurement_count=token_measurements,
        latency_measurement_count=latency_measurements,
        legacy_unverified_cost=legacy_unverified_cost,
        failures=failures,
        retries=retries,
        loops=loops,
        autocorrections=autocorrections,
    )


def persist_provenance_artifact(
    spec: MembraneSpec,
    *,
    workspace_id: str,
    system_id: str | None,
    run_id: str,
    payload: Mapping[str, Any],
    store: ObjectStore | None = None,
) -> ProvenanceArtifact | None:
    """Persist canonical provenance bytes and return immutable evidence.

    A required v2 artifact is fail-closed: write/read verification failures
    raise :class:`MembraneEnforcementError`.  Compat and shadow keep their
    historical non-blocking behaviour and simply return ``None``.
    """

    if not spec.authoritative or "provenance" not in spec.configured_facets():
        return None
    created_at = datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
    document = {
        "schema_version": 1,
        "membrane_version": spec.version,
        "enforcement_mode": spec.effective_mode.value,
        "workspace_id": workspace_id,
        "system_id": system_id,
        "run_id": run_id,
        "created_at": created_at,
        "payload": _jsonable(payload),
    }
    encoded = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    sha256 = hashlib.sha256(encoded).hexdigest()
    prefix = spec.provenance.object_store_prefix or f"membrane/{workspace_id}/{run_id}"
    if store is None:
        from app.services.object_store import get_object_store

        object_store = get_object_store()
    else:
        object_store = store
    key = object_store.key(prefix, f"provenance-{sha256}.json")
    try:
        persisted_key = object_store.write_bytes(key, encoded)
        persisted = object_store.read_bytes(persisted_key)
        if hashlib.sha256(persisted).hexdigest() != sha256:
            raise OSError("provenance artifact checksum mismatch")
    except Exception as exc:  # noqa: BLE001 - policy decides whether failure is fatal.
        if spec.enforcement_active:
            raise MembraneEnforcementError("membrane_provenance_persistence_failed") from exc
        return None
    return ProvenanceArtifact(
        uri=f"object://{persisted_key}",
        key=persisted_key,
        sha256=sha256,
        size_bytes=len(encoded),
        created_at=created_at,
    )


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(item) for item in value]
    return str(value)


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _non_negative_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if isinstance(value, bool) or not math.isfinite(parsed) or parsed < 0:
        return None
    return parsed


def _coverage(total: int, measured: int) -> MeasurementCoverage:
    if total <= 0 or measured <= 0:
        return MeasurementCoverage.UNAVAILABLE
    if measured >= total:
        return MeasurementCoverage.COMPLETE
    return MeasurementCoverage.PARTIAL


def _first_int(container: Mapping[str, Any], keys: Sequence[str]) -> int | None:
    for key in keys:
        parsed = _non_negative_int(container.get(key))
        if parsed is not None:
            return parsed
    return None
