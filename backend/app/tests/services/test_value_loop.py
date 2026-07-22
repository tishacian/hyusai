"""Behavioral contract for the authoritative Lot-8 value loop."""
from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

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
from app.services.run_outcome_provenance import record_operator_outcome_override

ACTUATOR = service.CONTROL_POLICY_GUARDRAILS_PATCH_V1


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
        }
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
    )
    db.add_all([workspace, policy, system, baseline])
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
        model="value-model-v1",
        assumptions={"window_days": 30, "volume": 100},
        projected_outcome={"value": 125.0, "cost": 9.0},
        provenance={"model_version": "v1", "dataset": "run-ledger-30d"},
        confidence=0.82,
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
            }
        },
    )
    db.add(run)
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
    assert measurement.assumption_evaluation["declared_assumptions"] == {
        "window_days": 30,
        "volume": 100,
    }
    assert db_session.query(ValueSimulation).count() == 1
    assert db_session.query(ValueMeasurement).count() == 1
    assert [
        row.event_type
        for row in db_session.query(AuditLog)
        .filter(AuditLog.workspace_id == workspace.id)
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
            model="v1",
            assumptions={},
            projected_outcome={"value": 1},
            provenance={"source": "test"},
            confidence=0.8,
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
    record_operator_outcome_override(
        observed,
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
