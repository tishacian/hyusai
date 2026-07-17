from __future__ import annotations

import time
import uuid

from app.models.capability import Capability
from app.models.policy import AdaptivePolicy, ControlPolicy
from app.models.run import Run
from app.models.system import System
from app.models.workspace import Workspace
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
