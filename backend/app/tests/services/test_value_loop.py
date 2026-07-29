"""Behavioral contract for the authoritative Lot-8 value loop."""
from __future__ import annotations

import copy
import inspect
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import update

from app.models.audit import AuditLog
from app.models.decision import Decision
from app.models.policy import ControlPolicy
from app.models.run import Run
from app.models.system import System
from app.models.value_loop import (
    ValueActionExecution,
    ValueLoopOperation,
    ValueMeasurement,
    ValueScenario,
    ValueSimulation,
)
from app.models.workspace import Workspace
from app.services import value_loop as service
from app.services.control_policy_snapshot import control_policy_execution_contract
from app.services.outcome.derive import apply_operator_override
from app.services.run_outcome_provenance import (
    record_operator_outcome_override,
    record_runtime_auto_outcome,
    run_measurement_provenance,
)

ACTUATOR = service.CONTROL_POLICY_GUARDRAILS_PATCH_V1
RUNTIME_REVISION = "a" * 40


def _membrane(*, allowed: bool = True) -> dict:
    return {
        "version": 2,
        "enforcement_mode": "enforce",
        "capabilities": {"allowed_actions": [ACTUATOR] if allowed else []},
    }


def _settings(*, enabled: bool = True) -> dict:
    return {
        "value_loop": {
            "actuators": {
                ACTUATOR: {
                    "enabled": enabled,
                    "fields": {
                        "max_cost_per_decision": {"min": 0, "max": 50},
                        "max_latency_ms": {"min": 100, "max": 30_000},
                        "mandatory_hitl_if_confidence_below": {
                            "min": 0,
                            "max": 1,
                        },
                    },
                }
            }
        },
        "steering_model": {
            "version": "value-model-v1",
            "confidence": 0.82,
            "assumptions": ["Comparable 30-day run mix", "Stable request volume"],
            "forecasts": {
                "max_cost_per_decision": [
                    {
                        "minimum": 0,
                        "maximum": 50,
                        "include_maximum": True,
                        "cost_multiplier": 0.9,
                        "value_multiplier": 1.25,
                    }
                ],
                "max_latency_ms": [
                    {
                        "minimum": 100,
                        "maximum": 30_000,
                        "include_maximum": True,
                        "cost_multiplier": 0.9,
                        "value_multiplier": 1.25,
                    }
                ],
                "mandatory_hitl_if_confidence_below": [
                    {
                        "minimum": 0,
                        "maximum": 1,
                        "include_maximum": True,
                        "cost_multiplier": 0.9,
                        "value_multiplier": 1.25,
                    }
                ],
            },
        },
    }


def _seed(
    db,
    *,
    baseline_source: str = "auto",
    membrane_allowed: bool = True,
    actuator_enabled: bool = True,
) -> tuple[Workspace, System, ControlPolicy, Run]:
    suffix = uuid4().hex[:10]
    workspace = Workspace(
        id=str(uuid4()),
        name=f"Value loop {suffix}",
        slug=f"value-loop-{suffix}",
    )
    policy = ControlPolicy(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="System guardrails",
        scope="system",
        max_cost_per_decision=8.0,
        max_latency_ms=8_000.0,
        mandatory_hitl_if_confidence_below=0.45,
        extra={"membrane_spec": _membrane(allowed=membrane_allowed)},
    )
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Contract Risk",
        objective="Reduce contract risk",
        status="active",
        control_policy_id=policy.id,
        settings=_settings(enabled=actuator_enabled),
    )
    policy.target_id = system.id
    baseline = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        status="completed",
        started_at=datetime.utcnow() - timedelta(hours=2),
        completed_at=datetime.utcnow() - timedelta(hours=1),
        decision="allow",
        confidence=0.7,
        value_estimated=100.0,
        cost_internal=10.0,
        efficiency=1.0,
        value_source=baseline_source,
        input_ref={
            "execution": {
                "control_policy": control_policy_execution_contract(policy),
                "flow_sha256": "b" * 64,
                "runtime_revision": RUNTIME_REVISION,
            }
        },
    )
    db.add_all([workspace, policy, system, baseline])
    db.commit()
    if baseline_source == "auto":
        record_runtime_auto_outcome(baseline, db=db)
        db.commit()
    return workspace, system, policy, baseline


def _scenario(db, workspace: Workspace, system: System, baseline: Run):
    return service.create_value_scenario(
        db,
        workspace_id=workspace.id,
        system_id=system.id,
        source_run_id=baseline.id,
        objective="Improve value without weakening risk controls",
        title="Tighten the confidence gate",
        rationale={"source": "operator"},
        actor="owner@example.test",
        idempotency_key=f"scenario-{uuid4()}",
    )


def _simulation(db, workspace: Workspace, scenario: ValueScenario, *, patch=None):
    return service.simulate_value_scenario(
        db,
        workspace_id=workspace.id,
        scenario_id=scenario.id,
        recommended_patch=patch or {"mandatory_hitl_if_confidence_below": 0.6},
        actor="analyst@example.test",
        idempotency_key=f"simulate-{uuid4()}",
    )


def _approved(db, workspace, system, baseline, *, patch=None):
    scenario, decision = _scenario(db, workspace, system, baseline)
    simulation = _simulation(db, workspace, scenario, patch=patch)
    scenario = service.approve_value_scenario(
        db,
        workspace_id=workspace.id,
        scenario_id=scenario.id,
        simulation_id=simulation.id,
        actor="approver@example.test",
        idempotency_key=f"approve-{uuid4()}",
    )
    return scenario, simulation, decision


def _acted(db, workspace, system, baseline, *, patch=None):
    patch = patch or {"mandatory_hitl_if_confidence_below": 0.6}
    scenario, simulation, decision = _approved(db, workspace, system, baseline, patch=patch)
    action = service.act_value_scenario(
        db,
        workspace_id=workspace.id,
        scenario_id=scenario.id,
        actuator=ACTUATOR,
        patch=patch,
        actor="operator@example.test",
        idempotency_key=f"act-{uuid4()}",
    )
    return scenario, simulation, decision, action


def _post_action_run(
    db,
    workspace: Workspace,
    system: System,
    action: ValueActionExecution,
    *,
    source: str = "auto",
    value: float = 130.0,
) -> Run:
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        status="completed",
        started_at=action.executed_at + timedelta(seconds=1),
        completed_at=action.executed_at + timedelta(seconds=2),
        decision="allow",
        confidence=0.8,
        value_estimated=value,
        cost_internal=8.0,
        efficiency=1.3,
        value_source=source,
        input_ref={
            "execution": {
                "control_policy": action.after_state["_control_policy"],
                "flow_sha256": "c" * 64,
                "runtime_revision": RUNTIME_REVISION,
            }
        },
    )
    db.add(run)
    db.commit()
    if source == "auto":
        record_runtime_auto_outcome(run, db=db)
        db.commit()
    return run


def test_complete_loop_keeps_simulation_and_measurement_distinct(db_session):
    workspace, system, policy, baseline = _seed(db_session)
    scenario, simulation, decision = _approved(db_session, workspace, system, baseline)

    assert scenario.status == "approved"
    assert simulation.projected_outcome["evidence_type"] == "simulation"
    assert decision.status == "accepted"
    assert decision.impact_estimate["evidence_type"] == "simulation"

    action = service.act_value_scenario(
        db_session,
        workspace_id=workspace.id,
        scenario_id=scenario.id,
        actuator=ACTUATOR,
        patch={"mandatory_hitl_if_confidence_below": 0.6},
        actor="operator@example.test",
        idempotency_key="act-complete-loop",
    )
    db_session.refresh(policy)
    assert policy.mandatory_hitl_if_confidence_below == 0.6
    assert action.before_state["mandatory_hitl_if_confidence_below"] == 0.45
    assert action.after_state["mandatory_hitl_if_confidence_below"] == 0.6
    assert action.before_state["_control_policy"]["sha256"] != (
        action.after_state["_control_policy"]["sha256"]
    )

    observed_run = _post_action_run(db_session, workspace, system, action)
    measurement = service.measure_value_scenario(
        db_session,
        workspace_id=workspace.id,
        scenario_id=scenario.id,
        source_run_id=observed_run.id,
        actor="operator@example.test",
        idempotency_key="measure-complete-loop",
    )

    db_session.refresh(scenario)
    db_session.refresh(decision)
    assert scenario.status == "measured"
    assert decision.status == "applied"
    assert measurement.status == "measured"
    assert measurement.simulation_id == simulation.id
    assert measurement.source_run_id == observed_run.id
    assert measurement.observed_outcome["source_type"] == "run"
    assert measurement.observed_outcome.get("evidence_type") is None
    assert measurement.observed_outcome["measurement_provenance"]["source"] == "runtime_auto"
    assert measurement.observed_outcome["measurement_provenance"]["actor"] == "run_engine"
    assert measurement.observed_outcome["measurement_provenance"]["artifact_ref"].startswith(
        "sha256:"
    )
    assert measurement.delta["value"] == 30.0
    assert measurement.forecast_delta == {"value": 5.0, "cost": -1.0}
    assert measurement.assumption_verdict == "confirmed"
    assert measurement.assumption_evaluation["verdict"] == "confirmed"
    assert measurement.assumption_evaluation["causality"] == "not_established"
    assert measurement.assumption_evaluation["declared_assumptions"] == (
        simulation.assumptions
    )
    assert db_session.query(ValueSimulation).count() == 1
    assert db_session.query(ValueMeasurement).count() == 1
    assert [
        row.event_type
        for row in db_session.query(AuditLog)
        .filter(
            AuditLog.workspace_id == workspace.id,
            AuditLog.event_type.like("value_loop.%"),
        )
        .order_by(AuditLog.timestamp, AuditLog.event_type)
        .all()
    ] == [
        "value_loop.scenario.created",
        "value_loop.simulation.created",
        "value_loop.scenario.approved",
        "value_loop.action.executed",
        "value_loop.measurement.measured",
    ]


def test_action_retry_is_idempotent_and_request_hash_is_bound(db_session):
    workspace, system, policy, baseline = _seed(db_session)
    scenario, _simulation_row, _decision = _approved(db_session, workspace, system, baseline)
    kwargs = {
        "workspace_id": workspace.id,
        "scenario_id": scenario.id,
        "actuator": ACTUATOR,
        "patch": {"mandatory_hitl_if_confidence_below": 0.6},
        "actor": "operator@example.test",
        "idempotency_key": "same-action-request",
    }
    first = service.act_value_scenario(db_session, **kwargs)
    second = service.act_value_scenario(db_session, **kwargs)

    assert second.id == first.id
    assert db_session.query(ValueActionExecution).count() == 1
    assert (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "value_loop.action.executed")
        .count()
        == 1
    )
    with pytest.raises(service.ValueLoopConflict) as caught:
        service.act_value_scenario(
            db_session,
            **{**kwargs, "patch": {"mandatory_hitl_if_confidence_below": 0.7}},
        )
    assert caught.value.code == "idempotency_conflict"
    db_session.refresh(policy)
    assert policy.mandatory_hitl_if_confidence_below == 0.6


def test_idempotency_key_is_unique_across_operation_types(db_session):
    workspace, system, _policy, baseline = _seed(db_session)
    scenario, _decision = service.create_value_scenario(
        db_session,
        workspace_id=workspace.id,
        system_id=system.id,
        source_run_id=baseline.id,
        objective="objective",
        title="title",
        rationale={},
        actor="owner",
        idempotency_key="workspace-global-key",
    )
    with pytest.raises(service.ValueLoopConflict) as caught:
        service.simulate_value_scenario(
            db_session,
            workspace_id=workspace.id,
            scenario_id=scenario.id,
            recommended_patch={"max_cost_per_decision": 5},
            actor="analyst",
            idempotency_key="workspace-global-key",
        )
    assert caught.value.code == "idempotency_conflict"
    assert db_session.query(ValueSimulation).count() == 0


def test_invalid_transition_claims_no_receipt_and_mutates_nothing(db_session):
    workspace, system, policy, baseline = _seed(db_session)
    scenario, _decision = _scenario(db_session, workspace, system, baseline)
    operation_count = db_session.query(ValueLoopOperation).count()

    with pytest.raises(service.ValueLoopConflict):
        service.act_value_scenario(
            db_session,
            workspace_id=workspace.id,
            scenario_id=scenario.id,
            actuator=ACTUATOR,
            patch={"max_cost_per_decision": 5},
            actor="operator",
            idempotency_key="invalid-act",
        )

    db_session.refresh(scenario)
    db_session.refresh(policy)
    assert scenario.status == "decision_proposed"
    assert policy.max_cost_per_decision == 8.0
    assert db_session.query(ValueLoopOperation).count() == operation_count
    assert db_session.query(ValueActionExecution).count() == 0


def test_scenario_cannot_advance_when_decision_changed_out_of_band(db_session):
    workspace, system, _policy, baseline = _seed(db_session)
    scenario, decision = _scenario(db_session, workspace, system, baseline)
    decision.status = "rejected"
    db_session.commit()
    operation_count = db_session.query(ValueLoopOperation).count()

    with pytest.raises(service.ValueLoopConflict, match="Decision is not proposed"):
        _simulation(db_session, workspace, scenario)
    assert db_session.query(ValueSimulation).count() == 0
    assert db_session.query(ValueLoopOperation).count() == operation_count


def test_audit_failure_rolls_back_policy_action_decision_and_receipt(db_session, monkeypatch):
    workspace, system, policy, baseline = _seed(db_session)
    scenario, _simulation_row, decision = _approved(db_session, workspace, system, baseline)
    operation_count = db_session.query(ValueLoopOperation).count()

    def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(service, "_audit", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        service.act_value_scenario(
            db_session,
            workspace_id=workspace.id,
            scenario_id=scenario.id,
            actuator=ACTUATOR,
            patch={"mandatory_hitl_if_confidence_below": 0.6},
            actor="operator",
            idempotency_key="audit-must-succeed",
        )

    policy = db_session.get(ControlPolicy, policy.id)
    scenario = db_session.get(ValueScenario, scenario.id)
    decision = db_session.get(Decision, decision.id)
    assert policy.mandatory_hitl_if_confidence_below == 0.45
    assert scenario.status == "approved"
    assert scenario.acted_at is None
    assert decision.status == "accepted"
    assert db_session.query(ValueActionExecution).count() == 0
    assert db_session.query(ValueLoopOperation).count() == operation_count


@pytest.mark.parametrize(
    ("seed_options", "expected_code"),
    [
        ({"membrane_allowed": False}, "actuator_not_allowed"),
        ({"actuator_enabled": False}, "actuator_not_configured"),
    ],
)
def test_simulation_requires_explicit_system_and_membrane_configuration(
    db_session, seed_options, expected_code
):
    workspace, system, _policy, baseline = _seed(db_session, **seed_options)
    scenario, _decision = _scenario(db_session, workspace, system, baseline)
    operation_count = db_session.query(ValueLoopOperation).count()

    with pytest.raises(service.ValueLoopConflict) as caught:
        _simulation(db_session, workspace, scenario)
    assert caught.value.code == expected_code
    assert db_session.query(ValueSimulation).count() == 0
    assert db_session.query(ValueLoopOperation).count() == operation_count


def test_simulation_fails_closed_while_membrane_is_shadow(db_session):
    workspace, system, policy, baseline = _seed(db_session)
    extra = dict(policy.extra or {})
    membrane = dict(extra["membrane_spec"])
    membrane["enforcement_mode"] = "shadow"
    extra["membrane_spec"] = membrane
    policy.extra = extra
    db_session.commit()
    scenario, _decision = _scenario(db_session, workspace, system, baseline)
    operation_count = db_session.query(ValueLoopOperation).count()

    with pytest.raises(service.ValueLoopConflict) as caught:
        _simulation(db_session, workspace, scenario)

    assert caught.value.code == "actuator_not_enforced"
    assert db_session.query(ValueSimulation).count() == 0
    assert db_session.query(ValueLoopOperation).count() == operation_count


def test_policy_must_be_system_scoped_and_patch_must_be_bounded(db_session):
    workspace, system, policy, baseline = _seed(db_session)
    scenario, _decision = _scenario(db_session, workspace, system, baseline)
    policy.target_id = "another-system"
    db_session.commit()
    with pytest.raises(service.ValueLoopConflict) as caught:
        _simulation(db_session, workspace, scenario)
    assert caught.value.code == "actuator_not_configured"

    policy.target_id = system.id
    db_session.commit()
    with pytest.raises(service.ValueLoopValidationError, match="outside"):
        _simulation(
            db_session,
            workspace,
            scenario,
            patch={"max_cost_per_decision": 500},
        )
    assert db_session.query(ValueSimulation).count() == 0


def test_action_must_exactly_match_approved_simulation(db_session):
    workspace, system, policy, baseline = _seed(db_session)
    scenario, _simulation_row, _decision = _approved(
        db_session,
        workspace,
        system,
        baseline,
        patch={"max_cost_per_decision": 5},
    )

    with pytest.raises(service.ValueLoopConflict) as caught:
        service.act_value_scenario(
            db_session,
            workspace_id=workspace.id,
            scenario_id=scenario.id,
            actuator=ACTUATOR,
            patch={"max_cost_per_decision": 4},
            actor="operator",
            idempotency_key="different-from-approved",
        )
    assert caught.value.code == "approved_action_mismatch"
    db_session.refresh(policy)
    db_session.refresh(scenario)
    assert policy.max_cost_per_decision == 8.0
    assert scenario.status == "approved"
    assert db_session.query(ValueActionExecution).count() == 0


def test_simulation_service_derives_all_evidence_from_system_contract(db_session):
    workspace, system, _policy, baseline = _seed(db_session)
    scenario, _decision = _scenario(db_session, workspace, system, baseline)

    simulation = _simulation(db_session, workspace, scenario)

    assert simulation.model == "system-steering:value-model-v1"
    assert simulation.confidence == 0.82
    assert simulation.assumptions["configured"] == [
        "Comparable 30-day run mix",
        "Stable request volume",
    ]
    assert simulation.projected_outcome == {
        "value": 125.0,
        "value_state": "available",
        "cost": 9.0,
        "cost_state": "available",
        "evidence_type": "simulation",
    }
    assert simulation.provenance["model_source"] == (
        "systems.settings.steering_model"
    )


def test_simulation_service_rejects_caller_supplied_evidence_contract(db_session):
    workspace, system, _policy, baseline = _seed(db_session)
    scenario, _decision = _scenario(db_session, workspace, system, baseline)
    forbidden = {
        "model",
        "assumptions",
        "projected_outcome",
        "provenance",
        "confidence",
    }

    assert forbidden.isdisjoint(inspect.signature(service.simulate_value_scenario).parameters)
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        service.simulate_value_scenario(
            db_session,
            workspace_id=workspace.id,
            scenario_id=scenario.id,
            recommended_patch={"mandatory_hitl_if_confidence_below": 0.6},
            actor="attacker@example.test",
            idempotency_key="direct-evidence-injection",
            model="attacker-model",
            assumptions={"trust": "caller"},
            projected_outcome={"value": 1_000_000},
            provenance={"source": "caller"},
            confidence=1.0,
        )
    assert db_session.query(ValueSimulation).count() == 0


def test_approval_pins_exact_canonical_simulation_contract(db_session):
    workspace, system, _policy, baseline = _seed(db_session)
    scenario, simulation, decision = _approved(
        db_session,
        workspace,
        system,
        baseline,
    )
    expected_snapshot, expected_sha256 = service._canonical_simulation_snapshot(
        simulation
    )

    assert scenario.approved_simulation_snapshot == expected_snapshot
    assert scenario.approved_simulation_content_sha256 == expected_sha256
    assert decision.impact_estimate["simulation_content_sha256"] == expected_sha256
    approval_audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "value_loop.scenario.approved")
        .one()
    )
    assert approval_audit.details["simulation_content_sha256"] == expected_sha256


@pytest.mark.parametrize(
    ("field", "mutated_value"),
    [
        ("model", "attacker-model"),
        ("assumptions", {"configured": ["attacker hypothesis"]}),
        (
            "projected_outcome",
            {"value": 999_999, "evidence_type": "simulation"},
        ),
        (
            "recommended_action",
            {
                "actuator": ACTUATOR,
                "patch": {"mandatory_hitl_if_confidence_below": 0.7},
            },
        ),
        ("provenance", {"source": "attacker"}),
        ("confidence", 1.0),
    ],
)
def test_act_fails_closed_when_approved_simulation_content_changes(
    db_session,
    field,
    mutated_value,
):
    workspace, system, policy, baseline = _seed(db_session)
    scenario, simulation, _decision = _approved(
        db_session,
        workspace,
        system,
        baseline,
    )
    operation_count = db_session.query(ValueLoopOperation).count()
    setattr(simulation, field, mutated_value)
    db_session.commit()

    submitted_patch = (
        {"mandatory_hitl_if_confidence_below": 0.7}
        if field == "recommended_action"
        else {"mandatory_hitl_if_confidence_below": 0.6}
    )
    with pytest.raises(service.ValueLoopConflict) as caught:
        service.act_value_scenario(
            db_session,
            workspace_id=workspace.id,
            scenario_id=scenario.id,
            actuator=ACTUATOR,
            patch=submitted_patch,
            actor="operator@example.test",
            idempotency_key=f"mutated-simulation-{field}",
        )

    assert caught.value.code == "approved_simulation_changed"
    db_session.refresh(policy)
    db_session.refresh(scenario)
    assert policy.mandatory_hitl_if_confidence_below == 0.45
    assert scenario.status == "approved"
    assert db_session.query(ValueActionExecution).count() == 0
    assert db_session.query(ValueLoopOperation).count() == operation_count


def test_act_fails_closed_for_legacy_approval_without_contract_pin(db_session):
    workspace, system, policy, baseline = _seed(db_session)
    scenario, _simulation_row, _decision = _approved(
        db_session,
        workspace,
        system,
        baseline,
    )
    operation_count = db_session.query(ValueLoopOperation).count()
    scenario.approved_simulation_content_sha256 = None
    scenario.approved_simulation_snapshot = None
    db_session.commit()

    with pytest.raises(service.ValueLoopConflict) as caught:
        service.act_value_scenario(
            db_session,
            workspace_id=workspace.id,
            scenario_id=scenario.id,
            actuator=ACTUATOR,
            patch={"mandatory_hitl_if_confidence_below": 0.6},
            actor="operator@example.test",
            idempotency_key="legacy-unpinned-act",
        )

    assert caught.value.code == "approved_simulation_unpinned"
    db_session.refresh(policy)
    assert policy.mandatory_hitl_if_confidence_below == 0.45
    assert db_session.query(ValueActionExecution).count() == 0
    assert db_session.query(ValueLoopOperation).count() == operation_count


def test_actuator_updates_only_the_three_bounded_guardrails(db_session):
    workspace, system, policy, baseline = _seed(db_session)
    patch = {
        "max_cost_per_decision": 6,
        "max_latency_ms": 5_000,
        "mandatory_hitl_if_confidence_below": 0.65,
    }
    scenario, _simulation_row, _decision = _approved(
        db_session,
        workspace,
        system,
        baseline,
        patch=patch,
    )
    action = service.act_value_scenario(
        db_session,
        workspace_id=workspace.id,
        scenario_id=scenario.id,
        actuator=ACTUATOR,
        patch=patch,
        actor="operator",
        idempotency_key="all-bounded-fields",
    )
    db_session.refresh(policy)
    assert policy.max_cost_per_decision == 6
    assert policy.max_latency_ms == 5_000
    assert policy.mandatory_hitl_if_confidence_below == 0.65
    assert set(action.patch) == set(service.PATCH_FIELDS)


@pytest.mark.parametrize(
    "patch",
    [
        {"unbounded_field": 1},
        {"max_cost_per_decision": -1},
        {"max_latency_ms": float("inf")},
        {"mandatory_hitl_if_confidence_below": 1.1},
        {"max_cost_per_decision": True},
    ],
)
def test_guardrail_patch_rejects_unknown_unbounded_or_non_finite_values(db_session, patch):
    workspace, system, _policy, baseline = _seed(db_session)
    scenario, _decision = _scenario(db_session, workspace, system, baseline)
    with pytest.raises(service.ValueLoopValidationError):
        _simulation(db_session, workspace, scenario, patch=patch)
    assert db_session.query(ValueSimulation).count() == 0


def test_no_post_action_sample_is_explicit_not_measured_and_remains_acted(
    db_session,
):
    workspace, system, _policy, baseline = _seed(db_session)
    scenario, _simulation_row, _decision, _action = _acted(db_session, workspace, system, baseline)

    measurement = service.measure_value_scenario(
        db_session,
        workspace_id=workspace.id,
        scenario_id=scenario.id,
        actor="operator",
        idempotency_key="no-sample-yet",
    )

    db_session.refresh(scenario)
    assert measurement.status == "not_measured"
    assert measurement.reason == "no_comparable_post_action_run"
    assert measurement.source_run_id is None
    assert measurement.observed_outcome is None
    assert measurement.simulation_id == _simulation_row.id
    assert measurement.forecast_delta is None
    assert measurement.assumption_verdict == "not_evaluable"
    assert measurement.assumption_evaluation["reason"] == (
        "no_comparable_post_action_run"
    )
    assert scenario.status == "acted"
    assert scenario.measured_at is None


@pytest.mark.parametrize(
    ("source", "value"),
    [("unset", 100.0), ("auto", None)],
)
def test_scenario_rejects_a_completed_baseline_without_measured_value(
    db_session,
    source,
    value,
):
    workspace, system, _policy, baseline = _seed(
        db_session,
        baseline_source=source,
    )
    baseline.value_estimated = value
    db_session.commit()

    with pytest.raises(service.ValueLoopValidationError) as caught:
        _scenario(db_session, workspace, system, baseline)

    assert caught.value.code == "baseline_not_measured"
    assert db_session.query(ValueScenario).count() == 0
    assert db_session.query(ValueLoopOperation).count() == 0


@pytest.mark.parametrize(
    ("marker", "expected_code"),
    [
        ({"showcase_seed": True}, "baseline_run_is_synthetic_demo"),
        ({"lot8_value_loop_canary": True}, "baseline_run_is_canary_authored"),
    ],
)
def test_scenario_rejects_seed_and_canary_authored_baselines(
    db_session,
    marker,
    expected_code,
):
    workspace, system, _policy, baseline = _seed(db_session)
    baseline.input_ref = {**dict(baseline.input_ref or {}), **marker}
    db_session.commit()

    with pytest.raises(service.ValueLoopValidationError) as caught:
        _scenario(db_session, workspace, system, baseline)

    assert caught.value.code == expected_code
    assert db_session.query(ValueScenario).count() == 0
    assert db_session.query(ValueLoopOperation).count() == 0


def test_scenario_rejects_operator_baseline_even_with_server_override_receipt(
    db_session,
):
    workspace, system, _policy, baseline = _seed(
        db_session,
        baseline_source="operator",
    )
    baseline.value_estimated = 90.0
    apply_operator_override(
        baseline,
        value=100.0,
        note="operator-authored baseline",
    )
    record_operator_outcome_override(
        baseline,
        db=db_session,
        actor="operator@example.test",
        previous_value=90.0,
        note="operator-authored baseline",
    )
    db_session.commit()

    with pytest.raises(service.ValueLoopValidationError) as caught:
        _scenario(db_session, workspace, system, baseline)

    assert caught.value.code == "baseline_not_measured"
    assert db_session.query(ValueScenario).count() == 0


def test_scenario_rejects_client_shaped_self_signed_baseline_provenance(db_session):
    workspace, system, _policy, baseline = _seed(db_session)
    baseline.input_ref = {
        "measurement_provenance": {
            "source": "runtime_auto",
            "artifact_ref": "sha256:" + "f" * 64,
        }
    }
    db_session.commit()

    with pytest.raises(service.ValueLoopValidationError) as caught:
        _scenario(db_session, workspace, system, baseline)

    assert caught.value.code == "baseline_not_measured"
    assert db_session.query(ValueScenario).count() == 0


def test_scenario_persists_matching_runtime_auto_baseline_provenance(db_session):
    workspace, system, _policy, baseline = _seed(db_session)

    scenario, _decision = _scenario(db_session, workspace, system, baseline)

    provenance = scenario.baseline_outcome["measurement_provenance"]
    assert provenance == run_measurement_provenance(baseline, db=db_session)
    assert provenance["source"] == "runtime_auto"
    assert provenance["actor"] == "run_engine"
    assert provenance["artifact_ref"].startswith("sha256:")


def test_unset_values_never_become_measurements(db_session):
    workspace, system, _policy, baseline = _seed(db_session)
    scenario, _simulation_row, _decision, action = _acted(db_session, workspace, system, baseline)
    unset_run = _post_action_run(
        db_session,
        workspace,
        system,
        action,
        source="unset",
        value=999.0,
    )

    measurement = service.measure_value_scenario(
        db_session,
        workspace_id=workspace.id,
        scenario_id=scenario.id,
        source_run_id=unset_run.id,
        actor="operator",
        idempotency_key="unset-is-not-evidence",
    )
    db_session.refresh(scenario)
    assert measurement.status == "not_measured"
    assert measurement.reason == "post_action_value_not_measured"
    assert measurement.delta is None
    assert scenario.status == "acted"


def test_auto_measurement_discovery_skips_newer_unset_run(db_session):
    workspace, system, _policy, baseline = _seed(db_session)
    scenario, _simulation_row, _decision, action = _acted(db_session, workspace, system, baseline)
    measured_run = _post_action_run(
        db_session,
        workspace,
        system,
        action,
        source="auto",
        value=120.0,
    )
    unset_run = _post_action_run(
        db_session,
        workspace,
        system,
        action,
        source="unset",
        value=10_000.0,
    )
    unset_run.completed_at = measured_run.completed_at + timedelta(seconds=10)
    db_session.commit()

    measurement = service.measure_value_scenario(
        db_session,
        workspace_id=workspace.id,
        scenario_id=scenario.id,
        actor="operator",
        idempotency_key="discover-real-measurement",
    )
    assert measurement.status == "measured"
    assert measurement.source_run_id == measured_run.id
    assert measurement.source_run_id != unset_run.id
    assert measurement.delta["value"] == 20.0


def test_operator_measurement_without_server_receipt_stays_not_measured(db_session):
    workspace, system, _policy, baseline = _seed(db_session)
    scenario, _simulation_row, _decision, action = _acted(
        db_session,
        workspace,
        system,
        baseline,
    )
    observed = _post_action_run(
        db_session,
        workspace,
        system,
        action,
        source="operator",
    )

    measurement = service.measure_value_scenario(
        db_session,
        workspace_id=workspace.id,
        scenario_id=scenario.id,
        source_run_id=observed.id,
        actor="operator",
        idempotency_key="operator-without-receipt",
    )

    db_session.refresh(scenario)
    assert measurement.status == "not_measured"
    assert measurement.reason == "post_action_measurement_provenance_unavailable"
    assert measurement.observed_outcome is not None
    assert "measurement_provenance" not in measurement.observed_outcome
    assert scenario.status == "acted"


def test_operator_measurement_with_server_receipt_has_matching_provenance(db_session):
    workspace, system, _policy, baseline = _seed(db_session)
    scenario, _simulation_row, _decision, action = _acted(
        db_session,
        workspace,
        system,
        baseline,
    )
    observed = _post_action_run(
        db_session,
        workspace,
        system,
        action,
        source="operator",
    )
    observed.value_estimated = 120.0
    apply_operator_override(
        observed,
        value=130.0,
        note="independent post-action observation",
    )
    record_operator_outcome_override(
        observed,
        db=db_session,
        actor="operator@example.test",
        previous_value=120.0,
        note="independent post-action observation",
    )
    db_session.commit()

    measurement = service.measure_value_scenario(
        db_session,
        workspace_id=workspace.id,
        scenario_id=scenario.id,
        source_run_id=observed.id,
        actor="operator@example.test",
        idempotency_key="operator-with-server-receipt",
    )

    assert measurement.status == "measured"
    assert measurement.observed_outcome["value_source"] == "operator"
    assert measurement.observed_outcome["measurement_provenance"]["source"] == (
        "operator_override"
    )


def test_canary_authored_operator_outcome_is_never_independent_measurement(db_session):
    workspace, system, _policy, baseline = _seed(db_session)
    scenario, _simulation_row, _decision, action = _acted(
        db_session,
        workspace,
        system,
        baseline,
    )
    observed = _post_action_run(
        db_session,
        workspace,
        system,
        action,
        source="operator",
    )
    observed.input_ref = {
        **dict(observed.input_ref or {}),
        "lot8_value_loop_canary": True,
    }
    observed.value_estimated = 100.0
    apply_operator_override(
        observed,
        value=130.0,
        note="self-authored canary fallback",
    )
    record_operator_outcome_override(
        observed,
        db=db_session,
        actor="canary@example.test",
        previous_value=100.0,
        note="self-authored canary fallback",
    )
    db_session.commit()

    measurement = service.measure_value_scenario(
        db_session,
        workspace_id=workspace.id,
        scenario_id=scenario.id,
        source_run_id=observed.id,
        actor="canary@example.test",
        idempotency_key="canary-authored-operator-outcome",
    )

    db_session.refresh(scenario)
    assert measurement.status == "not_measured"
    assert measurement.reason == "canary_authored_outcome_is_not_independent"
    assert measurement.observed_outcome["measurement_provenance"]["source"] == (
        "operator_override"
    )
    assert scenario.status == "acted"


def test_pre_actuation_run_is_rejected_without_receipt(db_session):
    workspace, system, _policy, baseline = _seed(db_session)
    scenario, _simulation_row, _decision, _action = _acted(db_session, workspace, system, baseline)
    operation_count = db_session.query(ValueLoopOperation).count()

    with pytest.raises(service.ValueLoopValidationError, match="after actuation"):
        service.measure_value_scenario(
            db_session,
            workspace_id=workspace.id,
            scenario_id=scenario.id,
            source_run_id=baseline.id,
            actor="operator",
            idempotency_key="pre-action-is-invalid",
        )
    assert db_session.query(ValueLoopOperation).count() == operation_count
    assert db_session.query(ValueMeasurement).count() == 0


def test_post_action_run_with_stale_policy_digest_is_rejected_without_receipt(
    db_session,
):
    workspace, system, _policy, baseline = _seed(db_session)
    scenario, _simulation_row, _decision, action = _acted(
        db_session,
        workspace,
        system,
        baseline,
    )
    observed = _post_action_run(db_session, workspace, system, action)
    observed.input_ref = {
        "execution": {
            "control_policy": action.before_state["_control_policy"],
        }
    }
    db_session.commit()
    operation_count = db_session.query(ValueLoopOperation).count()

    with pytest.raises(
        service.ValueLoopValidationError,
        match="did not execute the post-actuation ControlPolicy",
    ):
        service.measure_value_scenario(
            db_session,
            workspace_id=workspace.id,
            scenario_id=scenario.id,
            source_run_id=observed.id,
            actor="operator",
            idempotency_key="stale-policy-is-invalid",
        )

    assert db_session.query(ValueLoopOperation).count() == operation_count
    assert db_session.query(ValueMeasurement).count() == 0


def test_baseline_must_be_completed_and_same_system(db_session):
    workspace, system, _policy, baseline = _seed(db_session)
    baseline.status = "running"
    baseline.completed_at = None
    db_session.commit()

    with pytest.raises(service.ValueLoopValidationError, match="must be completed"):
        _scenario(db_session, workspace, system, baseline)
    assert db_session.query(ValueScenario).count() == 0
    assert db_session.query(Decision).count() == 0


def test_explicit_measurement_run_is_scoped_before_use(db_session):
    workspace, system, _policy, baseline = _seed(db_session)
    scenario, _simulation_row, _decision, _action = _acted(
        db_session,
        workspace,
        system,
        baseline,
    )
    other_workspace, other_system, _other_policy, _other_baseline = _seed(db_session)
    foreign_run = Run(
        id=str(uuid4()),
        workspace_id=other_workspace.id,
        system_id=other_system.id,
        status="completed",
        started_at=datetime.utcnow() + timedelta(seconds=1),
        completed_at=datetime.utcnow() + timedelta(seconds=2),
        value_estimated=999.0,
        value_source="operator",
    )
    db_session.add(foreign_run)
    db_session.commit()

    with pytest.raises(service.ValueLoopNotFound, match="post-action Run not found"):
        service.measure_value_scenario(
            db_session,
            workspace_id=workspace.id,
            scenario_id=scenario.id,
            source_run_id=foreign_run.id,
            actor="operator",
            idempotency_key="foreign-run-is-never-read-as-evidence",
        )

    assert db_session.query(ValueMeasurement).count() == 0
    assert (
        db_session.query(ValueLoopOperation)
        .filter(ValueLoopOperation.idempotency_key == "foreign-run-is-never-read-as-evidence")
        .count()
        == 0
    )


def test_simulate_refreshes_stale_system_actuator_configuration(db_session):
    workspace, system, _policy, baseline = _seed(db_session)
    scenario, _decision = _scenario(db_session, workspace, system, baseline)
    assert system.settings["value_loop"]["actuators"][ACTUATOR]["enabled"] is True

    disabled = copy.deepcopy(system.settings)
    disabled["value_loop"]["actuators"][ACTUATOR]["enabled"] = False
    db_session.execute(
        update(System)
        .where(System.id == system.id)
        .values(settings=disabled)
        .execution_options(synchronize_session=False)
    )
    # The ORM object intentionally remains stale until the locking read.
    assert system.settings["value_loop"]["actuators"][ACTUATOR]["enabled"] is True

    with pytest.raises(service.ValueLoopConflict) as caught:
        _simulation(db_session, workspace, scenario)

    assert caught.value.code == "actuator_not_configured"
    assert db_session.query(ValueSimulation).count() == 0
    assert (
        db_session.query(ValueLoopOperation)
        .filter(ValueLoopOperation.operation == "simulate")
        .count()
        == 0
    )


def test_approve_refreshes_stale_membrane_policy(db_session):
    workspace, system, policy, baseline = _seed(db_session)
    scenario, _decision = _scenario(db_session, workspace, system, baseline)
    simulation = _simulation(db_session, workspace, scenario)
    assert ACTUATOR in policy.extra["membrane_spec"]["capabilities"]["allowed_actions"]

    denied = copy.deepcopy(policy.extra)
    denied["membrane_spec"]["capabilities"]["allowed_actions"] = []
    db_session.execute(
        update(ControlPolicy)
        .where(ControlPolicy.id == policy.id)
        .values(extra=denied)
        .execution_options(synchronize_session=False)
    )
    assert ACTUATOR in policy.extra["membrane_spec"]["capabilities"]["allowed_actions"]

    with pytest.raises(service.ValueLoopConflict) as caught:
        service.approve_value_scenario(
            db_session,
            workspace_id=workspace.id,
            scenario_id=scenario.id,
            simulation_id=simulation.id,
            actor="approver@example.test",
            idempotency_key="approve-after-stale-policy",
        )

    assert caught.value.code == "actuator_not_allowed"
    db_session.refresh(scenario)
    assert scenario.status == "simulated"
    assert (
        db_session.query(ValueLoopOperation)
        .filter(ValueLoopOperation.idempotency_key == "approve-after-stale-policy")
        .count()
        == 0
    )


def test_act_refreshes_stale_system_binding_and_uses_current_policy(db_session):
    workspace, system, original, baseline = _seed(db_session)
    scenario, _simulation_row, _decision = _approved(
        db_session,
        workspace,
        system,
        baseline,
    )
    replacement = ControlPolicy(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Replacement System guardrails",
        scope="system",
        target_id=system.id,
        max_cost_per_decision=8.0,
        max_latency_ms=8_000.0,
        mandatory_hitl_if_confidence_below=0.55,
        extra={"membrane_spec": _membrane()},
    )
    db_session.add(replacement)
    db_session.commit()
    assert system.control_policy_id == original.id

    db_session.execute(
        update(System)
        .where(System.id == system.id)
        .values(control_policy_id=replacement.id)
        .execution_options(synchronize_session=False)
    )
    assert system.control_policy_id == original.id

    action = service.act_value_scenario(
        db_session,
        workspace_id=workspace.id,
        scenario_id=scenario.id,
        actuator=ACTUATOR,
        patch={"mandatory_hitl_if_confidence_below": 0.6},
        actor="operator@example.test",
        idempotency_key="act-after-current-binding-refresh",
    )

    db_session.refresh(original)
    db_session.refresh(replacement)
    assert action.control_policy_id == replacement.id
    assert action.before_state["mandatory_hitl_if_confidence_below"] == 0.55
    assert original.mandatory_hitl_if_confidence_below == 0.45
    assert replacement.mandatory_hitl_if_confidence_below == 0.6


def test_measure_refreshes_policy_and_rejects_post_action_drift(db_session):
    workspace, system, policy, baseline = _seed(db_session)
    scenario, _simulation_row, _decision, action = _acted(
        db_session,
        workspace,
        system,
        baseline,
    )
    observed = _post_action_run(db_session, workspace, system, action)
    assert policy.mandatory_hitl_if_confidence_below == 0.6

    db_session.execute(
        update(ControlPolicy)
        .where(ControlPolicy.id == policy.id)
        .values(mandatory_hitl_if_confidence_below=0.61)
        .execution_options(synchronize_session=False)
    )
    assert policy.mandatory_hitl_if_confidence_below == 0.6

    with pytest.raises(service.ValueLoopConflict) as caught:
        service.measure_value_scenario(
            db_session,
            workspace_id=workspace.id,
            scenario_id=scenario.id,
            source_run_id=observed.id,
            actor="operator@example.test",
            idempotency_key="measure-after-current-policy-drift",
        )

    assert caught.value.code == "control_policy_changed"
    assert db_session.query(ValueMeasurement).count() == 0
    assert (
        db_session.query(ValueLoopOperation)
        .filter(
            ValueLoopOperation.idempotency_key
            == "measure-after-current-policy-drift"
        )
        .count()
        == 0
    )


def test_completed_idempotent_act_replays_after_policy_binding_removal(db_session):
    workspace, system, _policy, baseline = _seed(db_session)
    scenario, _simulation_row, _decision = _approved(
        db_session,
        workspace,
        system,
        baseline,
    )
    kwargs = {
        "workspace_id": workspace.id,
        "scenario_id": scenario.id,
        "actuator": ACTUATOR,
        "patch": {"mandatory_hitl_if_confidence_below": 0.6},
        "actor": "operator@example.test",
        "idempotency_key": "act-replay-after-authority-removal",
    }
    first = service.act_value_scenario(db_session, **kwargs)
    db_session.execute(
        update(System)
        .where(System.id == system.id)
        .values(control_policy_id=None)
        .execution_options(synchronize_session=False)
    )

    replay = service.act_value_scenario(db_session, **kwargs)

    assert replay.id == first.id
    assert (
        db_session.query(ValueActionExecution)
        .filter(ValueActionExecution.scenario_id == scenario.id)
        .count()
        == 1
    )


def test_simulate_acquires_authority_before_aggregate_rows(db_session, monkeypatch):
    workspace, system, _policy, baseline = _seed(db_session)
    scenario, _decision = _scenario(db_session, workspace, system, baseline)
    calls: list[str] = []

    def wrap(name, function):
        def _wrapped(*args, **kwargs):
            calls.append(name)
            return function(*args, **kwargs)

        return _wrapped

    monkeypatch.setattr(
        service,
        "_workspace_for_update",
        wrap("workspace", service._workspace_for_update),
    )
    monkeypatch.setattr(
        service,
        "_system_for_update",
        wrap("system", service._system_for_update),
    )
    monkeypatch.setattr(
        service,
        "_control_policy_for_update",
        wrap("policy", service._control_policy_for_update),
    )
    monkeypatch.setattr(
        service,
        "_scenario_for_update",
        wrap("scenario", service._scenario_for_update),
    )

    _simulation(db_session, workspace, scenario)

    assert calls[:4] == ["workspace", "system", "policy", "scenario"]
