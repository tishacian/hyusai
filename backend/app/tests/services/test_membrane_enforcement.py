from __future__ import annotations

from app.services.membrane.enforcement import (
    EgressDisposition,
    MeasurementCoverage,
    MembraneEnforcementError,
    ValveUsage,
    collect_valve_usage,
    decide_egress,
    enforce_inbound_collections,
    enforce_inbound_sources,
    evaluate_capability,
    evaluate_valves,
    persist_provenance_artifact,
)
from app.services.membrane.spec import MembraneSpec


def _spec(mode: str, **facets) -> MembraneSpec:
    return MembraneSpec.from_dict(
        {"version": 2, "enforcement_mode": mode, **facets},
        authoritative=True,
    )


def test_inbound_empty_intersection_is_fail_closed_only_in_enforce() -> None:
    enforce = _spec("enforce", inbound={"collection_allowlist": ["contracts"]})
    shadow = _spec("shadow", inbound={"collection_allowlist": ["contracts"]})
    legacy = MembraneSpec.from_dict(
        {"version": 1, "inbound": {"collection_allowlist": ["contracts"]}}
    )

    enforced = enforce_inbound_collections(enforce, ["other"])
    assert enforced.collections == []
    assert enforced.blocked is True
    assert "collection_allowlist_empty_intersection" in enforced.violations

    shadowed = enforce_inbound_collections(shadow, ["other"])
    assert shadowed.collections == ["other"]
    assert shadowed.would_block is True
    assert shadowed.blocked is False

    compatible = enforce_inbound_collections(legacy, ["other"])
    assert compatible.collections == ["other"]
    assert compatible.blocked is False


def test_inbound_sources_enforce_reference_type_and_project() -> None:
    spec = _spec(
        "enforce",
        inbound={
            "reference_type_filters": ["contract"],
            "reject_cross_project_sources": True,
        },
    )
    sources = [
        {"metadata": {"reference_type": "contract", "project_code": "A"}},
        {"metadata": {"reference_type": "email", "project_code": "A"}},
        {"metadata": {"reference_type": "contract", "project_code": "B"}},
    ]
    decision = enforce_inbound_sources(spec, sources, expected_project="A")
    assert decision.sources == [sources[0]]
    assert len(decision.violations) == 2


def test_inbound_project_separation_rejects_missing_tenant_proof() -> None:
    enforce = _spec(
        "enforce",
        inbound={"reject_cross_project_sources": True},
    )
    shadow = _spec(
        "shadow",
        inbound={"reject_cross_project_sources": True},
    )
    sources = [{"metadata": {"reference_type": "contract"}}]

    blocked = enforce_inbound_sources(enforce, sources, expected_project="A")
    assert blocked.sources == []
    assert blocked.blocked is True
    assert blocked.violations == ("source[0]:source_project_missing",)

    observed = enforce_inbound_sources(shadow, sources, expected_project=None)
    assert observed.sources == sources
    assert observed.blocked is False
    assert observed.would_block is True
    assert observed.violations == ("source[0]:expected_project_missing",)


def test_capability_skills_models_and_actions_share_one_gate() -> None:
    spec = _spec(
        "enforce",
        capabilities={
            "allowed_skills": ["semantic_search_v1"],
            "allowed_models": ["gpt-5"],
            "allowed_actions": ["system.engine.run"],
        },
    )
    allowed = evaluate_capability(
        spec,
        skill="semantic_search_v1",
        model="gpt-5",
        action="system.engine.run",
    )
    denied = evaluate_capability(spec, skill="mail_send_v1", model="gpt-4o")
    assert allowed.allowed is True
    assert denied.allowed is False
    assert denied.violations == (
        "skill_not_allowed:mail_send_v1",
        "model_not_allowed:gpt-4o",
    )


def test_egress_shadow_reports_hold_without_holding() -> None:
    spec = _spec(
        "shadow",
        outbound={"expert_review_required": True, "gate_if_confidence_below": 0.8},
        provenance={"require_citations": True},
    )
    decision = decide_egress(
        spec,
        confidence=0.5,
        citations=[],
        legacy_review_required=False,
    )
    assert decision.disposition is EgressDisposition.ALLOW
    assert decision.would_disposition is EgressDisposition.BLOCK
    assert set(decision.reasons) == {
        "expert_review_required",
        "confidence_below_gate",
        "citations_required",
    }


def test_valve_confidence_threshold_creates_real_enforce_hold() -> None:
    spec = _spec(
        "enforce",
        outbound={"expert_review_required": False},
        valves={"mandatory_hitl_if_confidence_below": 0.75},
    )
    decision = decide_egress(spec, confidence=0.5, citations=[])
    assert decision.disposition is EgressDisposition.HOLD
    assert decision.reasons == ("confidence_below_mandatory_hitl_valve",)


def test_valves_consume_tokens_failures_and_all_attempt_kinds() -> None:
    spec = _spec(
        "enforce",
        valves={
            "token_budget": 100,
            "circuit_breaker": {"failure_threshold": 2, "max_attempts": 3},
        },
    )
    usage = ValveUsage(
        tokens=101,
        token_coverage=MeasurementCoverage.COMPLETE,
        failures=2,
        retries=1,
        loops=1,
        autocorrections=1,
    )
    decision = evaluate_valves(spec, usage)
    assert decision.allowed is False
    assert set(decision.breaches) == {
        "token_budget",
        "circuit_breaker_failures",
        "circuit_breaker_attempts",
    }


def test_valve_usage_is_aggregated_from_persisted_attempt_traces() -> None:
    usage = collect_valve_usage(
        [
            {
                "status": "completed",
                "cost": 0.25,
                "cost_measured": True,
                "output_ref": {"usage": {"prompt_tokens": 10, "completion_tokens": 5}},
                "metrics": {"total_tokens": 15},
                "trace": {"membrane_attempt_kind": "task"},
            },
            {
                "status": "failed",
                "cost": 0.5,
                "cost_measured": True,
                "output_ref": {"token_usage": {"total_tokens": 20}},
                "trace": {
                    "membrane_attempt_kind": "retry",
                    "membrane_autocorrections": 1,
                },
            },
            {
                "status": "completed",
                "cost": 0.1,
                "cost_measured": True,
                "metrics": {"usage": {"input_tokens": 4, "output_tokens": 6}},
                "trace": {"membrane_attempt_kind": "loop"},
            },
        ],
        duration_ms=42,
    )
    assert usage.cost == 0.85
    assert usage.tokens == 45
    assert usage.failures == 1
    assert usage.retries == 1
    assert usage.loops == 1
    assert usage.autocorrections == 1
    assert usage.attempts == 4
    assert usage.cost_coverage is MeasurementCoverage.COMPLETE
    assert usage.token_coverage is MeasurementCoverage.COMPLETE


def test_unmeasured_cost_is_not_summed_and_v2_enforce_fails_closed() -> None:
    usage = collect_valve_usage(
        [
            {
                "status": "completed",
                "cost": 9.5,
                "cost_measured": False,
                "metrics": {"total_tokens": 0},
                "latency_ms": 1,
            }
        ]
    )
    assert usage.cost == 0
    assert usage.legacy_unverified_cost == 9.5
    assert usage.cost_coverage is MeasurementCoverage.UNAVAILABLE

    enforce = evaluate_valves(
        _spec("enforce", valves={"max_cost_per_decision": 10}),
        usage,
    )
    assert enforce.allowed is False
    assert enforce.breaches == ("cost_measurement_unavailable",)

    shadow = evaluate_valves(
        _spec("shadow", valves={"max_cost_per_decision": 10}),
        usage,
    )
    assert shadow.allowed is True
    assert shadow.would_block is True
    assert shadow.breaches == ("cost_measurement_unavailable",)


def test_compat_keeps_legacy_unverified_cost_threshold_behavior() -> None:
    usage = collect_valve_usage(
        [{"cost": 9.5, "cost_measured": False}],
        duration_ms=0,
    )
    compat = evaluate_valves(
        _spec(
            "compat",
            valves={"max_cost_per_decision": 5, "hard_abort": True},
        ),
        usage,
    )
    assert compat.allowed is False
    assert compat.breaches == ("max_cost_per_decision",)


def test_missing_tokens_are_distinct_from_an_explicit_zero() -> None:
    missing = collect_valve_usage(
        [{"cost": 0, "cost_measured": True, "latency_ms": 0}],
    )
    assert missing.tokens == 0
    assert missing.token_coverage is MeasurementCoverage.UNAVAILABLE
    missing_decision = evaluate_valves(
        _spec("enforce", valves={"token_budget": 1}),
        missing,
    )
    assert missing_decision.allowed is False
    assert missing_decision.breaches == ("token_measurement_unavailable",)

    reported_zero = collect_valve_usage(
        [
            {
                "cost": 0,
                "cost_measured": True,
                "metrics": {"usage": {"input_tokens": 0, "output_tokens": 0}},
                "latency_ms": 0,
            }
        ],
    )
    assert reported_zero.tokens == 0
    assert reported_zero.token_coverage is MeasurementCoverage.COMPLETE
    assert evaluate_valves(
        _spec("enforce", valves={"token_budget": 1}),
        reported_zero,
    ).allowed is True


def test_one_sided_or_explicitly_partial_tokens_never_become_complete() -> None:
    usage = collect_valve_usage(
        [
            {
                "cost": 0,
                "cost_measured": True,
                "output_ref": {"usage": {"prompt_tokens": 10}},
                # A mirrored total must not override the authoritative partial
                # marker persisted by the provider ledger.
                "metrics": {
                    "total_tokens": 10,
                    "token_evidence": {
                        "measurement_coverage": "partial",
                        "reported_total": 10,
                    },
                },
                "latency_ms": 0,
            }
        ]
    )

    assert usage.tokens == 0
    assert usage.token_coverage is MeasurementCoverage.UNAVAILABLE
    decision = evaluate_valves(
        _spec("enforce", valves={"token_budget": 10}),
        usage,
    )
    assert decision.allowed is False
    assert decision.breaches == ("token_measurement_unavailable",)


def test_partial_measurement_coverage_never_becomes_a_compliant_zero() -> None:
    usage = collect_valve_usage(
        [
            {
                "cost": 0,
                "cost_measured": True,
                "metrics": {"total_tokens": 0},
                "latency_ms": 0,
            }
        ],
        measurement_gaps=1,
    )
    assert usage.cost == 0
    assert usage.tokens == 0
    assert usage.cost_coverage is MeasurementCoverage.PARTIAL
    assert usage.token_coverage is MeasurementCoverage.PARTIAL
    decision = evaluate_valves(
        _spec("enforce", valves={"max_cost_per_decision": 1, "token_budget": 1}),
        usage,
    )
    assert decision.allowed is False
    assert decision.breaches == (
        "cost_measurement_unavailable",
        "token_measurement_unavailable",
    )


def test_latency_budget_uses_explicit_measurement_coverage() -> None:
    row = {"cost": 0, "cost_measured": True, "metrics": {"total_tokens": 0}}
    unavailable = collect_valve_usage([row])
    assert unavailable.latency_coverage is MeasurementCoverage.UNAVAILABLE
    blocked = evaluate_valves(
        _spec("enforce", valves={"max_latency_ms": 1}),
        unavailable,
    )
    assert blocked.allowed is False
    assert blocked.breaches == ("latency_measurement_unavailable",)

    measured_zero = collect_valve_usage([row], duration_ms=0)
    assert measured_zero.latency_coverage is MeasurementCoverage.COMPLETE
    assert evaluate_valves(
        _spec("enforce", valves={"max_latency_ms": 1}),
        measured_zero,
    ).allowed is True


class _MemoryStore:
    def __init__(self) -> None:
        self.content = {}

    def key(self, *parts) -> str:
        return "/".join(str(part).strip("/") for part in parts if str(part).strip("/"))

    def write_bytes(self, key: str, content: bytes) -> str:
        self.content[key] = content
        return key

    def read_bytes(self, key: str) -> bytes:
        return self.content[key]


class _BrokenStore(_MemoryStore):
    def read_bytes(self, key: str) -> bytes:
        raise OSError("object store unavailable")


def test_provenance_is_canonical_persisted_and_hashed() -> None:
    spec = _spec(
        "enforce",
        provenance={"require_citations": True, "object_store_prefix": "membrane/showcase"},
    )
    store = _MemoryStore()
    artifact = persist_provenance_artifact(
        spec,
        workspace_id="workspace-1",
        system_id="system-1",
        run_id="run-1",
        payload={"citations": [{"id": "source-1"}], "decision": "allow"},
        store=store,  # type: ignore[arg-type]
    )
    assert artifact is not None
    assert artifact.uri.startswith("object://membrane/showcase/")
    assert artifact.sha256 in artifact.key
    assert store.content[artifact.key]


def test_required_provenance_fails_closed_only_in_enforce() -> None:
    enforce = _spec("enforce", provenance={"require_citations": True})
    shadow = _spec("shadow", provenance={"require_citations": True})

    try:
        persist_provenance_artifact(
            enforce,
            workspace_id="w",
            system_id="s",
            run_id="r",
            payload={"citations": [{"id": "source"}]},
            store=_BrokenStore(),  # type: ignore[arg-type]
        )
    except MembraneEnforcementError as exc:
        assert str(exc) == "membrane_provenance_persistence_failed"
    else:  # pragma: no cover - makes the fail-closed invariant explicit.
        raise AssertionError("enforce provenance failure must block")

    assert (
        persist_provenance_artifact(
            shadow,
            workspace_id="w",
            system_id="s",
            run_id="r",
            payload={"citations": [{"id": "source"}]},
            store=_BrokenStore(),  # type: ignore[arg-type]
        )
        is None
    )
