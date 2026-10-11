"""API contract for the System-scoped Lot 8 value loop."""
from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.api.v1.endpoints import hypervisor, value_loop
from app.core.config import settings as app_settings
from app.models.audit import AuditLog
from app.models.policy import ControlPolicy
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.value_loop import (
    ValueActionExecution,
    ValueLoopOperation,
    ValueScenario,
    ValueSimulation,
)
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember
from app.services import value_loop_gate
from app.services.control_policy_snapshot import control_policy_execution_contract
from app.services.iam.decision_plane import AuthorizationMode, resolve_mode
from app.services.run_outcome_provenance import record_runtime_auto_outcome
from app.services.value_loop import CONTROL_POLICY_GUARDRAILS_PATCH_V1
from app.services.value_loop_gate import value_loop_policy_chain_reference

ACTUATOR = CONTROL_POLICY_GUARDRAILS_PATCH_V1
RUNTIME_REVISION = "a" * 40


@pytest.fixture(autouse=True)
def _runtime_rollout_authorization_is_pre_attested(monkeypatch):
    """Endpoint tests isolate action semantics from the rollout promotion gate.

    The real authorization-attestation gate is covered by the rollout service
    tests; this module varies individual actions after the feature is open.
    """

    monkeypatch.setattr(
        value_loop_gate,
        "value_loop_authorization_ready",
        lambda *_args, **_kwargs: True,
    )


def _seed(db_session):
    suffix = uuid4().hex[:8]
    workspace = Workspace(
        id=str(uuid4()),
        slug=f"value-loop-api-{suffix}",
        name="Value loop API",
        settings={"features": {"value_loop_v1": True}},
    )
    user = User(
        id=str(uuid4()),
        username=f"value-loop-{suffix}",
        email=f"value-loop-{suffix}@example.test",
    )
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        role_template="workspace_owner",
    )
    policy = ControlPolicy(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Value loop policy",
        scope="system",
        max_cost_per_decision=10.0,
        max_latency_ms=5_000.0,
        mandatory_hitl_if_confidence_below=0.4,
        extra={
            "membrane_spec": {
                "version": 2,
                "enforcement_mode": "enforce",
                "capabilities": {"allowed_actions": [ACTUATOR]},
            }
        },
    )
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Value loop canary",
        objective="Prove the value loop",
        status="active",
        control_policy_id=policy.id,
        settings={
            "experience": {"value_loop_canary": "v1"},
            "_lot8_value_loop_rollout_v1": {
                "schema_version": 1,
                "prepared": {
                    "system_id": "pending",
                    "contract_sha256": "f" * 64,
                },
                "proof_window": None,
                "activations": [],
                "deactivations": [],
                "policy_transitions": [],
            },
            "steering_model": {
                "version": "value-model-v1",
                "confidence": 0.8,
                "assumptions": ["Comparable 30-day run mix"],
                "forecasts": {
                    "max_cost_per_decision": [
                        {
                            "minimum": 0,
                            "maximum": 10,
                            "include_maximum": False,
                            "cost_multiplier": 0.9,
                            "value_multiplier": 1.05,
                        },
                        {
                            "minimum": 10,
                            "maximum": 50,
                            "include_maximum": True,
                            "cost_multiplier": 1.0,
                            "value_multiplier": 1.1,
                        },
                    ],
                    "max_latency_ms": [
                        {
                            "minimum": 100,
                            "maximum": 5_000,
                            "include_maximum": False,
                            "cost_multiplier": 1.1,
                            "value_multiplier": 1.1,
                        },
                        {
                            "minimum": 5_000,
                            "maximum": 30_000,
                            "include_maximum": True,
                            "cost_multiplier": 0.9,
                            "value_multiplier": 1.0,
                        },
                    ],
                    "mandatory_hitl_if_confidence_below": [
                        {
                            "minimum": 0,
                            "maximum": 0.5,
                            "include_maximum": False,
                            "cost_multiplier": 0.95,
                            "value_multiplier": 1.05,
                        },
                        {
                            "minimum": 0.5,
                            "maximum": 1,
                            "include_maximum": True,
                            "cost_multiplier": 1.1,
                            "value_multiplier": 1.25,
                        },
                    ],
                },
            },
            "value_loop": {
                "actuators": {
                    ACTUATOR: {
                        "enabled": True,
                        "fields": {
                            "max_cost_per_decision": {"min": 0, "max": 50},
                            "max_latency_ms": {"min": 100, "max": 30_000},
                            "mandatory_hitl_if_confidence_below": {"min": 0, "max": 1},
                        },
                    }
                }
            },
        },
    )
    policy.target_id = system.id
    rollout_state = system.settings["_lot8_value_loop_rollout_v1"]
    rollout_state["prepared"]["system_id"] = system.id
    policy_reference = control_policy_execution_contract(policy)
    opened_at = datetime.now(UTC)
    expires_at = opened_at + timedelta(hours=2)
    policy_chain_ref = value_loop_policy_chain_reference(
        system_id=system.id,
        revision=RUNTIME_REVISION,
        created_at=opened_at.isoformat(),
        control_policy=policy_reference,
    )
    audit_id = str(uuid4())
    rollout_state["proof_window"] = {
        "audit_id": audit_id,
        "system_id": system.id,
        "revision": RUNTIME_REVISION,
        "contract_sha256": rollout_state["prepared"]["contract_sha256"],
        "opened_at": opened_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "opened_by": "operator@example.test",
        "policy_chain_ref": policy_chain_ref,
        "control_policy": policy_reference,
    }
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
        value_source="auto",
        input_ref={
            "execution": {
                "control_policy": policy_reference,
                "flow_sha256": "b" * 64,
                "runtime_revision": RUNTIME_REVISION,
            }
        },
    )
    db_session.add_all(
        [
            workspace,
            user,
            member,
            policy,
            system,
            baseline,
            AuditLog(
                id=audit_id,
                workspace_id=workspace.id,
                event_type="lot8.value_loop.canary_window.opened",
                actor="operator@example.test",
                agent_id=system.id,
                details={
                    "system_id": system.id,
                    "revision": RUNTIME_REVISION,
                    "expires_at": expires_at.isoformat(),
                    "feature": "value_loop_v1",
                    "claim_promoted": False,
                    "policy_chain_ref": policy_chain_ref,
                    "control_policy_revision": policy_reference["revision"],
                    "control_policy_sha256": policy_reference["sha256"],
                },
            ),
        ]
    )
    db_session.commit()
    record_runtime_auto_outcome(baseline, db=db_session)
    db_session.commit()
    return workspace, user, system, policy, baseline


def _client(db_session, workspace, user) -> TestClient:
    app = FastAPI()
    app.include_router(value_loop.router, prefix="/systems")
    app.include_router(hypervisor.router, prefix="/hypervisor")
    app.dependency_overrides[value_loop.get_current_workspace] = lambda: workspace
    app.dependency_overrides[value_loop.get_current_user] = lambda: user
    app.dependency_overrides[value_loop.get_db] = lambda: db_session
    app.dependency_overrides[hypervisor.get_current_workspace] = lambda: workspace
    app.dependency_overrides[hypervisor.get_current_user] = lambda: user
    app.dependency_overrides[hypervisor.get_db] = lambda: db_session
    return TestClient(app)


def _set_contributor(db_session, workspace: Workspace, user: User) -> None:
    member = (
        db_session.query(WorkspaceMember)
        .filter_by(workspace_id=workspace.id, user_id=user.id)
        .one()
    )
    member.role = "member"
    member.role_template = "workspace_contributor"
    db_session.commit()


def _set_run_read_mode(
    db_session,
    *,
    workspace: Workspace,
    user: User,
    mode: str,
    attest_authorization_v2=None,
) -> WorkspaceIAMConfig:
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=1,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {"run.read": mode},
            }
        },
        updated_by_user_id=user.id,
    )
    db_session.add(config)
    db_session.commit()
    if mode == "enforce":
        assert attest_authorization_v2 is not None
        attest_authorization_v2(config, ["run.read"])
        db_session.commit()
    return config


def _set_decision_read_mode(
    db_session,
    *,
    workspace: Workspace,
    user: User,
    mode: str,
    attest_authorization_v2=None,
) -> WorkspaceIAMConfig:
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=1,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {"decision.read": mode},
            }
        },
        updated_by_user_id=user.id,
    )
    db_session.add(config)
    db_session.commit()
    if mode == "enforce" and attest_authorization_v2 is not None:
        attest_authorization_v2(config, ["decision.read"])
        db_session.commit()
    return config


def _set_member_role(
    db_session,
    *,
    workspace: Workspace,
    user: User,
    role: str,
    role_template: str,
) -> None:
    member = (
        db_session.query(WorkspaceMember)
        .filter_by(workspace_id=workspace.id, user_id=user.id)
        .one()
    )
    member.role = role
    member.role_template = role_template
    db_session.commit()


def _act_scenario(
    db_session,
    *,
    workspace: Workspace,
    user: User,
    system: System,
    baseline: Run,
    key: str,
) -> tuple[TestClient, str, ValueActionExecution]:
    client = _client(db_session, workspace, user)
    created = client.post(
        f"/systems/{system.id}/value-loop/scenarios",
        headers={"Idempotency-Key": f"{key}-create"},
        json={
            "source_run_id": baseline.id,
            "objective": "Exercise Run evidence authorization",
            "title": "Authorized source Run",
        },
    )
    assert created.status_code == 201, created.text
    scenario_id = created.json()["id"]
    simulated = client.post(
        f"/systems/{system.id}/value-loop/scenarios/{scenario_id}/simulate",
        headers={"Idempotency-Key": f"{key}-simulate"},
        json={"recommended_patch": {"mandatory_hitl_if_confidence_below": 0.6}},
    )
    assert simulated.status_code == 201, simulated.text
    approved = client.post(
        f"/systems/{system.id}/value-loop/scenarios/{scenario_id}/approve",
        headers={"Idempotency-Key": f"{key}-approve"},
        json={"simulation_id": simulated.json()["id"]},
    )
    assert approved.status_code == 200, approved.text
    acted = client.post(
        f"/systems/{system.id}/value-loop/scenarios/{scenario_id}/act",
        headers={"Idempotency-Key": f"{key}-act"},
        json={
            "actuator": ACTUATOR,
            "patch": {"mandatory_hitl_if_confidence_below": 0.6},
        },
    )
    assert acted.status_code == 201, acted.text
    action = db_session.query(ValueActionExecution).filter_by(id=acted.json()["id"]).one()
    return client, scenario_id, action


def _observed_run(
    *,
    workspace_id: str,
    system_id: str,
    action: ValueActionExecution,
    owner_id: str | None,
    trigger: str | None = None,
) -> Run:
    return Run(
        id=str(uuid4()),
        workspace_id=workspace_id,
        system_id=system_id,
        initiated_by_user_id=owner_id,
        trigger=trigger,
        status="completed",
        started_at=action.executed_at + timedelta(seconds=1),
        completed_at=action.executed_at + timedelta(seconds=2),
        value_estimated=110,
        value_source="auto",
        input_ref={
            "execution": {
                "control_policy": action.after_state["_control_policy"],
                "flow_sha256": "c" * 64,
                "runtime_revision": RUNTIME_REVISION,
            }
        },
    )


@pytest.fixture(autouse=True)
def _runtime_revision(monkeypatch):
    monkeypatch.setattr(app_settings, "agentium_image_revision", RUNTIME_REVISION)


def test_create_hides_private_cross_system_and_cross_tenant_source_runs(db_session):
    workspace, user, system, _policy, baseline = _seed(db_session)
    _set_contributor(db_session, workspace, user)
    other_user = User(
        id=str(uuid4()),
        username=f"other-{uuid4().hex[:8]}",
        email=f"other-{uuid4().hex[:8]}@example.test",
    )
    baseline.trigger = "chat_agentic"
    baseline.initiated_by_user_id = other_user.id
    foreign_system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Foreign System",
        status="active",
    )
    cross_system_run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=foreign_system.id,
        status="completed",
        completed_at=datetime.utcnow(),
        value_estimated=10,
        value_source="auto",
    )
    foreign_workspace = Workspace(
        id=str(uuid4()),
        slug=f"foreign-{uuid4().hex[:8]}",
        name="Foreign workspace",
    )
    cross_tenant_run = Run(
        id=str(uuid4()),
        workspace_id=foreign_workspace.id,
        system_id=system.id,
        status="completed",
        completed_at=datetime.utcnow(),
        value_estimated=10,
        value_source="auto",
    )
    db_session.add_all(
        [other_user, foreign_system, cross_system_run, foreign_workspace, cross_tenant_run]
    )
    db_session.commit()
    client = _client(db_session, workspace, user)

    denied_ids = [baseline.id, cross_system_run.id, cross_tenant_run.id, str(uuid4())]
    for index, run_id in enumerate(denied_ids):
        response = client.post(
            f"/systems/{system.id}/value-loop/scenarios",
            headers={"Idempotency-Key": f"hidden-source-{index}"},
            json={
                "source_run_id": run_id,
                "objective": "Do not disclose hidden evidence",
                "title": "Hidden source",
            },
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "Run not found"}

    baseline.initiated_by_user_id = user.id
    db_session.commit()
    allowed = client.post(
        f"/systems/{system.id}/value-loop/scenarios",
        headers={"Idempotency-Key": "same-system-owned-source"},
        json={
            "source_run_id": baseline.id,
            "objective": "Use my measured evidence",
            "title": "Authorized source",
        },
    )
    assert allowed.status_code == 201, allowed.text
    assert db_session.query(ValueScenario).count() == 1


def test_create_preserves_shadow_but_run_read_enforce_fails_closed(
    db_session,
    attest_authorization_v2,
):
    workspace, user, system, _policy, baseline = _seed(db_session)
    _set_contributor(db_session, workspace, user)
    other_user = User(
        id=str(uuid4()),
        username=f"candidate-owner-{uuid4().hex[:8]}",
        email=f"candidate-owner-{uuid4().hex[:8]}@example.test",
    )
    baseline.initiated_by_user_id = other_user.id
    db_session.add(other_user)
    _set_run_read_mode(
        db_session,
        workspace=workspace,
        user=user,
        mode="shadow",
    )
    client = _client(db_session, workspace, user)

    shadow = client.post(
        f"/systems/{system.id}/value-loop/scenarios",
        headers={"Idempotency-Key": "shadow-source-read"},
        json={
            "source_run_id": baseline.id,
            "objective": "Preserve legacy behavior in shadow",
            "title": "Shadow source",
        },
    )
    assert shadow.status_code == 201, shadow.text
    assert (
        db_session.query(AuditLog)
        .filter_by(workspace_id=workspace.id, event_type="iam.shadow.diff")
        .count()
        == 1
    )

    config = db_session.query(WorkspaceIAMConfig).filter_by(workspace_id=workspace.id).one()
    config.capability_overrides = {
        "authorization_v2": {
            "policy_version": 2,
            "default_mode": "compat",
            "modes": {"run.read": "enforce"},
        }
    }
    db_session.commit()
    attest_authorization_v2(config, ["run.read"])
    db_session.commit()
    assert resolve_mode(config, resource_kind="run", action="read") is AuthorizationMode.ENFORCE

    enforced = client.post(
        f"/systems/{system.id}/value-loop/scenarios",
        headers={"Idempotency-Key": "enforced-source-read"},
        json={
            "source_run_id": baseline.id,
            "objective": "Candidate denial is authoritative",
            "title": "Enforced source",
        },
    )
    assert enforced.status_code == 404
    assert enforced.json() == {"detail": "Run not found"}
    assert db_session.query(ValueScenario).count() == 1


def test_measure_hides_private_cross_system_and_cross_tenant_source_runs(db_session):
    workspace, user, system, _policy, baseline = _seed(db_session)
    client, scenario_id, action = _act_scenario(
        db_session,
        workspace=workspace,
        user=user,
        system=system,
        baseline=baseline,
        key="measure-boundaries",
    )
    other_user = User(
        id=str(uuid4()),
        username=f"measure-other-{uuid4().hex[:8]}",
        email=f"measure-other-{uuid4().hex[:8]}@example.test",
    )
    private_run = _observed_run(
        workspace_id=workspace.id,
        system_id=system.id,
        action=action,
        owner_id=other_user.id,
        trigger="chat_agentic",
    )
    foreign_system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Foreign measurement System",
        status="active",
    )
    cross_system_run = _observed_run(
        workspace_id=workspace.id,
        system_id=foreign_system.id,
        action=action,
        owner_id=user.id,
    )
    foreign_workspace = Workspace(
        id=str(uuid4()),
        slug=f"measurement-foreign-{uuid4().hex[:8]}",
        name="Foreign measurement workspace",
    )
    cross_tenant_run = _observed_run(
        workspace_id=foreign_workspace.id,
        system_id=system.id,
        action=action,
        owner_id=user.id,
    )
    db_session.add_all(
        [
            other_user,
            private_run,
            foreign_system,
            cross_system_run,
            foreign_workspace,
            cross_tenant_run,
        ]
    )
    db_session.commit()
    _set_contributor(db_session, workspace, user)

    denied_ids = [private_run.id, cross_system_run.id, cross_tenant_run.id, str(uuid4())]
    for index, run_id in enumerate(denied_ids):
        response = client.post(
            f"/systems/{system.id}/value-loop/scenarios/{scenario_id}/measure",
            headers={"Idempotency-Key": f"hidden-measurement-source-{index}"},
            json={"source_run_id": run_id},
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "Run not found"}

    authorized = _observed_run(
        workspace_id=workspace.id,
        system_id=system.id,
        action=action,
        owner_id=user.id,
        trigger="chat_agentic",
    )
    db_session.add(authorized)
    db_session.commit()
    record_runtime_auto_outcome(authorized, db=db_session)
    db_session.commit()
    measured = client.post(
        f"/systems/{system.id}/value-loop/scenarios/{scenario_id}/measure",
        headers={"Idempotency-Key": "same-system-owned-measurement"},
        json={"source_run_id": authorized.id},
    )
    assert measured.status_code == 201, measured.text
    assert measured.json()["source_run_id"] == authorized.id
    assert measured.json()["status"] == "measured"


def test_measure_preserves_shadow_for_a_legacy_visible_source(
    db_session,
):
    workspace, user, system, _policy, baseline = _seed(db_session)
    client, scenario_id, action = _act_scenario(
        db_session,
        workspace=workspace,
        user=user,
        system=system,
        baseline=baseline,
        key="measure-shadow",
    )
    other_user = User(
        id=str(uuid4()),
        username=f"shadow-measure-{uuid4().hex[:8]}",
        email=f"shadow-measure-{uuid4().hex[:8]}@example.test",
    )
    observed = _observed_run(
        workspace_id=workspace.id,
        system_id=system.id,
        action=action,
        owner_id=other_user.id,
    )
    db_session.add_all([other_user, observed])
    db_session.commit()
    record_runtime_auto_outcome(observed, db=db_session)
    db_session.commit()
    _set_contributor(db_session, workspace, user)
    _set_run_read_mode(
        db_session,
        workspace=workspace,
        user=user,
        mode="shadow",
    )

    measured = client.post(
        f"/systems/{system.id}/value-loop/scenarios/{scenario_id}/measure",
        headers={"Idempotency-Key": "shadow-measure-source"},
        json={"source_run_id": observed.id},
    )
    assert measured.status_code == 201, measured.text
    assert measured.json()["source_run_id"] == observed.id
    assert (
        db_session.query(AuditLog)
        .filter_by(workspace_id=workspace.id, event_type="iam.shadow.diff")
        .count()
        == 1
    )


def test_measure_run_read_enforce_hides_denied_explicit_and_implicit_sources(
    db_session,
    attest_authorization_v2,
):
    workspace, user, system, _policy, baseline = _seed(db_session)
    client, scenario_id, action = _act_scenario(
        db_session,
        workspace=workspace,
        user=user,
        system=system,
        baseline=baseline,
        key="measure-enforce",
    )
    other_user = User(
        id=str(uuid4()),
        username=f"enforce-measure-{uuid4().hex[:8]}",
        email=f"enforce-measure-{uuid4().hex[:8]}@example.test",
    )
    observed = _observed_run(
        workspace_id=workspace.id,
        system_id=system.id,
        action=action,
        owner_id=other_user.id,
    )
    db_session.add_all([other_user, observed])
    db_session.commit()
    _set_contributor(db_session, workspace, user)
    _set_run_read_mode(
        db_session,
        workspace=workspace,
        user=user,
        mode="enforce",
        attest_authorization_v2=attest_authorization_v2,
    )

    explicit = client.post(
        f"/systems/{system.id}/value-loop/scenarios/{scenario_id}/measure",
        headers={"Idempotency-Key": "enforce-explicit-source"},
        json={"source_run_id": observed.id},
    )
    assert explicit.status_code == 404
    assert explicit.json() == {"detail": "Run not found"}

    implicit = client.post(
        f"/systems/{system.id}/value-loop/scenarios/{scenario_id}/measure",
        headers={"Idempotency-Key": "enforce-implicit-source"},
        json={},
    )
    assert implicit.status_code == 201, implicit.text
    assert implicit.json()["status"] == "not_measured"
    assert implicit.json()["source_run_id"] is None


def test_api_executes_authoritative_loop_and_preserves_evidence_types(
    db_session,
):
    workspace, user, system, policy, baseline = _seed(db_session)
    client = _client(db_session, workspace, user)

    created = client.post(
        f"/systems/{system.id}/value-loop/scenarios",
        headers={"Idempotency-Key": "api-create"},
        json={
            "source_run_id": baseline.id,
            "objective": "Improve value with a stricter confidence gate",
            "title": "Tighten confidence",
            "rationale": {"source": "operator"},
        },
    )
    assert created.status_code == 201, created.text
    scenario_id = created.json()["id"]

    simulated = client.post(
        f"/systems/{system.id}/value-loop/scenarios/{scenario_id}/simulate",
        headers={"Idempotency-Key": "api-simulate"},
        json={
            "recommended_patch": {"mandatory_hitl_if_confidence_below": 0.6},
        },
    )
    assert simulated.status_code == 201, simulated.text
    assert simulated.json()["evidence_type"] == "simulation"
    assert simulated.json()["model"] == "system-steering:value-model-v1"
    assert simulated.json()["projected_outcome"]["value"] == 125.0
    assert simulated.json()["provenance"]["system_id"] == system.id
    assert simulated.json()["provenance"]["canonical_patch"] == {
        "mandatory_hitl_if_confidence_below": 0.6
    }
    assert simulated.json()["assumptions"]["canonical_patch"] == {
        "mandatory_hitl_if_confidence_below": 0.6
    }
    simulation_id = simulated.json()["id"]

    approved = client.post(
        f"/systems/{system.id}/value-loop/scenarios/{scenario_id}/approve",
        headers={"Idempotency-Key": "api-approve"},
        json={"simulation_id": simulation_id},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert len(approved.json()["approved_simulation_content_sha256"]) == 64

    acted = client.post(
        f"/systems/{system.id}/value-loop/scenarios/{scenario_id}/act",
        headers={"Idempotency-Key": "api-act"},
        json={
            "actuator": ACTUATOR,
            "patch": {"mandatory_hitl_if_confidence_below": 0.6},
        },
    )
    assert acted.status_code == 201, acted.text
    assert acted.json()["changed_fields"] == ["mandatory_hitl_if_confidence_below"]
    db_session.refresh(policy)
    assert policy.mandatory_hitl_if_confidence_below == 0.6

    action_time = datetime.fromisoformat(acted.json()["executed_at"])
    action = db_session.query(ValueActionExecution).filter_by(id=acted.json()["id"]).one()
    db_session.refresh(system)
    transitions = system.settings["_lot8_value_loop_rollout_v1"][
        "policy_transitions"
    ]
    assert len(transitions) == 1
    assert transitions[0]["action_execution_id"] == action.id
    assert transitions[0]["scenario_id"] == scenario_id
    assert transitions[0]["from"] == action.before_state["_control_policy"]
    assert transitions[0]["to"] == action.after_state["_control_policy"]
    assert client.get(f"/systems/{system.id}/value-loop").status_code == 200
    observed = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        status="completed",
        started_at=action_time + timedelta(seconds=1),
        completed_at=action_time + timedelta(seconds=2),
        decision="allow",
        confidence=0.82,
        value_estimated=130.0,
        cost_internal=8.0,
        efficiency=1.3,
        value_source="auto",
        input_ref={
            "execution": {
                "control_policy": action.after_state["_control_policy"],
                "flow_sha256": "d" * 64,
                "runtime_revision": RUNTIME_REVISION,
            }
        },
    )
    db_session.add(observed)
    db_session.commit()
    record_runtime_auto_outcome(observed, db=db_session)
    db_session.commit()

    measured = client.post(
        f"/systems/{system.id}/value-loop/scenarios/{scenario_id}/measure",
        headers={"Idempotency-Key": "api-measure"},
        json={"source_run_id": observed.id},
    )
    assert measured.status_code == 201, measured.text
    assert measured.json()["status"] == "measured"
    assert measured.json()["evidence_type"] == "run"
    assert measured.json()["simulation_id"] == simulation_id
    assert measured.json()["delta"]["value"] == 30.0
    assert measured.json()["forecast_delta"] == {"value": 5.0, "cost": -3.0}
    assert measured.json()["assumption_verdict"] == "confirmed"
    assert measured.json()["assumption_evaluation"]["causality"] == (
        "not_established"
    )

    payload = client.get(f"/systems/{system.id}/value-loop")
    assert payload.status_code == 200, payload.text
    assert payload.json()["system_id"] == system.id
    assert payload.json()["items"][0]["status"] == "measured"
    assert payload.json()["items"][0]["simulations"][0]["evidence_type"] == "simulation"
    assert payload.json()["items"][0]["measurements"][0]["evidence_type"] == "run"
    portfolio = client.get("/hypervisor/value-loop")
    assert portfolio.status_code == 200, portfolio.text
    assert portfolio.json()["scope"] == "portfolio"
    assert portfolio.json()["systems"][0]["system_id"] == system.id
    assert portfolio.json()["systems"][0]["actuator_state"] == "available"
    assert portfolio.json()["observed_value_delta"] == {
        "state": "available",
        "value": 30.0,
        "source": "value_measurements.delta.value",
        "sample_count": 1,
    }
    assert portfolio.json()["simulation_is_measurement"] is False
    assert portfolio.json()["outcomes"]["state"] == "available"
    assert portfolio.json()["outcomes"]["forecast_verdict_counts"] == {
        "state": "available",
        "value": {
            "confirmed": 1,
            "partially_confirmed": 0,
            "not_confirmed": 0,
        },
        "source": "value_measurements.assumption_verdict",
        "sample_count": 1,
    }
    assert portfolio.json()["risks"] == {
        "state": "available",
        "count": 0,
        "items": [],
        "source": (
            "value_scenarios.status,value_measurements.status,reason,"
            "assumption_verdict"
        ),
    }
    assert portfolio.json()["arbitrations"]["state"] == "available"
    assert portfolio.json()["arbitrations"]["items"][0]["scenario_id"] == scenario_id
    assert portfolio.json()["arbitrations"]["items"][0]["system_id"] == system.id
    assert portfolio.json()["scenarios"]["state"] == "available"
    assert portfolio.json()["scenarios"]["items"][0]["id"] == scenario_id
    portfolio_outcome = portfolio.json()["scenarios"]["items"][0]["outcome"]
    assert portfolio_outcome["state"] == "available"
    assert portfolio_outcome["measurement_id"] == measured.json()["id"]
    assert portfolio_outcome["delta"]["value"] == 30.0
    assert portfolio_outcome["forecast_delta"] == {"value": 5.0, "cost": -3.0}
    assert portfolio_outcome["assumption_verdict"] == "confirmed"


def test_api_act_rejects_simulation_rewrite_after_approval(db_session):
    workspace, user, system, policy, baseline = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post(
        f"/systems/{system.id}/value-loop/scenarios",
        headers={"Idempotency-Key": "rewrite-create"},
        json={
            "source_run_id": baseline.id,
            "objective": "Do not trust a rewritten forecast",
            "title": "Approval content pin",
        },
    )
    assert created.status_code == 201, created.text
    scenario_id = created.json()["id"]
    simulated = client.post(
        f"/systems/{system.id}/value-loop/scenarios/{scenario_id}/simulate",
        headers={"Idempotency-Key": "rewrite-simulate"},
        json={"recommended_patch": {"mandatory_hitl_if_confidence_below": 0.6}},
    )
    assert simulated.status_code == 201, simulated.text
    approved = client.post(
        f"/systems/{system.id}/value-loop/scenarios/{scenario_id}/approve",
        headers={"Idempotency-Key": "rewrite-approve"},
        json={"simulation_id": simulated.json()["id"]},
    )
    assert approved.status_code == 200, approved.text
    operation_count = db_session.query(ValueLoopOperation).count()

    simulation = db_session.get(ValueSimulation, simulated.json()["id"])
    simulation.recommended_action = {
        "actuator": ACTUATOR,
        "patch": {"mandatory_hitl_if_confidence_below": 0.7},
    }
    db_session.commit()
    attacked = client.post(
        f"/systems/{system.id}/value-loop/scenarios/{scenario_id}/act",
        headers={"Idempotency-Key": "rewrite-act"},
        json={
            "actuator": ACTUATOR,
            "patch": {"mandatory_hitl_if_confidence_below": 0.7},
        },
    )

    assert attacked.status_code == 409, attacked.text
    assert attacked.json()["detail"]["code"] == "approved_simulation_changed"
    db_session.refresh(policy)
    assert policy.mandatory_hitl_if_confidence_below == 0.4
    assert db_session.query(ValueActionExecution).count() == 0
    assert db_session.query(ValueLoopOperation).count() == operation_count


def test_api_rejects_unmeasured_run_as_scenario_baseline(db_session):
    workspace, user, system, _policy, baseline = _seed(db_session)
    baseline.value_source = "unset"
    db_session.commit()
    client = _client(db_session, workspace, user)

    response = client.post(
        f"/systems/{system.id}/value-loop/scenarios",
        headers={"Idempotency-Key": "reject-unmeasured-baseline"},
        json={
            "source_run_id": baseline.id,
            "objective": "Do not reinterpret an unset value",
            "title": "Invalid baseline",
        },
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "baseline_not_measured"
    assert db_session.query(ValueScenario).count() == 0
    assert db_session.query(ValueLoopOperation).count() == 0


def test_patch_specific_forecasts_produce_distinct_outcomes(db_session):
    workspace, user, system, _policy, baseline = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post(
        f"/systems/{system.id}/value-loop/scenarios",
        headers={"Idempotency-Key": "patch-specific-create"},
        json={
            "source_run_id": baseline.id,
            "objective": "Compare opposing bounded patches",
            "title": "Patch-specific forecast",
        },
    )
    assert created.status_code == 201, created.text
    scenario_id = created.json()["id"]

    low = client.post(
        f"/systems/{system.id}/value-loop/scenarios/{scenario_id}/simulate",
        headers={"Idempotency-Key": "patch-specific-low"},
        json={"recommended_patch": {"mandatory_hitl_if_confidence_below": 0.2}},
    )
    high = client.post(
        f"/systems/{system.id}/value-loop/scenarios/{scenario_id}/simulate",
        headers={"Idempotency-Key": "patch-specific-high"},
        json={"recommended_patch": {"mandatory_hitl_if_confidence_below": 0.8}},
    )

    assert low.status_code == 201, low.text
    assert high.status_code == 201, high.text
    assert low.json()["projected_outcome"] != high.json()["projected_outcome"]
    assert low.json()["projected_outcome"]["value"] == 105.0
    assert high.json()["projected_outcome"]["value"] == 125.0
    assert low.json()["provenance"]["patch_sha256"] != high.json()["provenance"][
        "patch_sha256"
    ]
    assert low.json()["provenance"]["matched_forecasts"][0]["maximum"] == 0.5
    assert high.json()["provenance"]["matched_forecasts"][0]["minimum"] == 0.5


def test_exact_enforce_manifest_executes_every_value_loop_endpoint(
    db_session,
    attest_authorization_v2,
):
    workspace, user, system, _policy, baseline = _seed(db_session)
    actions = [
        "value_scenario.read",
        "value_scenario.create",
        "value_scenario.simulate",
        "value_scenario.approve",
        "value_scenario.act",
        "value_scenario.measure",
    ]
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=1,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {action: "enforce" for action in actions},
            }
        },
        updated_by_user_id=user.id,
    )
    db_session.add(config)
    db_session.commit()
    attest_authorization_v2(config, actions)
    db_session.commit()
    assert all(
        resolve_mode(
            config,
            resource_kind="value_scenario",
            action=action.split(".", 1)[1],
        )
        is AuthorizationMode.ENFORCE
        for action in actions
    )
    client = _client(db_session, workspace, user)

    created = client.post(
        f"/systems/{system.id}/value-loop/scenarios",
        headers={"Idempotency-Key": "enforce-create"},
        json={
            "source_run_id": baseline.id,
            "objective": "Exercise the exact manifest vocabulary",
            "title": "Exact enforce value loop",
        },
    )
    assert created.status_code == 201, created.text
    scenario_id = created.json()["id"]
    simulated = client.post(
        f"/systems/{system.id}/value-loop/scenarios/{scenario_id}/simulate",
        headers={"Idempotency-Key": "enforce-simulate"},
        json={"recommended_patch": {"mandatory_hitl_if_confidence_below": 0.6}},
    )
    assert simulated.status_code == 201, simulated.text
    approved = client.post(
        f"/systems/{system.id}/value-loop/scenarios/{scenario_id}/approve",
        headers={"Idempotency-Key": "enforce-approve"},
        json={"simulation_id": simulated.json()["id"]},
    )
    assert approved.status_code == 200, approved.text
    acted = client.post(
        f"/systems/{system.id}/value-loop/scenarios/{scenario_id}/act",
        headers={"Idempotency-Key": "enforce-act"},
        json={
            "actuator": ACTUATOR,
            "patch": {"mandatory_hitl_if_confidence_below": 0.6},
        },
    )
    assert acted.status_code == 201, acted.text
    action_time = datetime.fromisoformat(acted.json()["executed_at"])
    action = db_session.query(ValueActionExecution).filter_by(id=acted.json()["id"]).one()
    observed = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        status="completed",
        started_at=action_time + timedelta(seconds=1),
        completed_at=action_time + timedelta(seconds=2),
        value_estimated=110,
        value_source="auto",
        input_ref={
            "execution": {
                "control_policy": action.after_state["_control_policy"],
                "flow_sha256": "e" * 64,
                "runtime_revision": RUNTIME_REVISION,
            }
        },
    )
    db_session.add(observed)
    db_session.commit()
    record_runtime_auto_outcome(observed, db=db_session)
    db_session.commit()
    measured = client.post(
        f"/systems/{system.id}/value-loop/scenarios/{scenario_id}/measure",
        headers={"Idempotency-Key": "enforce-measure"},
        json={"source_run_id": observed.id},
    )
    assert measured.status_code == 201, measured.text
    assert measured.json()["status"] == "measured"
    listed = client.get(f"/systems/{system.id}/value-loop")
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["status"] == "measured"


def test_missing_patch_forecast_is_not_configured_and_persists_nothing(db_session):
    workspace, user, system, _policy, baseline = _seed(db_session)
    system.settings = {
        **system.settings,
        "steering_model": {
            "version": "legacy-generic-model",
            "confidence": 0.8,
            "cost_multiplier": 0.01,
            "value_multiplier": 99,
        },
    }
    db_session.commit()
    client = _client(db_session, workspace, user)
    created = client.post(
        f"/systems/{system.id}/value-loop/scenarios",
        headers={"Idempotency-Key": "missing-forecast-create"},
        json={
            "source_run_id": baseline.id,
            "objective": "Never use a generic fallback",
            "title": "Missing patch forecast",
        },
    )
    assert created.status_code == 201, created.text

    response = client.post(
        f"/systems/{system.id}/value-loop/scenarios/{created.json()['id']}/simulate",
        headers={"Idempotency-Key": "missing-forecast-simulate"},
        json={"recommended_patch": {"mandatory_hitl_if_confidence_below": 0.6}},
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "SIMULATION_NOT_CONFIGURED"
    assert db_session.query(ValueSimulation).count() == 0


def test_gate_and_tenant_boundary_fail_closed(db_session):
    workspace, user, system, _policy, baseline = _seed(db_session)
    client = _client(db_session, workspace, user)

    missing_key = client.post(
        f"/systems/{system.id}/value-loop/scenarios",
        json={
            "source_run_id": baseline.id,
            "objective": "Objective",
            "title": "Title",
        },
    )
    assert missing_key.status_code == 422

    other_workspace = Workspace(
        id=str(uuid4()),
        slug=f"other-{uuid4().hex[:8]}",
        name="Other",
    )
    other_system = System(
        id=str(uuid4()),
        workspace_id=other_workspace.id,
        name="Foreign",
        status="active",
        settings={"experience": {"value_loop_canary": "v1"}},
    )
    db_session.add_all([other_workspace, other_system])
    db_session.commit()
    assert client.get(f"/systems/{other_system.id}/value-loop").status_code == 404

    workspace.settings = {"features": {"value_loop_v1": False}}
    db_session.commit()
    disabled = client.get(f"/systems/{system.id}/value-loop")
    assert disabled.status_code == 404
    assert disabled.json()["detail"]["code"] == "VALUE_LOOP_NOT_CONFIGURED"


def test_multiple_marked_systems_close_the_gate(db_session):
    workspace, user, system, _policy, _baseline = _seed(db_session)
    duplicate = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Duplicate marker",
        status="active",
        settings={"experience": {"value_loop_canary": "v1"}},
    )
    db_session.add(duplicate)
    db_session.commit()

    response = _client(db_session, workspace, user).get(f"/systems/{system.id}/value-loop")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "VALUE_LOOP_NOT_CONFIGURED"


def test_activation_from_another_runtime_revision_closes_the_gate(
    db_session,
    monkeypatch,
):
    workspace, user, system, _policy, _baseline = _seed(db_session)
    monkeypatch.setattr(app_settings, "agentium_image_revision", "d" * 40)

    response = _client(db_session, workspace, user).get(
        f"/systems/{system.id}/value-loop"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "VALUE_LOOP_NOT_CONFIGURED"


def test_sha_bound_canary_window_opens_then_expires_closed(db_session):
    workspace, user, system, policy, _baseline = _seed(db_session)
    now = datetime.now(UTC)
    contract_sha = "f" * 64
    opened_at = (now - timedelta(minutes=1)).isoformat()
    policy_reference = control_policy_execution_contract(policy)
    audit_id = str(uuid4())
    policy_chain_ref = value_loop_policy_chain_reference(
        system_id=system.id,
        revision=RUNTIME_REVISION,
        created_at=opened_at,
        control_policy=policy_reference,
    )
    settings = dict(system.settings)
    settings["_lot8_value_loop_rollout_v1"] = {
        "schema_version": 1,
        "prepared": {"system_id": system.id, "contract_sha256": contract_sha},
        "proof_window": {
            "audit_id": audit_id,
            "system_id": system.id,
            "revision": RUNTIME_REVISION,
            "contract_sha256": contract_sha,
            "opened_at": opened_at,
            "expires_at": (now + timedelta(minutes=30)).isoformat(),
            "opened_by": "operator@example.test",
            "policy_chain_ref": policy_chain_ref,
            "control_policy": policy_reference,
        },
        "activations": [],
        "deactivations": [],
        "policy_transitions": [],
    }
    system.settings = settings
    db_session.add(
        AuditLog(
            id=audit_id,
            workspace_id=workspace.id,
            event_type="lot8.value_loop.canary_window.opened",
            actor="operator@example.test",
            agent_id=system.id,
            details={
                "system_id": system.id,
                "revision": RUNTIME_REVISION,
                "expires_at": settings["_lot8_value_loop_rollout_v1"][
                    "proof_window"
                ]["expires_at"],
                "feature": "value_loop_v1",
                "claim_promoted": False,
                "policy_chain_ref": policy_chain_ref,
                "control_policy_revision": policy_reference["revision"],
                "control_policy_sha256": policy_reference["sha256"],
            },
        )
    )
    db_session.commit()
    client = _client(db_session, workspace, user)

    assert client.get(f"/systems/{system.id}/value-loop").status_code == 200

    settings = dict(system.settings)
    state = dict(settings["_lot8_value_loop_rollout_v1"])
    window = dict(state["proof_window"])
    window["expires_at"] = (now - timedelta(seconds=1)).isoformat()
    state["proof_window"] = window
    settings["_lot8_value_loop_rollout_v1"] = state
    system.settings = settings
    db_session.commit()
    expired = client.get(f"/systems/{system.id}/value-loop")
    assert expired.status_code == 404
    assert expired.json()["detail"]["code"] == "VALUE_LOOP_NOT_CONFIGURED"


def test_runtime_gate_closes_when_actuator_or_membrane_drifts(db_session):
    workspace, user, system, policy, _baseline = _seed(db_session)
    client = _client(db_session, workspace, user)
    path = f"/systems/{system.id}/value-loop"
    assert client.get(path).status_code == 200

    original_settings = copy.deepcopy(system.settings)
    drifted_settings = copy.deepcopy(system.settings)
    drifted_settings["value_loop"]["actuators"][ACTUATOR]["fields"][
        "max_cost_per_decision"
    ]["max"] = 51
    system.settings = drifted_settings
    db_session.commit()
    drifted = client.get(path)
    assert drifted.status_code == 404
    assert drifted.json()["detail"]["code"] == "VALUE_LOOP_NOT_CONFIGURED"

    system.settings = original_settings
    drifted_extra = copy.deepcopy(policy.extra)
    drifted_extra["membrane_spec"]["enforcement_mode"] = "shadow"
    policy.extra = drifted_extra
    db_session.commit()
    drifted = client.get(path)
    assert drifted.status_code == 404
    assert drifted.json()["detail"]["code"] == "VALUE_LOOP_NOT_CONFIGURED"


def test_external_control_policy_drift_closes_actions_but_keeps_portfolio_history(
    db_session,
):
    workspace, user, system, policy, _baseline = _seed(db_session)
    client = _client(db_session, workspace, user)
    path = f"/systems/{system.id}/value-loop"
    assert client.get(path).status_code == 200

    policy.max_cost_per_decision = 11.0
    db_session.commit()

    closed = client.get(path)
    assert closed.status_code == 404
    assert closed.json()["detail"]["code"] == "VALUE_LOOP_NOT_CONFIGURED"
    portfolio = client.get("/hypervisor/value-loop")
    assert portfolio.status_code == 200
    assert portfolio.json()["state"] == "available"
    assert portfolio.json()["systems"][0]["system_id"] == system.id
    assert portfolio.json()["systems"][0]["actuator_state"] == "not_configured"

    policy.max_cost_per_decision = 10.0
    replacement = ControlPolicy(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Unattested replacement",
        scope="system",
        target_id=system.id,
        max_cost_per_decision=10.0,
        max_latency_ms=5_000.0,
        mandatory_hitl_if_confidence_below=0.4,
        extra=copy.deepcopy(policy.extra),
    )
    system.control_policy_id = replacement.id
    db_session.add(replacement)
    db_session.commit()

    identity_drift = client.get(path)
    assert identity_drift.status_code == 404
    assert identity_drift.json()["detail"]["code"] == "VALUE_LOOP_NOT_CONFIGURED"


def test_mutation_refreshes_authority_after_workspace_lock(
    db_session,
    monkeypatch,
):
    workspace, user, system, _policy, baseline = _seed(db_session)
    original_lock = value_loop._workspace_for_mutation
    decisions: list[bool] = []

    def _lock_then_revoke(db, selected_workspace):
        locked = original_lock(db, selected_workspace)
        db.execute(
            update(WorkspaceMember)
            .where(
                WorkspaceMember.workspace_id == workspace.id,
                WorkspaceMember.user_id == user.id,
            )
            .values(role="member", role_template="workspace_viewer"),
            execution_options={"synchronize_session": False},
        )
        db.flush()
        return locked

    def _enforce_fresh_authority(*_args, **kwargs):
        allowed = bool(kwargs["legacy_allowed"])
        decisions.append(allowed)
        if not allowed:
            raise HTTPException(status_code=403, detail="revoked")

    monkeypatch.setattr(value_loop, "_workspace_for_mutation", _lock_then_revoke)
    monkeypatch.setattr(value_loop, "enforce_action", _enforce_fresh_authority)

    response = _client(db_session, workspace, user).post(
        f"/systems/{system.id}/value-loop/scenarios",
        headers={"Idempotency-Key": "revoked-before-authority-refresh"},
        json={
            "source_run_id": baseline.id,
            "objective": "Must not be persisted",
            "title": "Revoked authority",
        },
    )

    assert response.status_code == 403
    # The composed System read still permits the viewer, then the refreshed
    # scenario-create action observes the revoked contributor authority.
    assert decisions == [True, False]
    assert db_session.query(ValueScenario).count() == 0
    assert db_session.query(ValueLoopOperation).count() == 0


def test_empty_value_loop_read_still_composes_system_authority(
    db_session,
    monkeypatch,
):
    workspace, user, system, _policy, _baseline = _seed(db_session)
    decisions: list[tuple[str, str, dict[str, object]]] = []

    def _observe_authority(*_args, **kwargs):
        decisions.append(
            (
                kwargs["resource_kind"],
                kwargs["action"],
                dict(kwargs["resource_attrs"]),
            )
        )

    monkeypatch.setattr(value_loop, "enforce_action", _observe_authority)
    response = _client(db_session, workspace, user).get(
        f"/systems/{system.id}/value-loop"
    )

    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
    assert response.json()["state"] == "not_configured"
    assert [(kind, action) for kind, action, _ in decisions] == [
        ("system", "read"),
        ("value_scenario", "read"),
    ]
    assert all(attrs["system_id"] == system.id for _, _, attrs in decisions)


def test_value_loop_read_models_redact_credential_shaped_evidence(db_session):
    workspace, user, system, _policy, baseline = _seed(db_session)
    settings = dict(system.settings)
    steering = dict(settings["steering_model"])
    steering["assumptions"] = ["Bearer abcdefghijklmnopqrstuvwxyz"]
    settings["steering_model"] = steering
    system.settings = settings
    db_session.commit()
    client = _client(db_session, workspace, user)

    created = client.post(
        f"/systems/{system.id}/value-loop/scenarios",
        headers={"Idempotency-Key": "redacted-create"},
        json={
            "source_run_id": baseline.id,
            "objective": "Keep evidence safe",
            "title": "Redaction contract",
            "rationale": {"api_key": "must-not-leak", "source": "operator"},
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["decision"]["rationale"] == {
        "api_key": "[redacted]",
        "source": "operator",
    }

    simulated = client.post(
        f"/systems/{system.id}/value-loop/scenarios/{created.json()['id']}/simulate",
        headers={"Idempotency-Key": "redacted-simulate"},
        json={"recommended_patch": {"mandatory_hitl_if_confidence_below": 0.6}},
    )
    assert simulated.status_code == 201, simulated.text
    assert simulated.json()["assumptions"]["configured"] == ["[redacted]"]

    listed = client.get(f"/systems/{system.id}/value-loop")
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["decision"]["rationale"]["api_key"] == "[redacted]"
    assert listed.json()["items"][0]["simulations"][0]["assumptions"]["configured"] == [
        "[redacted]"
    ]


def test_value_loop_decision_read_shadow_enforce_and_privileged_roles(
    db_session,
    attest_authorization_v2,
):
    workspace, user, system, _policy, baseline = _seed(db_session)
    owner_client = _client(db_session, workspace, user)
    created = owner_client.post(
        f"/systems/{system.id}/value-loop/scenarios",
        headers={"Idempotency-Key": "decision-read-projection"},
        json={
            "source_run_id": baseline.id,
            "objective": "Authorize the projected Decision",
            "title": "Decision read projection",
        },
    )
    assert created.status_code == 201, created.text
    scenario_id = created.json()["id"]

    _set_contributor(db_session, workspace, user)
    config = _set_decision_read_mode(
        db_session,
        workspace=workspace,
        user=user,
        mode="shadow",
    )
    contributor = _client(db_session, workspace, user)

    shadow_system = contributor.get(f"/systems/{system.id}/value-loop")
    shadow_portfolio = contributor.get("/hypervisor/value-loop")
    assert shadow_system.status_code == shadow_portfolio.status_code == 200
    shadow_item = shadow_system.json()["items"][0]
    assert shadow_item["id"] == scenario_id
    assert shadow_item["decision_state"] == "available"
    assert shadow_item["decision"] is not None
    assert shadow_portfolio.json()["arbitrations"]["state"] == "available"
    assert shadow_portfolio.json()["scenarios"]["items"][0][
        "decision_state"
    ] == "available"
    assert shadow_portfolio.json()["scenarios"]["items"][0]["decision"] is not None
    shadow_evidence = [
        row
        for row in db_session.query(AuditLog)
        .filter_by(
            workspace_id=workspace.id,
            event_type="iam.shadow.evaluation",
        )
        .all()
        if row.details.get("action") == "decision.read"
    ]
    assert shadow_evidence
    assert all(row.details["mismatches"] == 1 for row in shadow_evidence)

    overrides = copy.deepcopy(config.capability_overrides)
    overrides["authorization_v2"]["modes"] = {"decision.read": "enforce"}
    config.capability_overrides = overrides
    config.version += 1
    db_session.commit()
    attest_authorization_v2(config, ["decision.read"])
    db_session.commit()

    restricted_system = contributor.get(f"/systems/{system.id}/value-loop")
    restricted_portfolio = contributor.get("/hypervisor/value-loop")
    assert restricted_system.status_code == restricted_portfolio.status_code == 200
    restricted_item = restricted_system.json()["items"][0]
    assert restricted_item["decision_state"] == "restricted"
    assert restricted_item["decision"] is None
    assert restricted_portfolio.json()["arbitrations"] == {
        "state": "restricted",
        "items": [],
        "source": "decisions.kind=value_loop,scope=system",
    }
    restricted_scenario = restricted_portfolio.json()["scenarios"]["items"][0]
    assert restricted_scenario["decision_state"] == "restricted"
    assert restricted_scenario["decision"] is None

    for role, role_template in (
        ("reviewer", "workspace_reviewer"),
        ("admin", "workspace_admin"),
    ):
        _set_member_role(
            db_session,
            workspace=workspace,
            user=user,
            role=role,
            role_template=role_template,
        )
        privileged_system = contributor.get(f"/systems/{system.id}/value-loop")
        privileged_portfolio = contributor.get("/hypervisor/value-loop")
        assert privileged_system.json()["items"][0]["decision_state"] == "available"
        assert privileged_system.json()["items"][0]["decision"] is not None
        assert privileged_portfolio.json()["arbitrations"]["state"] == "available"
        assert privileged_portfolio.json()["arbitrations"]["items"]


def test_value_loop_decision_read_invalid_enforce_attestation_fails_closed(
    db_session,
):
    workspace, user, system, _policy, baseline = _seed(db_session)
    owner_client = _client(db_session, workspace, user)
    created = owner_client.post(
        f"/systems/{system.id}/value-loop/scenarios",
        headers={"Idempotency-Key": "decision-read-invalid-attestation"},
        json={
            "source_run_id": baseline.id,
            "objective": "Fail closed",
            "title": "Invalid attestation",
        },
    )
    assert created.status_code == 201, created.text

    _set_contributor(db_session, workspace, user)
    _set_decision_read_mode(
        db_session,
        workspace=workspace,
        user=user,
        mode="enforce",
    )
    client = _client(db_session, workspace, user)

    system_payload = client.get(f"/systems/{system.id}/value-loop")
    portfolio_payload = client.get("/hypervisor/value-loop")
    assert system_payload.status_code == portfolio_payload.status_code == 200
    assert system_payload.json()["items"][0]["decision_state"] == "restricted"
    assert system_payload.json()["items"][0]["decision"] is None
    assert portfolio_payload.json()["arbitrations"]["state"] == "restricted"
    assert portfolio_payload.json()["arbitrations"]["items"] == []
    assert portfolio_payload.json()["scenarios"]["items"][0][
        "decision_state"
    ] == "restricted"
    assert portfolio_payload.json()["scenarios"]["items"][0]["decision"] is None


def test_portfolio_value_loop_exact_deny_hides_scenario_and_all_derivatives(
    db_session,
    attest_authorization_v2,
):
    workspace, user, system, _policy, baseline = _seed(db_session)
    owner_client = _client(db_session, workspace, user)
    created = owner_client.post(
        f"/systems/{system.id}/value-loop/scenarios",
        headers={"Idempotency-Key": "portfolio-scenario-read-deny"},
        json={
            "source_run_id": baseline.id,
            "objective": "PORTFOLIO SCENARIO SECRET",
            "title": "PORTFOLIO DECISION SECRET",
        },
    )
    assert created.status_code == 201, created.text
    scenario_id = created.json()["id"]

    member = (
        db_session.query(WorkspaceMember)
        .filter_by(workspace_id=workspace.id, user_id=user.id)
        .one()
    )
    db_session.delete(member)
    db_session.commit()
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=1,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {"value_scenario.read": "enforce"},
            }
        },
        updated_by_user_id=user.id,
    )
    db_session.add(config)
    db_session.commit()
    attest_authorization_v2(config, ["value_scenario.read"])
    db_session.commit()

    response = _client(db_session, workspace, user).get("/hypervisor/value-loop")

    assert response.status_code == 200
    payload = response.json()
    assert payload["systems"][0]["scenario_state"] == "restricted"
    assert payload["systems"][0]["scenario_count"] == 0
    assert payload["systems"][0]["open_count"] == 0
    assert payload["systems"][0]["measured_count"] == 0
    assert payload["scenarios"]["state"] == "restricted"
    assert payload["scenarios"]["items"] == []
    assert payload["risks"]["state"] == "restricted"
    assert payload["risks"]["items"] == []
    assert payload["arbitrations"]["state"] == "restricted"
    assert payload["arbitrations"]["items"] == []
    assert payload["outcomes"]["state"] == "restricted"
    assert payload["observed_value_delta"]["state"] == "restricted"
    assert scenario_id not in response.text
    assert "PORTFOLIO SCENARIO SECRET" not in response.text
    assert "PORTFOLIO DECISION SECRET" not in response.text
