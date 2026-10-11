from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta

import pytest

from app.models.capability import Capability
from app.models.policy import AdaptivePolicy, ControlPolicy
from app.models.run import Run
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.workspace import Workspace
from app.services.control_policy_snapshot import control_policy_execution_contract
from app.services.run_engine.engine import (
    _build_initial_ctx,
    _load_adaptive_policy,
    _load_control_policy,
    _snapshot_run_flow,
)


def _workspace(db_session, name: str) -> Workspace:
    row = Workspace(
        id=str(uuid.uuid4()),
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_run_start_overwrites_caller_policy_identity_with_loaded_policy(db_session):
    workspace = _workspace(db_session, "Policy execution identity")
    system = System(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name="Policy-bound System",
        objective="test",
        flow_definition={"nodes": [], "edges": []},
    )
    policy = ControlPolicy(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name="Bound policy",
        scope="system",
        target_id=system.id,
        mandatory_hitl_if_confidence_below=0.6,
    )
    system.control_policy_id = policy.id
    run = Run(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        status="pending",
        input_ref={
            "execution": {
                "control_policy": {
                    "schema_version": 1,
                    "policy_id": policy.id,
                    "revision": "control-policy-v1:" + "f" * 64,
                    "sha256": "f" * 64,
                }
            }
        },
    )
    db_session.add_all([system, policy, run])
    db_session.commit()

    _snapshot_run_flow(db_session, run, system, control=policy)

    assert run.input_ref["execution"]["control_policy"] == (
        control_policy_execution_contract(policy)
    )
    observed = [cp for cp in run.checkpoints if cp.get("kind") == "mandate_snapshot"]
    assert len(observed) == 1
    assert observed[0]["control_policy"] == control_policy_execution_contract(policy)
    assert observed[0]["mandate"]["spec"]["valves"]["mandatory_hitl_if_confidence_below"] == 0.6
    policy.mandatory_hitl_if_confidence_below = 0.9
    _snapshot_run_flow(db_session, run, system, control=policy, first_start=False)
    assert [cp for cp in run.checkpoints if cp.get("kind") == "mandate_snapshot"] == observed


def test_system_without_explicit_adaptive_policy_never_inherits_global_latest(db_session):
    workspace = _workspace(db_session, "No implicit policy")
    db_session.add(
        AdaptivePolicy(
            id=str(uuid.uuid4()),
            workspace_id=workspace.id,
            name="unrelated latest policy",
            enabled=True,
            scope="portfolio",
        )
    )
    system = System(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name="unbound system",
        objective="test",
        adaptive_policy_id=None,
    )
    db_session.add(system)
    db_session.commit()

    assert _load_adaptive_policy(db_session, system) is None


def test_explicit_capability_scoped_policy_binding_remains_valid(db_session):
    workspace = _workspace(db_session, "Capability policy")
    capability = Capability(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        slug=f"cap-{uuid.uuid4().hex[:8]}",
        name="Translation capability",
        description="test",
    )
    policy = AdaptivePolicy(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name="Translation replay adaptation",
        enabled=True,
        scope="capability",
        target_id=capability.id,
    )
    system = System(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name="Translation Suite",
        objective="test",
        capability_id=capability.id,
        adaptive_policy_id=policy.id,
    )
    db_session.add_all([capability, policy, system])
    db_session.commit()

    assert _load_adaptive_policy(db_session, system).id == policy.id


def test_explicit_policy_must_still_match_workspace_and_scope_target(db_session):
    workspace = _workspace(db_session, "Bound workspace")
    other = _workspace(db_session, "Other workspace")
    policy = AdaptivePolicy(
        id=str(uuid.uuid4()),
        workspace_id=other.id,
        name="cross-workspace policy",
        enabled=True,
        scope="system",
        target_id="different-system",
    )
    system = System(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name="Protected system",
        objective="test",
        adaptive_policy_id=policy.id,
    )
    db_session.add_all([policy, system])
    db_session.commit()

    assert _load_adaptive_policy(db_session, system) is None


def test_control_policy_binding_requires_same_workspace_scope_and_target(db_session):
    workspace = _workspace(db_session, "Control workspace")
    system = System(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name="Protected system",
        objective="test",
    )
    wrong_target = ControlPolicy(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name="Another system policy",
        scope="system",
        target_id="another-system",
    )
    system.control_policy_id = wrong_target.id
    db_session.add_all([system, wrong_target])
    db_session.commit()

    assert _load_control_policy(db_session, system) is None

    correct = ControlPolicy(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name="Exact system policy",
        scope="system",
        target_id=system.id,
    )
    db_session.add(correct)
    system.control_policy_id = correct.id
    db_session.commit()

    assert _load_control_policy(db_session, system).id == correct.id


def test_run_snapshot_replaces_caller_tenant_actor_and_retrieval_contract(db_session):
    workspace = _workspace(db_session, "Canonical tenant")
    other = _workspace(db_session, "Other tenant")
    contract = {
        "collection": "canonical-collection",
        "asset_binding": "authoritative",
    }
    system = System(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name="Tenant-safe system",
        objective="test",
        settings={"retrieval_contract": contract},
        execution_profile={"max_runtime_s": 12},
        flow_definition={"variant": "test", "nodes": []},
    )
    run = Run(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        initiated_by_user_id=None,
        status="pending",
        input_ref={
            "workspace_id": other.id,
            "workspace_slug": other.slug,
            "user_id": "spoofed-user",
            "retrieval_contract": {
                "collection": "other-tenant-collection",
                "allow_workspace_fallback": True,
            },
        },
    )
    db_session.add_all([system, run])
    db_session.commit()

    _snapshot_run_flow(db_session, run, system)
    ctx = _build_initial_ctx(db_session, run, system, None)

    assert run.input_ref["workspace_id"] == workspace.id
    assert run.input_ref["workspace_slug"] == workspace.slug
    assert run.input_ref["user_id"] is None
    assert run.input_ref["retrieval_contract"] == contract
    assert ctx["workspace_slug"] == workspace.slug
    assert ctx["user_id"] is None
    assert ctx["retrieval_contract"] == contract
    remaining = ctx["_run_deadline_monotonic"] - time.monotonic()
    assert 11.0 < remaining <= 12.0


@pytest.mark.parametrize(
    "trigger",
    ["manual", "chat_agentic", "scheduler", "rerun", "replay"],
)
def test_run_start_binds_every_producer_to_exact_existing_version(
    db_session,
    trigger,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.services.run_engine.engine.settings.agentium_image_revision",
        "d" * 40,
    )
    workspace = _workspace(db_session, f"Version binding {trigger}")
    flow = {
        "schema_version": 3,
        "io_mode": "strict",
        "nodes": [{"id": "audit", "type": "task"}],
        "edges": [],
    }
    system = System(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name=f"Versioned {trigger}",
        objective="test",
        flow_definition=flow,
    )
    started_at = datetime.utcnow() - timedelta(hours=1)
    version = SystemVersion(
        id=str(uuid.uuid4()),
        system_id=system.id,
        workspace_id=workspace.id,
        version_number=1,
        flow_definition={**flow, "edges": []},
        created_at=started_at + timedelta(minutes=30),
        created_by="test",
    )
    run = Run(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        flow_snapshot=(flow if trigger in {"chat_agentic", "rerun", "replay"} else None),
        status="pending",
        started_at=started_at,
        trigger=trigger,
    )
    db_session.add_all([system, version, run])
    db_session.commit()

    _snapshot_run_flow(db_session, run, system)
    db_session.flush()

    assert run.flow_snapshot == flow
    assert run.flow_version_id == version.id
    snapshot_at = run.input_ref["execution"]["snapshot_at"]
    runtime_revision = run.input_ref["execution"]["runtime_revision"]
    assert datetime.fromisoformat(snapshot_at.removesuffix("Z")) > version.created_at
    assert runtime_revision == "d" * 40

    run.status = "hitl_pending"
    _snapshot_run_flow(db_session, run, system, first_start=False)
    assert run.input_ref["execution"]["snapshot_at"] == snapshot_at
    assert run.input_ref["execution"]["runtime_revision"] == runtime_revision
    assert run.flow_version_id == version.id
    assert db_session.query(SystemVersion).filter_by(system_id=system.id).count() == 1


def test_run_start_version_binding_is_history_safe_and_fail_closed(db_session):
    workspace = _workspace(db_session, "Version history")
    foreign_workspace = _workspace(db_session, "Foreign version history")
    bound_policy = ControlPolicy(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name="Bound policy",
        scope="system",
    )
    flow = {"nodes": [{"id": "exact"}], "edges": []}
    system = System(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name="History-safe System",
        objective="test",
        flow_definition=flow,
        control_policy_id=bound_policy.id,
    )
    bound_policy.target_id = system.id
    started_at = datetime.utcnow()
    compatible = SystemVersion(
        id=str(uuid.uuid4()),
        system_id=system.id,
        workspace_id=workspace.id,
        version_number=1,
        flow_definition=flow,
        configuration_snapshot={
            "schema_version": 1,
            "bindings": {"control_policy_id": bound_policy.id},
        },
        created_at=started_at - timedelta(minutes=5),
        created_by="test",
    )
    incompatible_configuration = SystemVersion(
        id=str(uuid.uuid4()),
        system_id=system.id,
        workspace_id=workspace.id,
        version_number=2,
        flow_definition=flow,
        configuration_snapshot={
            "schema_version": 1,
            "bindings": {"control_policy_id": str(uuid.uuid4())},
        },
        created_at=started_at - timedelta(minutes=4),
        created_by="test",
    )
    different_flow = SystemVersion(
        id=str(uuid.uuid4()),
        system_id=system.id,
        workspace_id=workspace.id,
        version_number=3,
        flow_definition={"nodes": [{"id": "different"}], "edges": []},
        created_at=started_at - timedelta(minutes=3),
        created_by="test",
    )
    foreign_version = SystemVersion(
        id=str(uuid.uuid4()),
        system_id=system.id,
        workspace_id=foreign_workspace.id,
        version_number=4,
        flow_definition=flow,
        created_at=started_at - timedelta(minutes=2),
        created_by="test",
    )
    future = SystemVersion(
        id=str(uuid.uuid4()),
        system_id=system.id,
        workspace_id=workspace.id,
        version_number=5,
        flow_definition=flow,
        created_at=started_at + timedelta(days=1),
        created_by="test",
    )
    run = Run(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        status="pending",
        started_at=started_at,
    )
    db_session.add_all(
        [
            bound_policy,
            system,
            compatible,
            incompatible_configuration,
            different_flow,
            foreign_version,
            future,
            run,
        ]
    )
    db_session.commit()

    _snapshot_run_flow(db_session, run, system)
    assert run.flow_version_id is None
    assert run.flow_snapshot == flow


def test_run_version_revalidation_ignores_mutable_current_bindings(db_session):
    workspace = _workspace(db_session, "Immutable version binding")
    policy = ControlPolicy(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name="Initial policy",
        scope="system",
    )
    flow = {"nodes": [{"id": "exact"}], "edges": []}
    system = System(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name="Stable evidence",
        objective="test",
        flow_definition=flow,
        control_policy_id=policy.id,
    )
    policy.target_id = system.id
    version = SystemVersion(
        id=str(uuid.uuid4()),
        system_id=system.id,
        workspace_id=workspace.id,
        version_number=1,
        flow_definition=flow,
        configuration_snapshot={
            "schema_version": 1,
            "bindings": {"control_policy_id": policy.id},
        },
        created_at=datetime.utcnow() - timedelta(minutes=1),
        created_by="test",
    )
    run = Run(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        status="pending",
        started_at=datetime.utcnow() - timedelta(minutes=5),
    )
    db_session.add_all([policy, system, version, run])
    db_session.commit()

    _snapshot_run_flow(db_session, run, system)
    snapshot_at = run.input_ref["execution"]["snapshot_at"]
    assert run.flow_version_id == version.id

    # Current bindings may evolve while a Run waits for HITL.  The already
    # validated link remains historical evidence of the first boundary.
    system.control_policy_id = None
    run.status = "hitl_pending"
    _snapshot_run_flow(db_session, run, system, first_start=False)
    assert run.flow_version_id == version.id
    assert run.input_ref["execution"]["snapshot_at"] == snapshot_at
    assert run.flow_snapshot == flow


def test_run_start_does_not_invent_version_without_exact_match(db_session):
    workspace = _workspace(db_session, "No approximate version")
    system = System(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name="Unversioned execution",
        objective="test",
        flow_definition={"nodes": [{"id": "current"}], "edges": []},
    )
    run = Run(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        status="pending",
        started_at=datetime.utcnow(),
    )
    db_session.add_all([system, run])
    db_session.commit()

    _snapshot_run_flow(db_session, run, system)

    assert run.flow_version_id is None
    assert db_session.query(SystemVersion).filter_by(system_id=system.id).count() == 0
