"""Safety contract for the structural Lot 8 Showcase rollout."""
from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.api.v1.endpoints import hypervisor
from app.core.config import settings as app_settings
from app.models.audit import AuditLog
from app.models.policy import ControlPolicy
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.value_loop import ValueActionExecution, ValueMeasurement, ValueScenario
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember
from app.services import value_loop as value_service
from app.services.control_policy_snapshot import control_policy_execution_contract
from app.services.outcome.derive import apply_operator_override
from app.services.run_outcome_provenance import (
    record_operator_outcome_override,
    record_runtime_auto_outcome,
    run_measurement_provenance,
)
from app.services.value_loop_gate import value_loop_enabled
from scripts import collect_value_loop_evidence as collector
from scripts import rollout_value_loop as rollout

REVISION = "a" * 40
ACTUATOR = value_service.CONTROL_POLICY_GUARDRAILS_PATCH_V1


def _trusted_runner(
    *,
    revision: str = REVISION,
    pipeline_id: str = "pipeline-1",
    job_id: str = "job-1",
) -> dict:
    return {
        "issuer": "https://gitlab.example.test",
        "project_id": "42",
        "pipeline_id": pipeline_id,
        "job_id": job_id,
        "commit_sha": revision,
        "ref": "demo/agentic",
        "ref_protected": True,
    }


def _membrane(*, mode: str = "shadow", allowed: bool = False) -> dict:
    return {
        "version": 2,
        "enforcement_mode": mode,
        "inbound": {},
        "outbound": {},
        "capabilities": {
            "allowed_skills": [],
            "allowed_models": [],
            "allowed_delegations": [],
            "allowed_actions": [ACTUATOR] if allowed else [],
        },
        "provenance": {},
        "valves": {},
    }


def _steering_model() -> dict:
    return {
        "version": "value-model-v1",
        "confidence": 0.82,
        "assumptions": ["Comparable 30-day run mix"],
        "forecasts": {
            "mandatory_hitl_if_confidence_below": [
                {
                    "minimum": 0,
                    "maximum": 1,
                    "include_maximum": True,
                    "cost_multiplier": 0.9,
                    "value_multiplier": 1.25,
                }
            ]
        },
    }


def _seed_target(db, *, marker: str = rollout.SYSTEM360_MARKER_KEY):
    workspace = Workspace(
        id=str(uuid4()),
        name="Structurally selected Workspace",
        slug=f"opaque-{uuid4()}",
        settings={"features": {rollout.FEATURE_KEY: False}},
    )
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="No rollout identity in this name",
        objective="Exercise a governed value loop",
        status="active",
        settings={
            "experience": {marker: rollout.CANARY_MARKER_VALUE},
            "steering_model": _steering_model(),
        },
    )
    policy = ControlPolicy(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="System policy",
        scope="system",
        target_id=system.id,
        max_cost_per_decision=8,
        max_latency_ms=8_000,
        mandatory_hitl_if_confidence_below=0.45,
        extra={"membrane_spec": _membrane()},
    )
    authorization = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=1,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {
                    action: "shadow"
                    for action in rollout.REQUIRED_VALUE_LOOP_AUTHORIZATION_ACTIONS
                },
            }
        },
    )
    system.control_policy_id = policy.id
    baseline = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        status="completed",
        started_at=datetime.utcnow() - timedelta(hours=2),
        completed_at=datetime.utcnow() - timedelta(hours=1),
        decision="allow",
        confidence=0.7,
        value_estimated=100,
        cost_internal=10,
        efficiency=1,
        value_source="auto",
        input_ref={
            "execution": {
                "control_policy": control_policy_execution_contract(policy),
                "flow_sha256": "b" * 64,
                "runtime_revision": REVISION,
            }
        },
    )
    db.add_all([workspace, system, policy, authorization, baseline])
    db.flush()
    db.info["attest_value_loop_authorization"](
        authorization,
        rollout.REQUIRED_VALUE_LOOP_AUTHORIZATION_ACTIONS,
    )
    db.commit()
    return workspace, system, policy, baseline


def _add_target(db, workspace: Workspace):
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name=f"Opaque target {uuid4()}",
        objective="Exercise another governed value loop",
        status="active",
        settings={"steering_model": _steering_model()},
    )
    policy = ControlPolicy(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Additional System policy",
        scope="system",
        target_id=system.id,
        max_cost_per_decision=8,
        max_latency_ms=8_000,
        mandatory_hitl_if_confidence_below=0.45,
        extra={"membrane_spec": _membrane()},
    )
    system.control_policy_id = policy.id
    baseline = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        status="completed",
        started_at=datetime.utcnow() - timedelta(hours=2),
        completed_at=datetime.utcnow() - timedelta(hours=1),
        decision="allow",
        confidence=0.7,
        value_estimated=100,
        cost_internal=10,
        efficiency=1,
        value_source="auto",
        input_ref={
            "execution": {
                "control_policy": control_policy_execution_contract(policy),
                "flow_sha256": "b" * 64,
                "runtime_revision": REVISION,
            }
        },
    )
    db.add_all([system, policy, baseline])
    db.commit()
    return system, policy, baseline


def _activate_target(db, workspace, system, policy, baseline):
    prepared = rollout.prepare(
        db,
        workspace_id=workspace.id,
        system_id=system.id,
        apply=True,
        actor="operator@example.test",
    )
    assert prepared["system_id"] == system.id
    _enforce(policy, db)
    opened = rollout.open_canary_window(
        db,
        workspace_id=workspace.id,
        system_id=system.id,
        apply=True,
        actor="operator@example.test",
    )
    assert opened["proof_window"]["system_id"] == system.id
    records = _complete_loop(db, workspace, system, baseline)
    evidence = _evidence(workspace, system, records)
    rollout.activate(
        db,
        workspace_id=workspace.id,
        system_id=system.id,
        evidence=evidence,
        apply=True,
        actor="operator@example.test",
        trusted_runner=_trusted_runner(),
    )
    db.refresh(workspace)
    db.refresh(system)
    return records, evidence


def _portfolio_user(db, workspace: Workspace) -> User:
    user = User(
        id=str(uuid4()),
        username=f"portfolio-{uuid4()}",
        email=f"portfolio-{uuid4()}@example.test",
    )
    db.add_all(
        [
            user,
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=user.id,
                role="owner",
                role_template="workspace_owner",
            ),
        ]
    )
    db.commit()
    return user


def _enforce(policy: ControlPolicy, db) -> None:
    extra = copy.deepcopy(policy.extra)
    extra["membrane_spec"]["enforcement_mode"] = "enforce"
    policy.extra = extra
    db.commit()


def _complete_loop(
    db,
    workspace,
    system,
    baseline,
    *,
    baseline_started_at=None,
):
    # Protected evidence must start from a real Run executed inside the
    # active proof window. Refreshing this test fixture models that runtime
    # observation; the collector independently checks both timestamps and
    # the server-derived provenance copied into the scenario.
    baseline.started_at = baseline_started_at or datetime.now(UTC)
    baseline.completed_at = baseline.started_at
    policy = (
        db.query(ControlPolicy)
        .filter(
            ControlPolicy.id == system.control_policy_id,
            ControlPolicy.workspace_id == workspace.id,
            ControlPolicy.target_id == system.id,
        )
        .one()
    )
    input_ref = copy.deepcopy(baseline.input_ref)
    input_ref["execution"]["control_policy"] = control_policy_execution_contract(
        policy
    )
    baseline.input_ref = input_ref
    record_runtime_auto_outcome(baseline, db=db)
    db.commit()
    scenario, decision = value_service.create_value_scenario(
        db,
        workspace_id=workspace.id,
        system_id=system.id,
        source_run_id=baseline.id,
        objective="Improve value without weakening the control boundary",
        title="Tighten the confidence threshold",
        rationale={"source": "rollout-canary"},
        actor="owner@example.test",
        idempotency_key=f"create-{uuid4()}",
    )
    simulation = value_service.simulate_value_scenario(
        db,
        workspace_id=workspace.id,
        scenario_id=scenario.id,
        recommended_patch={"mandatory_hitl_if_confidence_below": 0.6},
        actor="analyst@example.test",
        idempotency_key=f"simulate-{uuid4()}",
    )
    value_service.approve_value_scenario(
        db,
        workspace_id=workspace.id,
        scenario_id=scenario.id,
        simulation_id=simulation.id,
        actor="approver@example.test",
        idempotency_key=f"approve-{uuid4()}",
    )
    action = value_service.act_value_scenario(
        db,
        workspace_id=workspace.id,
        scenario_id=scenario.id,
        actuator=ACTUATOR,
        patch={"mandatory_hitl_if_confidence_below": 0.6},
        actor="operator@example.test",
        idempotency_key=f"act-{uuid4()}",
    )
    observed = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        status="completed",
        started_at=action.executed_at + timedelta(seconds=1),
        completed_at=action.executed_at + timedelta(seconds=2),
        decision="allow",
        confidence=0.8,
        value_estimated=130,
        cost_internal=8,
        efficiency=1.3,
        value_source="auto",
        input_ref={
            "execution": {
                "control_policy": action.after_state["_control_policy"],
                "flow_sha256": "c" * 64,
                "runtime_revision": REVISION,
            }
        },
    )
    db.add(observed)
    db.commit()
    record_runtime_auto_outcome(observed, db=db)
    db.commit()
    measurement = value_service.measure_value_scenario(
        db,
        workspace_id=workspace.id,
        scenario_id=scenario.id,
        source_run_id=observed.id,
        actor="operator@example.test",
        idempotency_key=f"measure-{uuid4()}",
    )
    db.refresh(scenario)
    db.refresh(decision)
    return scenario, decision, simulation, action, measurement


def _evidence(workspace, system, records, *, revision: str = REVISION) -> dict:
    observation_ref = "sha256:" + "e" * 64
    source_junit = _playwright_junit()
    source_junit_sha256 = hashlib.sha256(source_junit).hexdigest()
    source_junit_ref = f"sha256:{source_junit_sha256}"
    properties = (
        f'<property name="revision" value="{revision}"/>'
        f'<property name="workspace_id" value="{workspace.id}"/>'
        f'<property name="system_id" value="{system.id}"/>'
        f'<property name="observation_ref" value="{observation_ref}"/>'
        f'<property name="source_junit_ref" value="{source_junit_ref}"/>'
    )
    cases = "".join(
        f'<testcase classname="lot8" name="{name}"/>' for name in rollout.REQUIRED_CHECKS
    )
    xml = (
        f'<testsuite name="{rollout.EVIDENCE_SUITE}" tests="8" failures="0" '
        f'errors="0" skipped="0"><properties>{properties}</properties>{cases}</testsuite>'
    ).encode()
    return {
        "schema_version": rollout.EVIDENCE_SCHEMA_VERSION,
        "kind": rollout.EVIDENCE_KIND,
        "revision": revision,
        "validated_at": datetime.now(UTC).isoformat(),
        "validated_by": "protected-runner",
        "observation_ref": observation_ref,
        "subject": {"workspace_id": workspace.id, "system_id": system.id},
        "records": {
            "scenario_id": records[0].id,
            "decision_id": records[1].id,
            "simulation_id": records[2].id,
            "action_execution_id": records[3].id,
            "measurement_id": records[4].id,
        },
        "checks": {name: True for name in rollout.REQUIRED_CHECKS},
        "trusted_runner": _trusted_runner(revision=revision),
        "source_junit": {
            "media_type": "application/junit+xml",
            "sha256": source_junit_sha256,
            "artifact_ref": source_junit_ref,
        },
        "runner_artifact": {
            "format": "junit_xml",
            "content_base64": base64.b64encode(xml).decode(),
            "artifact_ref": f"sha256:{hashlib.sha256(xml).hexdigest()}",
        },
    }


def _redacted_observation(
    workspace,
    system,
    baseline,
    records,
    *,
    protected: bool = True,
    measured: bool = True,
) -> dict:
    def digest(value):
        return hashlib.sha256(str(value).encode()).hexdigest()

    return {
        "schema_version": collector.OBSERVATION_SCHEMA_VERSION,
        "kind": collector.OBSERVATION_KIND,
        "claim": collector.OBSERVATION_CLAIM,
        "status": (
            "behavior_observed"
            if protected and measured
            else "runner_verified" if measured else "not_promotable"
        ),
        "promotion_eligible": protected and measured,
        "non_promotable_reason": (
            None if protected and measured else "runner_not_protected" if measured else "not_measured"
        ),
        "tested_revision": REVISION,
        "runner": {
            "protected_ci": protected,
            "pipeline_id": "pipeline-1" if protected else None,
            "job_id": "job-1" if protected else None,
        },
        "contract_sha256": "f" * 64,
        "target": {
            "workspace_sha256": digest(workspace.id),
            "system_sha256": digest(system.id),
            "baseline_run_sha256": digest(baseline.id),
        },
        "operations": {
            "scenario_sha256": digest(records[0].id),
            "decision_sha256": digest(records[1].id),
            "simulation_sha256": digest(records[2].id),
            "action_sha256": digest(records[3].id),
            "measurement_sha256": digest(records[4].id),
            "observed_run_sha256": (
                digest(records[4].source_run_id) if measured else None
            ),
            "measurement_status": "measured" if measured else "not_measured",
        },
        "checks": {
            name: measured if name == "measure" else True
            for name in rollout.REQUIRED_CHECKS
        },
        "diagnostics": {"ui_steer_projection": True},
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _playwright_junit() -> bytes:
    return (
        '<testsuite tests="1" failures="0" errors="0" skipped="0">'
        f'<testcase classname="13-lot8-value-loop-canary.spec.ts" '
        f'name="{collector.CANARY_TEST_NAME}"/>'
        "</testsuite>"
    ).encode()


@pytest.fixture(autouse=True)
def _fixed_runtime_revision(
    monkeypatch,
    db_session,
    attest_authorization_v2,
):
    db_session.info["attest_value_loop_authorization"] = attest_authorization_v2
    monkeypatch.setattr(rollout, "_runtime_revision", lambda: REVISION)
    monkeypatch.setattr(app_settings, "agentium_image_revision", REVISION)
    monkeypatch.setattr(
        app_settings,
        "authorization_v2_trusted_oidc_issuer",
        "https://gitlab.example.test",
    )
    monkeypatch.setattr(app_settings, "authorization_v2_trusted_project_id", "42")
    monkeypatch.setattr(app_settings, "authorization_v2_trusted_ref", "demo/agentic")


def test_prepare_dry_run_derives_marker_without_mutation_and_is_idempotent(db_session):
    workspace, system, policy, _baseline = _seed_target(db_session)
    before_workspace = copy.deepcopy(workspace.settings)
    before_system = copy.deepcopy(system.settings)
    before_policy = copy.deepcopy(policy.extra)
    before_audits = db_session.query(AuditLog).count()

    preview = rollout.prepare(
        db_session,
        workspace_id=workspace.id,
        apply=False,
        actor="",
    )
    assert preview["operation"] == "dry_run"
    assert preview["changed"] is True
    assert workspace.settings == before_workspace
    assert system.settings == before_system
    assert policy.extra == before_policy
    assert db_session.query(AuditLog).count() == before_audits

    applied = rollout.prepare(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    db_session.refresh(workspace)
    db_session.refresh(system)
    db_session.refresh(policy)
    assert applied["changed"] is True
    assert rollout._experience(system)[rollout.CANARY_MARKER_KEY] == "v1"
    assert rollout._actuator_config(system) == rollout._canonical_actuator_config()
    assert ACTUATOR in rollout._membrane(policy)[1].capabilities.allowed_actions
    assert workspace.settings["features"][rollout.FEATURE_KEY] is False
    assert db_session.query(AuditLog).filter_by(event_type="lot8.value_loop.prepared").count() == 1

    repeated = rollout.prepare(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    assert repeated["changed"] is False
    assert db_session.query(AuditLog).filter_by(event_type="lot8.value_loop.prepared").count() == 1


def test_canary_and_activation_require_attested_authorization_enforce(db_session):
    workspace, system, policy, baseline = _seed_target(db_session)
    rollout.prepare(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    _enforce(policy, db_session)
    config = (
        db_session.query(WorkspaceIAMConfig)
        .filter_by(workspace_id=workspace.id)
        .one()
    )

    payload = copy.deepcopy(config.capability_overrides)
    payload["authorization_v2"]["modes"]["value_scenario.act"] = "shadow"
    config.capability_overrides = payload
    db_session.commit()
    with pytest.raises(
        rollout.ValueLoopRolloutError,
        match=r"value_scenario\.act=shadow",
    ):
        rollout.open_canary_window(
            db_session,
            workspace_id=workspace.id,
            apply=True,
            actor="operator@example.test",
        )
    assert workspace.settings["features"][rollout.FEATURE_KEY] is False

    db_session.info["attest_value_loop_authorization"](
        config,
        rollout.REQUIRED_VALUE_LOOP_AUTHORIZATION_ACTIONS,
    )
    db_session.commit()
    rollout.open_canary_window(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    records = _complete_loop(db_session, workspace, system, baseline)
    evidence = _evidence(workspace, system, records)

    payload = copy.deepcopy(config.capability_overrides)
    payload["authorization_v2"]["modes"]["control_policy.admin"] = "shadow"
    config.capability_overrides = payload
    db_session.commit()
    assert value_loop_enabled(db_session, workspace=workspace, system=system) is False
    with pytest.raises(
        rollout.ValueLoopRolloutError,
        match=r"control_policy\.admin=shadow",
    ):
        rollout.activate(
            db_session,
            workspace_id=workspace.id,
            evidence=evidence,
            apply=True,
            actor="operator@example.test",
            trusted_runner=_trusted_runner(),
        )
    assert rollout._state(system)["activations"] == []


def test_protected_collector_resolves_redacted_observation_into_strict_evidence(
    db_session,
):
    workspace, system, policy, baseline = _seed_target(db_session)
    rollout.prepare(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    _enforce(policy, db_session)
    opened = rollout.open_canary_window(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    window = opened["proof_window"]
    assert window["policy_chain_ref"].startswith("sha256:")
    assert window["control_policy"]["policy_id"] == policy.id
    records = _complete_loop(db_session, workspace, system, baseline)
    db_session.refresh(system)
    transitions = rollout._state(system)["policy_transitions"]
    assert len(transitions) == 1
    assert transitions[0]["policy_chain_ref"] == window["policy_chain_ref"]
    assert transitions[0]["from"] == window["control_policy"]
    assert transitions[0]["to"] == records[3].after_state["_control_policy"]
    assert transitions[0]["request_sha256"] == records[3].request_sha256
    action_audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.id == transitions[0]["audit_id"])
        .one()
    )
    assert action_audit.event_type == "value_loop.action.executed"
    assert action_audit.details["action_execution_id"] == records[3].id
    observation = _redacted_observation(
        workspace,
        system,
        baseline,
        records,
    )
    serialized_observation = str(observation)
    assert all(row.id not in serialized_observation for row in records)
    assert baseline.id not in serialized_observation

    evidence = collector.collect_evidence(
        db_session,
        workspace_id=workspace.id,
        observation=observation,
        playwright_junit=_playwright_junit(),
        mode="protected",
        validated_by="protected-collector",
        trusted_runner=_trusted_runner(),
    )

    assert evidence["kind"] == rollout.EVIDENCE_KIND
    assert evidence["schema_version"] == rollout.EVIDENCE_SCHEMA_VERSION
    assert evidence["observation_ref"].startswith("sha256:")
    assert evidence["records"]["scenario_id"] == records[0].id
    assert evidence["trusted_runner"] == _trusted_runner()
    assert evidence["source_junit"]["sha256"] == hashlib.sha256(
        _playwright_junit()
    ).hexdigest()
    metadata = rollout.validate_evidence(
        db_session,
        evidence,
        workspace=workspace,
        system=system,
        revision=REVISION,
        lock_records=False,
    )
    assert metadata["observation_ref"] == evidence["observation_ref"]
    assert metadata["runner_test_count"] == len(rollout.REQUIRED_CHECKS)
    activated = rollout.activate(
        db_session,
        workspace_id=workspace.id,
        evidence=evidence,
        apply=True,
        actor="operator@example.test",
        trusted_runner=_trusted_runner(),
    )
    db_session.refresh(workspace)
    db_session.refresh(system)
    assert activated["changed"] is True
    assert workspace.settings["features"][rollout.FEATURE_KEY] is True
    state = rollout._state(system)
    assert state["proof_window"] is None
    assert state["activations"][0]["policy_chain_ref"] == window[
        "policy_chain_ref"
    ]
    assert state["activations"][0]["control_policy"] == window[
        "control_policy"
    ]
    assert value_loop_enabled(db_session, workspace=workspace, system=system) is True


@pytest.mark.parametrize(
    ("marker", "expected"),
    [
        ({"showcase_seed": True, "evidence_kind": "synthetic_demo"}, "synthetic_demo"),
        ({"lot8_value_loop_canary": True}, "canary_authored"),
    ],
)
def test_protected_collector_rejects_seed_or_canary_baseline(
    db_session,
    marker,
    expected,
):
    workspace, system, policy, baseline = _seed_target(db_session)
    rollout.prepare(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    _enforce(policy, db_session)
    rollout.open_canary_window(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    records = _complete_loop(db_session, workspace, system, baseline)
    baseline.input_ref = {**dict(baseline.input_ref or {}), **marker}
    db_session.commit()

    with pytest.raises(rollout.ValueLoopRolloutError, match=expected):
        collector.collect_evidence(
            db_session,
            workspace_id=workspace.id,
            observation=_redacted_observation(
                workspace,
                system,
                baseline,
                records,
            ),
            playwright_junit=_playwright_junit(),
            mode="protected",
            validated_by="protected-collector",
            trusted_runner=_trusted_runner(),
        )


def test_protected_collector_rejects_baseline_outside_proof_window(db_session):
    workspace, system, policy, baseline = _seed_target(db_session)
    rollout.prepare(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    _enforce(policy, db_session)
    opened = rollout.open_canary_window(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    opened_at = rollout._parse_utc(
        opened["proof_window"]["opened_at"],
        field="proof_window.opened_at",
    )
    records = _complete_loop(
        db_session,
        workspace,
        system,
        baseline,
        baseline_started_at=opened_at - timedelta(seconds=2),
    )

    with pytest.raises(
        rollout.ValueLoopRolloutError,
        match="not executed inside the active canary window",
    ):
        collector.collect_evidence(
            db_session,
            workspace_id=workspace.id,
            observation=_redacted_observation(
                workspace,
                system,
                baseline,
                records,
            ),
            playwright_junit=_playwright_junit(),
            mode="protected",
            validated_by="protected-collector",
            trusted_runner=_trusted_runner(),
        )
def test_runtime_rejects_sha_shaped_activation_without_authoritative_records_or_audit(
    db_session,
):
    workspace, system, policy, _baseline = _seed_target(db_session)
    rollout.prepare(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    _enforce(policy, db_session)
    window = rollout.open_canary_window(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )["proof_window"]
    assert value_loop_enabled(db_session, workspace=workspace, system=system) is True

    fake_records = {
        name: str(uuid4())
        for name in rollout.REQUIRED_RECORDS
    }
    fake_audit_id = str(uuid4())
    activation = {
        "evidence_ref": "sha256:" + "1" * 64,
        "artifact_ref": "sha256:" + "2" * 64,
        "runner_test_count": len(rollout.REQUIRED_CHECKS),
        "revision": REVISION,
        "validated_at": datetime.now(UTC).isoformat(),
        "validated_by": "forged-runner",
        "observation_ref": "sha256:" + "3" * 64,
        "trusted_runner": _trusted_runner(),
        "source_junit_ref": "sha256:" + "4" * 64,
        "records": fake_records,
        "checks": {name: True for name in rollout.REQUIRED_CHECKS},
        "system_id": system.id,
        "activated_at": datetime.now(UTC).isoformat(),
        "activated_by": "operator@example.test",
        "policy_chain_ref": window["policy_chain_ref"],
        "policy_chain_created_at": window["opened_at"],
        "control_policy": window["control_policy"],
        "audit_id": fake_audit_id,
    }
    state = rollout._state(system)
    state["proof_window"] = None
    state["activations"] = [activation]
    rollout._save_state(system, state)
    db_session.commit()

    # A shape-valid activation is not authority without its exact server audit.
    assert value_loop_enabled(db_session, workspace=workspace, system=system) is False

    # Even an exact-looking audit cannot promote identifiers that have no
    # persisted, tenant-bound Outcome -> Act -> Measure lineage.
    db_session.add(
        AuditLog(
            id=fake_audit_id,
            workspace_id=workspace.id,
            event_type="lot8.value_loop.activated",
            actor=activation["activated_by"],
            agent_id=system.id,
            details={
                "system_id": system.id,
                "revision": REVISION,
                "evidence_ref": activation["evidence_ref"],
                "artifact_ref": activation["artifact_ref"],
                "source_junit_ref": activation["source_junit_ref"],
                "observation_ref": activation["observation_ref"],
                "record_ids": fake_records,
                "claim_promoted": True,
            },
        )
    )
    db_session.commit()
    assert value_loop_enabled(db_session, workspace=workspace, system=system) is False


def test_runtime_rechecks_exact_activation_audit_and_current_runner_trust(
    db_session,
    monkeypatch,
):
    workspace, system, policy, baseline = _seed_target(db_session)
    rollout.prepare(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    _enforce(policy, db_session)
    records = _complete_loop(db_session, workspace, system, baseline)
    rollout.activate(
        db_session,
        workspace_id=workspace.id,
        evidence=_evidence(workspace, system, records),
        apply=True,
        actor="operator@example.test",
        trusted_runner=_trusted_runner(),
    )
    assert value_loop_enabled(db_session, workspace=workspace, system=system) is True

    monkeypatch.setattr(
        app_settings,
        "authorization_v2_trusted_ref",
        "different-protected-ref",
    )
    assert value_loop_enabled(db_session, workspace=workspace, system=system) is False
    monkeypatch.setattr(
        app_settings,
        "authorization_v2_trusted_ref",
        "demo/agentic",
    )

    activation = rollout._state(system)["activations"][-1]
    audit = db_session.query(AuditLog).filter_by(id=activation["audit_id"]).one()
    audit.details = {**audit.details, "runner_test_count": 1}
    db_session.commit()
    assert value_loop_enabled(db_session, workspace=workspace, system=system) is False


def test_runtime_requires_the_exact_canary_window_audit_receipt(db_session):
    workspace, system, policy, _baseline = _seed_target(db_session)
    rollout.prepare(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    _enforce(policy, db_session)
    rollout.open_canary_window(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    assert value_loop_enabled(db_session, workspace=workspace, system=system) is True

    state = rollout._state(system)
    forged_audit_id = str(uuid4())
    state["proof_window"]["audit_id"] = forged_audit_id
    rollout._save_state(system, state)
    db_session.add(
        AuditLog(
            id=forged_audit_id,
            workspace_id=workspace.id,
            event_type="lot8.value_loop.canary_window.opened",
            actor=state["proof_window"]["opened_by"],
            agent_id=system.id,
            details={
                "system_id": system.id,
                "revision": REVISION,
                "expires_at": state["proof_window"]["expires_at"],
                "claim_promoted": False,
                "policy_chain_ref": "sha256:" + "0" * 64,
            },
        )
    )
    db_session.commit()

    assert value_loop_enabled(db_session, workspace=workspace, system=system) is False


def test_runtime_rejects_policy_transition_without_persisted_act(db_session):
    workspace, system, policy, baseline = _seed_target(db_session)
    rollout.prepare(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    _enforce(policy, db_session)
    rollout.open_canary_window(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    records = _complete_loop(db_session, workspace, system, baseline)
    rollout.activate(
        db_session,
        workspace_id=workspace.id,
        evidence=_evidence(workspace, system, records),
        apply=True,
        actor="operator@example.test",
        trusted_runner=_trusted_runner(),
    )
    assert value_loop_enabled(db_session, workspace=workspace, system=system) is True

    db_session.refresh(policy)
    before = control_policy_execution_contract(policy)
    policy.max_cost_per_decision = float(policy.max_cost_per_decision or 0) + 1
    db_session.flush()
    after = control_policy_execution_contract(policy)
    state = rollout._state(system)
    active = state["activations"][-1]
    sequence = len(
        [
            row
            for row in state["policy_transitions"]
            if row.get("policy_chain_ref") == active["policy_chain_ref"]
        ]
    ) + 1
    state["policy_transitions"].append(
        {
            "policy_chain_ref": active["policy_chain_ref"],
            "sequence": sequence,
            "action_execution_id": str(uuid4()),
            "scenario_id": records[0].id,
            "from": before,
            "to": after,
            "transitioned_at": datetime.now(UTC).isoformat(),
            "actor": "operator@example.test",
        }
    )
    rollout._save_state(system, state)
    db_session.commit()

    assert value_loop_enabled(db_session, workspace=workspace, system=system) is False


@pytest.mark.parametrize(
    "mutation",
    [
        "audit_details",
        "audit_actor",
        "audit_workspace",
        "transition_request",
        "transition_action",
        "transition_actor",
    ],
)
def test_runtime_rejects_tampered_policy_transition_authority(
    db_session,
    mutation,
):
    workspace, system, policy, baseline = _seed_target(db_session)
    rollout.prepare(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    _enforce(policy, db_session)
    rollout.open_canary_window(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    _complete_loop(db_session, workspace, system, baseline)
    db_session.refresh(system)
    assert value_loop_enabled(db_session, workspace=workspace, system=system) is True

    state = rollout._state(system)
    transition = state["policy_transitions"][-1]
    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.id == transition["audit_id"])
        .one()
    )
    if mutation == "audit_details":
        audit.details = {**dict(audit.details), "unexpected": True}
    elif mutation == "audit_actor":
        audit.actor = "forged@example.test"
    elif mutation == "audit_workspace":
        foreign = Workspace(
            id=str(uuid4()),
            slug=f"foreign-transition-{uuid4().hex[:8]}",
            name="Foreign transition audit",
        )
        db_session.add(foreign)
        db_session.flush()
        audit.workspace_id = foreign.id
    elif mutation == "transition_request":
        transition["request_sha256"] = "f" * 64
        rollout._save_state(system, state)
    elif mutation == "transition_action":
        transition["action_execution_id"] = str(uuid4())
        rollout._save_state(system, state)
    else:
        transition["actor"] = "forged@example.test"
        rollout._save_state(system, state)
    db_session.commit()

    assert value_loop_enabled(db_session, workspace=workspace, system=system) is False


def test_collector_rejects_canary_authored_operator_measurement(db_session):
    workspace, system, policy, baseline = _seed_target(db_session)
    rollout.prepare(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    _enforce(policy, db_session)
    rollout.open_canary_window(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    records = _complete_loop(db_session, workspace, system, baseline)
    measurement = records[4]
    observed = db_session.query(Run).filter(Run.id == measurement.source_run_id).one()
    observed.value_source = "operator"
    observed.input_ref = {
        **dict(observed.input_ref or {}),
        "lot8_value_loop_canary": True,
    }
    observed.value_estimated = 100.0
    apply_operator_override(
        observed,
        value=130.0,
        note="self-authored fallback",
    )
    record_operator_outcome_override(
        observed,
        db=db_session,
        actor="canary@example.test",
        previous_value=100.0,
        note="self-authored fallback",
    )
    measured_outcome = dict(measurement.observed_outcome or {})
    measured_outcome["value_source"] = "operator"
    measured_outcome["measurement_provenance"] = run_measurement_provenance(
        observed,
        db=db_session,
    )
    measurement.observed_outcome = measured_outcome
    db_session.commit()

    observation = _redacted_observation(
        workspace,
        system,
        baseline,
        records,
    )
    with pytest.raises(
        rollout.ValueLoopRolloutError,
        match="canary-authored operator outcome",
    ):
        collector.collect_evidence(
            db_session,
            workspace_id=workspace.id,
            observation=observation,
            playwright_junit=_playwright_junit(),
            mode="protected",
            validated_by="protected-collector",
            trusted_runner=_trusted_runner(),
        )


def test_local_or_non_promotable_collection_never_emits_record_ids(db_session):
    workspace, system, policy, baseline = _seed_target(db_session)
    rollout.prepare(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    _enforce(policy, db_session)
    rollout.open_canary_window(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    records = _complete_loop(db_session, workspace, system, baseline)
    local_observation = _redacted_observation(
        workspace,
        system,
        baseline,
        records,
        protected=False,
    )

    local = collector.collect_evidence(
        db_session,
        workspace_id=workspace.id,
        observation=local_observation,
        playwright_junit=_playwright_junit(),
        mode="local",
        validated_by="",
    )
    assert local["status"] == "non_promotable"
    assert "records" not in local
    assert all(row.id not in str(local) for row in records)

    false_claim = copy.deepcopy(local_observation)
    false_claim["status"] = "not_promotable"
    false_claim["promotion_eligible"] = False
    false_claim["non_promotable_reason"] = "measurement_not_measured"
    protected = collector.collect_evidence(
        db_session,
        workspace_id=workspace.id,
        observation=false_claim,
        playwright_junit=_playwright_junit(),
        mode="protected",
        validated_by="protected-collector",
        trusted_runner=_trusted_runner(),
    )
    assert protected["status"] == "non_promotable"
    with pytest.raises(rollout.ValueLoopRolloutError):
        rollout.validate_evidence(
            db_session,
            protected,
            workspace=workspace,
            system=system,
            revision=REVISION,
            lock_records=False,
        )

@pytest.mark.parametrize("marker", [rollout.CANARY_MARKER_KEY, rollout.SYSTEM360_MARKER_KEY])
def test_discovery_fails_closed_on_ambiguous_structural_markers(db_session, marker):
    workspace, _system, _policy, _baseline = _seed_target(db_session, marker=marker)
    second = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Another opaque System",
        objective="Ambiguity must fail closed",
        status="active",
        settings={"experience": {marker: "v1"}},
    )
    db_session.add(second)
    db_session.commit()

    with pytest.raises(rollout.ValueLoopRolloutError, match="found 2"):
        rollout.prepare(
            db_session,
            workspace_id=workspace.id,
            apply=False,
            actor="",
        )


def test_activation_requires_enforce_and_rejects_invalid_evidence(db_session):
    workspace, system, policy, baseline = _seed_target(db_session)
    rollout.prepare(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    # Runtime simulation/action are fail-closed too: the proof exercise itself
    # must run under enforce, not merely switch modes at activation time.
    _enforce(policy, db_session)
    records = _complete_loop(db_session, workspace, system, baseline)
    evidence = _evidence(workspace, system, records)

    shadow = copy.deepcopy(policy.extra)
    shadow["membrane_spec"]["enforcement_mode"] = "shadow"
    policy.extra = shadow
    db_session.commit()

    with pytest.raises(rollout.ValueLoopRolloutError, match="requires MembraneSpec v2 enforce"):
        rollout.activate(
            db_session,
            workspace_id=workspace.id,
            evidence=evidence,
            apply=True,
            actor="operator@example.test",
        )
    _enforce(policy, db_session)

    wrong_revision = copy.deepcopy(evidence)
    wrong_revision["revision"] = "b" * 40
    with pytest.raises(rollout.ValueLoopRolloutError, match="revision differs"):
        rollout.activate(
            db_session,
            workspace_id=workspace.id,
            evidence=wrong_revision,
            apply=True,
            actor="operator@example.test",
        )

    failed_check = copy.deepcopy(evidence)
    failed_check["checks"]["tenant_isolation"] = False
    with pytest.raises(rollout.ValueLoopRolloutError, match="every required"):
        rollout.activate(
            db_session,
            workspace_id=workspace.id,
            evidence=failed_check,
            apply=True,
            actor="operator@example.test",
        )
    assert workspace.settings["features"][rollout.FEATURE_KEY] is False


def test_activation_rejects_cross_tenant_subject_and_records(db_session):
    workspace, system, policy, baseline = _seed_target(db_session)
    rollout.prepare(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    _enforce(policy, db_session)
    assert (
        rollout.prepare(
            db_session,
            workspace_id=workspace.id,
            apply=True,
            actor="operator@example.test",
        )["changed"]
        is False
    )
    db_session.refresh(policy)
    assert rollout._membrane(policy)[1].effective_mode.value == "enforce"
    records = _complete_loop(db_session, workspace, system, baseline)
    evidence = _evidence(workspace, system, records)
    other_workspace, other_system, _other_policy, _other_baseline = _seed_target(db_session)

    wrong_subject = copy.deepcopy(evidence)
    wrong_subject["subject"]["workspace_id"] = other_workspace.id
    with pytest.raises(rollout.ValueLoopRolloutError, match="subject differs"):
        rollout.activate(
            db_session,
            workspace_id=workspace.id,
            evidence=wrong_subject,
            apply=True,
            actor="operator@example.test",
        )

    wrong_record = copy.deepcopy(evidence)
    wrong_record["records"]["scenario_id"] = str(uuid4())
    with pytest.raises(rollout.ValueLoopRolloutError, match="does not belong"):
        rollout.activate(
            db_session,
            workspace_id=workspace.id,
            evidence=wrong_record,
            apply=True,
            actor="operator@example.test",
        )
    assert other_system.id != system.id
    assert workspace.settings["features"][rollout.FEATURE_KEY] is False


def test_activate_and_deactivate_are_attested_idempotent_and_additive(db_session):
    workspace, system, policy, baseline = _seed_target(db_session)
    rollout.prepare(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    _enforce(policy, db_session)
    records = _complete_loop(db_session, workspace, system, baseline)
    evidence = _evidence(workspace, system, records)
    before_counts = {
        "scenarios": db_session.query(ValueScenario).count(),
        "actions": db_session.query(ValueActionExecution).count(),
        "measurements": db_session.query(ValueMeasurement).count(),
    }

    preview = rollout.activate(
        db_session,
        workspace_id=workspace.id,
        evidence=evidence,
        apply=False,
        actor="",
    )
    assert preview["changed"] is True
    assert workspace.settings["features"][rollout.FEATURE_KEY] is False

    activated = rollout.activate(
        db_session,
        workspace_id=workspace.id,
        evidence=evidence,
        apply=True,
        actor="operator@example.test",
        trusted_runner=_trusted_runner(),
    )
    db_session.refresh(workspace)
    db_session.refresh(system)
    assert activated["validation"]["evidence_ref"].startswith("sha256:")
    assert workspace.settings["features"][rollout.FEATURE_KEY] is True
    state = rollout._state(system)
    assert len(state["activations"]) == 1
    assert "content_base64" not in str(state)
    assert state["activations"][0]["artifact_ref"] == evidence["runner_artifact"]["artifact_ref"]
    assert db_session.query(AuditLog).filter_by(event_type="lot8.value_loop.activated").count() == 1

    repeated = rollout.activate(
        db_session,
        workspace_id=workspace.id,
        evidence=evidence,
        apply=True,
        actor="operator@example.test",
        trusted_runner=_trusted_runner(),
    )
    assert repeated["changed"] is False
    assert len(rollout._state(system)["activations"]) == 1
    assert db_session.query(AuditLog).filter_by(event_type="lot8.value_loop.activated").count() == 1

    rollback_preview = rollout.deactivate(
        db_session,
        workspace_id=workspace.id,
        apply=False,
        actor="",
    )
    assert rollback_preview["changed"] is True
    assert workspace.settings["features"][rollout.FEATURE_KEY] is True

    rollout.deactivate(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    db_session.refresh(workspace)
    db_session.refresh(system)
    assert workspace.settings["features"][rollout.FEATURE_KEY] is False
    assert rollout._experience(system)[rollout.CANARY_MARKER_KEY] == "v1"
    assert rollout._actuator_config(system) == rollout._canonical_actuator_config()
    assert len(rollout._state(system)["activations"]) == 1
    assert len(rollout._state(system)["deactivations"]) == 1
    assert before_counts == {
        "scenarios": db_session.query(ValueScenario).count(),
        "actions": db_session.query(ValueActionExecution).count(),
        "measurements": db_session.query(ValueMeasurement).count(),
    }
    assert (
        db_session.query(AuditLog).filter_by(event_type="lot8.value_loop.deactivated").count() == 1
    )

    repeated_rollback = rollout.deactivate(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    assert repeated_rollback["changed"] is False
    assert len(rollout._state(system)["deactivations"]) == 1

    # A generic settings write cannot resurrect evidence that an explicit
    # deactivation has superseded.
    rollout._set_feature(workspace, True)
    db_session.commit()
    assert value_loop_enabled(db_session, workspace=workspace, system=system) is False

    rollout._set_feature(workspace, False)
    db_session.commit()
    reactivated = rollout.activate(
        db_session,
        workspace_id=workspace.id,
        evidence=evidence,
        apply=True,
        actor="operator@example.test",
        trusted_runner=_trusted_runner(),
    )
    db_session.refresh(workspace)
    db_session.refresh(system)
    assert reactivated["changed"] is True
    assert len(rollout._state(system)["activations"]) == 2
    assert value_loop_enabled(db_session, workspace=workspace, system=system) is True


def test_activation_audit_failure_rolls_back_feature_and_evidence(db_session, monkeypatch):
    workspace, system, policy, baseline = _seed_target(db_session)
    rollout.prepare(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    _enforce(policy, db_session)
    evidence = _evidence(workspace, system, _complete_loop(db_session, workspace, system, baseline))
    monkeypatch.setattr(rollout, "emit_audit_event", lambda **_kwargs: None)

    with pytest.raises(rollout.ValueLoopRolloutError, match="mandatory rollout audit"):
        rollout.activate(
            db_session,
            workspace_id=workspace.id,
            evidence=evidence,
            apply=True,
            actor="operator@example.test",
            trusted_runner=_trusted_runner(),
        )
    db_session.refresh(workspace)
    db_session.refresh(system)
    assert workspace.settings["features"][rollout.FEATURE_KEY] is False
    assert rollout._state(system)["activations"] == []


def test_activation_requires_same_oidc_job_and_source_junit_binding(db_session):
    workspace, system, policy, baseline = _seed_target(db_session)
    rollout.prepare(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    _enforce(policy, db_session)
    evidence = _evidence(
        workspace,
        system,
        _complete_loop(db_session, workspace, system, baseline),
    )

    # Structural/trust-anchor validation remains available to an operator as a
    # dry-run, but no local process may perform the activation.
    assert rollout.activate(
        db_session,
        workspace_id=workspace.id,
        evidence=evidence,
        apply=False,
        actor="",
    )["validation"]["trusted_runner"] == _trusted_runner()
    with pytest.raises(rollout.ValueLoopRolloutError, match="protected GitLab OIDC runner"):
        rollout.activate(
            db_session,
            workspace_id=workspace.id,
            evidence=evidence,
            apply=True,
            actor="operator@example.test",
        )
    with pytest.raises(rollout.ValueLoopRolloutError, match="same protected GitLab job"):
        rollout.activate(
            db_session,
            workspace_id=workspace.id,
            evidence=evidence,
            apply=True,
            actor="operator@example.test",
            trusted_runner=_trusted_runner(job_id="job-2"),
        )

    tampered = copy.deepcopy(evidence)
    tampered["source_junit"]["sha256"] = "9" * 64
    tampered["source_junit"]["artifact_ref"] = "sha256:" + "9" * 64
    with pytest.raises(rollout.ValueLoopRolloutError, match="properties differ"):
        rollout.activate(
            db_session,
            workspace_id=workspace.id,
            evidence=tampered,
            apply=False,
            actor="",
        )
    assert workspace.settings["features"][rollout.FEATURE_KEY] is False


def test_two_attested_systems_are_aggregated_and_tampered_receipt_is_excluded(
    db_session,
):
    workspace, first, first_policy, first_baseline = _seed_target(db_session)
    second, second_policy, second_baseline = _add_target(db_session, workspace)
    user = _portfolio_user(db_session, workspace)

    _activate_target(
        db_session,
        workspace,
        first,
        first_policy,
        first_baseline,
    )
    _activate_target(
        db_session,
        workspace,
        second,
        second_policy,
        second_baseline,
    )

    db_session.refresh(first)
    db_session.refresh(second)
    assert rollout._marker_matches(first, rollout.CANARY_MARKER_KEY) is False
    assert rollout._marker_matches(second, rollout.CANARY_MARKER_KEY) is True
    assert value_loop_enabled(db_session, workspace=workspace, system=first) is True
    assert value_loop_enabled(db_session, workspace=workspace, system=second) is True

    portfolio = asyncio.run(
        hypervisor.portfolio_value_loop(
            workspace=workspace,
            user=user,
            db=db_session,
        )
    )
    assert {row["system_id"] for row in portfolio["systems"]} == {
        first.id,
        second.id,
    }

    state = rollout._state(second)
    state["activations"][-1]["audit_id"] = str(uuid4())
    rollout._save_state(second, state)
    db_session.commit()
    assert value_loop_enabled(db_session, workspace=workspace, system=second) is False

    portfolio = asyncio.run(
        hypervisor.portfolio_value_loop(
            workspace=workspace,
            user=user,
            db=db_session,
        )
    )
    assert [row["system_id"] for row in portfolio["systems"]] == [first.id]
    assert all(
        row["system_id"] == first.id
        for row in portfolio["scenarios"]["items"]
    )


def test_proof_window_is_unique_across_targeted_systems(db_session):
    workspace, first, first_policy, first_baseline = _seed_target(db_session)
    second, second_policy, _second_baseline = _add_target(db_session, workspace)
    third, _third_policy, _third_baseline = _add_target(db_session, workspace)

    _activate_target(
        db_session,
        workspace,
        first,
        first_policy,
        first_baseline,
    )
    preview = rollout.prepare(
        db_session,
        workspace_id=workspace.id,
        system_id=second.id,
        apply=False,
        actor="",
    )
    assert preview["previous_canary_system_ids"] == [first.id]
    assert rollout._marker_matches(first, rollout.CANARY_MARKER_KEY) is True
    assert rollout._marker_matches(second, rollout.CANARY_MARKER_KEY) is False

    rollout.prepare(
        db_session,
        workspace_id=workspace.id,
        system_id=second.id,
        apply=True,
        actor="operator@example.test",
    )
    marker_audit = (
        db_session.query(AuditLog)
        .filter_by(event_type="lot8.value_loop.prepared", agent_id=second.id)
        .one()
    )
    assert marker_audit.details["previous_canary_system_ids"] == [first.id]
    _enforce(second_policy, db_session)
    rollout.open_canary_window(
        db_session,
        workspace_id=workspace.id,
        system_id=second.id,
        apply=True,
        actor="operator@example.test",
    )

    with pytest.raises(
        rollout.ValueLoopRolloutError,
        match="another proof window is open",
    ):
        rollout.prepare(
            db_session,
            workspace_id=workspace.id,
            system_id=third.id,
            apply=False,
            actor="",
        )
    db_session.refresh(second)
    db_session.refresh(third)
    assert rollout._marker_matches(second, rollout.CANARY_MARKER_KEY) is True
    assert rollout._marker_matches(third, rollout.CANARY_MARKER_KEY) is False
    assert value_loop_enabled(db_session, workspace=workspace, system=first) is True
    assert value_loop_enabled(db_session, workspace=workspace, system=second) is True


def test_malformed_workspace_proof_state_fails_closed(db_session):
    workspace, system, policy, _baseline = _seed_target(db_session)
    other, _other_policy, _other_baseline = _add_target(db_session, workspace)
    rollout.prepare(
        db_session,
        workspace_id=workspace.id,
        system_id=system.id,
        apply=True,
        actor="operator@example.test",
    )
    _enforce(policy, db_session)
    rollout.open_canary_window(
        db_session,
        workspace_id=workspace.id,
        system_id=system.id,
        apply=True,
        actor="operator@example.test",
    )
    assert value_loop_enabled(db_session, workspace=workspace, system=system) is True

    malformed = rollout._state(other)
    malformed["proof_window"] = {
        "opened_at": "not-a-timestamp",
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    rollout._save_state(other, malformed)
    db_session.commit()

    assert value_loop_enabled(db_session, workspace=workspace, system=system) is False
    with pytest.raises(
        rollout.ValueLoopRolloutError,
        match="proof_window.opened_at must be ISO-8601",
    ):
        rollout.prepare(
            db_session,
            workspace_id=workspace.id,
            system_id=other.id,
            apply=False,
            actor="",
        )


def test_targeted_rollback_preserves_another_attested_system(db_session):
    workspace, first, first_policy, first_baseline = _seed_target(db_session)
    second, second_policy, second_baseline = _add_target(db_session, workspace)

    _activate_target(
        db_session,
        workspace,
        first,
        first_policy,
        first_baseline,
    )
    _activate_target(
        db_session,
        workspace,
        second,
        second_policy,
        second_baseline,
    )
    report = rollout.deactivate(
        db_session,
        workspace_id=workspace.id,
        system_id=first.id,
        apply=True,
        actor="operator@example.test",
    )
    db_session.refresh(workspace)
    db_session.refresh(first)
    db_session.refresh(second)

    assert report["changed"] is True
    assert report["workspace_feature_remains_enabled"] is True
    assert report["other_requested_system_ids"] == [second.id]
    assert workspace.settings["features"][rollout.FEATURE_KEY] is True
    assert value_loop_enabled(db_session, workspace=workspace, system=first) is False
    assert value_loop_enabled(db_session, workspace=workspace, system=second) is True
    assert len(rollout._state(first)["deactivations"]) == 1
    assert len(rollout._state(second)["deactivations"]) == 0
    assert rollout.status(
        db_session,
        workspace_id=workspace.id,
        system_id=first.id,
    )["runtime_gate_open"] is False
    assert rollout.status(
        db_session,
        workspace_id=workspace.id,
        system_id=second.id,
    )["runtime_gate_open"] is True


def test_explicit_rollout_target_is_tenant_scoped(db_session):
    workspace, system, _policy, _baseline = _seed_target(db_session)
    other_workspace, other_system, _other_policy, _other_baseline = _seed_target(
        db_session
    )
    before = copy.deepcopy(system.settings)
    other_before = copy.deepcopy(other_system.settings)

    with pytest.raises(
        rollout.ValueLoopRolloutError,
        match="outside the Workspace",
    ):
        rollout.prepare(
            db_session,
            workspace_id=workspace.id,
            system_id=other_system.id,
            apply=False,
            actor="",
        )
    with pytest.raises(
        rollout.ValueLoopRolloutError,
        match="outside the Workspace",
    ):
        rollout.deactivate(
            db_session,
            workspace_id=workspace.id,
            system_id=other_system.id,
            apply=False,
            actor="",
        )

    assert workspace.id != other_workspace.id
    assert system.settings == before
    assert other_system.settings == other_before
