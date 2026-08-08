"""Authorization and tenant boundaries for the production Agentic System."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, HTTPException
from pydantic import ValidationError

from app.api.v1.endpoints import control_plane, systems
from app.models.context import Context
from app.models.policy import ControlPolicy
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.chat_execution_policy import (
    ANDRITZ_MIGRATION_MARKER,
    ANDRITZ_MIGRATION_REVISION,
)
from app.tests.publication_baseline import LEGACY_FLOW_AUTHORITY


def _workspace(db_session, *, slug: str) -> Workspace:
    row = Workspace(
        id=str(uuid4()),
        name=slug,
        slug=slug,
        settings={"family": "andritz", **LEGACY_FLOW_AUTHORITY},
    )
    db_session.add(row)
    db_session.flush()
    return row


def _user(db_session, *, role: str = "user") -> User:
    token = uuid4().hex
    row = User(
        id=str(uuid4()),
        username=f"systems-boundary-{token}",
        email=f"systems-boundary-{token}@example.invalid",
        role=role,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _managed_system(db_session, workspace: Workspace) -> System:
    row = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Production Agentic chat",
        objective="test",
        status="active",
        settings={"system_type": "chat_agentic"},
        flow_definition={"variant": "chat_agentic_thinking_v1", "nodes": []},
    )
    workspace.settings = {
        "family": "andritz",
        **LEGACY_FLOW_AUTHORITY,
        ANDRITZ_MIGRATION_MARKER: {
            "revision": ANDRITZ_MIGRATION_REVISION,
            "schema": 1,
            "system_id": row.id,
        },
    }
    db_session.add(row)
    db_session.commit()
    return row


def _managed_policy(db_session, workspace: Workspace, system: System) -> ControlPolicy:
    policy = ControlPolicy(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Production membrane",
        scope="system",
        target_id=system.id,
        extra={"membrane_spec": {"version": 1, "inbound": {}}},
    )
    marker = dict(workspace.settings[ANDRITZ_MIGRATION_MARKER])
    marker["control_policy"] = {"id": policy.id}
    workspace.settings = {
        **workspace.settings,
        ANDRITZ_MIGRATION_MARKER: marker,
    }
    db_session.add(policy)
    db_session.commit()
    return policy


@pytest.mark.asyncio
async def test_member_cannot_patch_migration_managed_agentic_system(db_session):
    workspace = _workspace(db_session, slug=f"managed-{uuid4().hex[:8]}")
    user = _user(db_session)
    system = _managed_system(db_session, workspace)

    with pytest.raises(HTTPException) as exc_info:
        await systems.update_system(
            system.id,
            systems.SystemUpdate(name="shadow mutation"),
            systems.SystemUpdateOptions(),
            workspace,
            user,
            db_session,
        )

    assert exc_info.value.status_code == 403
    db_session.refresh(system)
    assert system.name == "Production Agentic chat"


@pytest.mark.asyncio
async def test_member_cannot_create_shadow_canonical_agentic_identity(db_session):
    workspace = _workspace(db_session, slug=f"reserved-{uuid4().hex[:8]}")
    user = _user(db_session)
    _managed_system(db_session, workspace)

    with pytest.raises(HTTPException) as exc_info:
        await systems.create_system(
            systems.SystemCreate(
                name="Shadow Agentic chat",
                settings={"system_type": "chat_agentic"},
                flow_definition={"variant": "chat_agentic_thinking_v1", "nodes": []},
                status="active",
            ),
            workspace,
            user,
            db_session,
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_generic_system_writes_cannot_forge_or_erase_rollout_authority(
    db_session,
):
    workspace = _workspace(db_session, slug=f"rollout-authority-{uuid4().hex[:8]}")
    admin = _user(db_session, role="admin")
    rollout_state = {
        "schema_version": 1,
        "prepared": {"system_id": "system-id"},
        "proof_window": None,
        "activations": [],
        "deactivations": [],
        "policy_transitions": [],
    }
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Rollout-owned System",
        objective="test",
        settings={
            "experience": {
                "system_360_canary": "v1",
                "value_loop_canary": "v1",
                "ordinary": "keep-if-requested",
            },
            "_lot6_system360_rollout_v1": {"schema_version": 1},
            "_lot7_projection_rollout_v1": {"schema_version": 1},
            "_lot8_value_loop_rollout_v1": rollout_state,
            "ordinary": {"before": True},
        },
        flow_definition={},
    )
    db_session.add(system)
    db_session.commit()

    attacks = (
        {"_lot8_value_loop_rollout_v1": {**rollout_state, "proof_window": {}}},
        {"_lot7_projection_rollout_v1": {"schema_version": 2}},
        {"_lot6_system360_rollout_v1": {}},
        {"experience": {"value_loop_canary": "v2"}},
        {"experience": {"system_360_canary": "forged"}},
    )
    for payload in attacks:
        with pytest.raises(HTTPException) as exc_info:
            await systems.update_system(
                system.id,
                systems.SystemUpdate(settings=payload),
                systems.SystemUpdateOptions(),
                workspace,
                admin,
                db_session,
            )
        assert exc_info.value.status_code == 409

    await systems.update_system(
        system.id,
        systems.SystemUpdate(
            settings={
                "ordinary": {"after": True},
                "experience": {"ordinary": "changed"},
            }
        ),
        systems.SystemUpdateOptions(),
        workspace,
        admin,
        db_session,
    )
    db_session.refresh(system)
    assert system.settings["ordinary"] == {"after": True}
    assert system.settings["experience"] == {
        "ordinary": "changed",
        "system_360_canary": "v1",
        "value_loop_canary": "v1",
    }
    assert system.settings["_lot6_system360_rollout_v1"] == {"schema_version": 1}
    assert system.settings["_lot7_projection_rollout_v1"] == {"schema_version": 1}
    assert system.settings["_lot8_value_loop_rollout_v1"] == rollout_state


@pytest.mark.asyncio
async def test_generic_system_create_rejects_rollout_markers(db_session):
    workspace = _workspace(db_session, slug=f"rollout-create-{uuid4().hex[:8]}")
    admin = _user(db_session, role="admin")

    for settings_payload in (
        {"experience": {"value_loop_canary": "v1"}},
        {"experience": {"system_360_canary": "v1"}},
        {"_lot8_value_loop_rollout_v1": {"schema_version": 1}},
    ):
        with pytest.raises(HTTPException) as exc_info:
            await systems.create_system(
                systems.SystemCreate(
                    name="Forged rollout System",
                    settings=settings_payload,
                ),
                workspace,
                admin,
                db_session,
            )
        assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_family_drift_does_not_release_managed_system_or_policy_admin_boundary(db_session):
    workspace = _workspace(db_session, slug=f"family-drift-{uuid4().hex[:8]}")
    member = _user(db_session)
    system = _managed_system(db_session, workspace)
    policy = _managed_policy(db_session, workspace, system)
    drifted = dict(workspace.settings)
    drifted["family"] = "generic"
    workspace.settings = drifted
    db_session.commit()

    with pytest.raises(HTTPException) as system_error:
        await systems.update_system(
            system.id,
            systems.SystemUpdate(name="family bypass"),
            systems.SystemUpdateOptions(),
            workspace,
            member,
            db_session,
        )
    with pytest.raises(HTTPException) as policy_error:
        await control_plane.update_policy(
            policy.id,
            control_plane.ControlPolicyBody(name="family bypass"),
            workspace,
            member,
            db_session,
        )

    assert system_error.value.status_code == 403
    assert policy_error.value.status_code == 403


@pytest.mark.asyncio
async def test_family_drift_does_not_release_reserved_agentic_identity(db_session):
    workspace = _workspace(db_session, slug=f"reserved-drift-{uuid4().hex[:8]}")
    member = _user(db_session)
    _managed_system(db_session, workspace)
    drifted = dict(workspace.settings)
    drifted["family"] = "generic"
    workspace.settings = drifted
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await systems.create_system(
            systems.SystemCreate(
                name="Shadow after family drift",
                settings={"system_type": "chat_agentic"},
                flow_definition={"variant": "chat_agentic_thinking_v1", "nodes": []},
                status="active",
            ),
            workspace,
            member,
            db_session,
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_system_cannot_bind_control_policy_from_another_workspace(db_session):
    workspace = _workspace(db_session, slug=f"policy-owner-{uuid4().hex[:8]}")
    other = _workspace(db_session, slug=f"policy-other-{uuid4().hex[:8]}")
    user = _user(db_session)
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Ordinary System",
        objective="test",
        settings={},
        flow_definition={},
    )
    foreign_policy = ControlPolicy(
        id=str(uuid4()),
        workspace_id=other.id,
        name="Foreign policy",
        scope="system",
        target_id=system.id,
    )
    db_session.add_all([system, foreign_policy])
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await systems.update_system(
            system.id,
            systems.SystemUpdate(control_policy_id=foreign_policy.id),
            systems.SystemUpdateOptions(),
            workspace,
            user,
            db_session,
        )

    assert exc_info.value.status_code == 400
    db_session.refresh(system)
    assert system.control_policy_id is None


@pytest.mark.asyncio
async def test_system_create_and_update_reject_context_from_another_workspace(db_session):
    workspace = _workspace(db_session, slug=f"context-owner-{uuid4().hex[:8]}")
    other = _workspace(db_session, slug=f"context-other-{uuid4().hex[:8]}")
    admin = _user(db_session, role="admin")
    foreign_context = Context(
        id=str(uuid4()),
        workspace_id=other.id,
        name="Foreign business context",
        business_constraints={"tenant_secret": "must-not-cross"},
    )
    local_system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Local System",
        objective="test",
        settings={},
        flow_definition={},
    )
    db_session.add_all([foreign_context, local_system])
    db_session.commit()

    with pytest.raises(HTTPException) as create_error:
        await systems.create_system(
            systems.SystemCreate(
                name="Cross-tenant Context System",
                context_id=foreign_context.id,
            ),
            workspace,
            admin,
            db_session,
        )
    assert create_error.value.status_code == 400

    with pytest.raises(HTTPException) as update_error:
        await systems.update_system(
            local_system.id,
            systems.SystemUpdate(context_id=foreign_context.id),
            systems.SystemUpdateOptions(),
            workspace,
            admin,
            db_session,
        )
    assert update_error.value.status_code == 400
    db_session.refresh(local_system)
    assert local_system.context_id is None


@pytest.mark.asyncio
async def test_member_cannot_trigger_migration_managed_agentic_system(db_session):
    workspace = _workspace(db_session, slug=f"trigger-member-{uuid4().hex[:8]}")
    user = _user(db_session)
    system = _managed_system(db_session, workspace)

    with pytest.raises(HTTPException) as exc_info:
        await systems.trigger_run(
            system.id,
            systems.RunCreate(
                input_ref={"query": "resume BCX200"},
                expected_flow_sha256=systems._flow_sha256(system.flow_definition),
            ),
            BackgroundTasks(),
            workspace,
            user,
            db_session,
        )

    assert exc_info.value.status_code == 403
    assert db_session.query(systems.Run).filter(systems.Run.system_id == system.id).count() == 0


@pytest.mark.asyncio
async def test_global_admin_can_trigger_migration_managed_agentic_system(db_session):
    workspace = _workspace(db_session, slug=f"trigger-admin-{uuid4().hex[:8]}")
    admin = _user(db_session, role="admin")
    system = _managed_system(db_session, workspace)

    result = await systems.trigger_run(
        system.id,
        systems.RunCreate(
            input_ref={"query": "resume BCX200"},
            expected_flow_sha256=systems._flow_sha256(system.flow_definition),
        ),
        BackgroundTasks(),
        workspace,
        admin,
        db_session,
    )

    assert result["system_id"] == system.id
    created = db_session.query(systems.Run).filter(systems.Run.id == result["id"]).one()
    assert created.initiated_by_user_id == admin.id


def test_run_create_forbids_ambiguous_http_shapes() -> None:
    flow_sha256 = "a" * 64
    with pytest.raises(ValidationError):
        systems.RunCreate(input_ref={}, expected_flow_sha256=flow_sha256, _debug={})
    with pytest.raises(ValidationError):
        systems.RunCreate(
            input_ref={"_debug": {"mode": "step", "unknown": True}},
            expected_flow_sha256=flow_sha256,
        )
    with pytest.raises(ValidationError):
        systems.RunCreate(input_ref={})


@pytest.mark.asyncio
async def test_run_post_freezes_hash_flow_and_runtime_before_worker_start(db_session):
    workspace = _workspace(db_session, slug=f"trigger-snapshot-{uuid4().hex[:8]}")
    admin = _user(db_session, role="admin")
    system = _managed_system(db_session, workspace)
    accepted_flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "source", "kind": "source"},
            {"id": "route", "kind": "decision", "config": {"branches": []}},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [],
    }
    system.flow_definition = accepted_flow
    db_session.commit()
    accepted_sha256 = systems._flow_sha256(accepted_flow)

    result = await systems.trigger_run(
        system.id,
        systems.RunCreate(
            input_ref={
                "query": "resume BCX200",
                "_debug": {"mode": "step", "breakpoints": ["route"]},
                "execution": {
                    "flow_sha256": "f" * 64,
                    "runtime_mode": "sequential_legacy",
                },
            },
            expected_flow_sha256=accepted_sha256,
        ),
        BackgroundTasks(),
        workspace,
        admin,
        db_session,
    )

    created = db_session.query(systems.Run).filter(systems.Run.id == result["id"]).one()
    assert created.flow_snapshot == accepted_flow
    assert created.input_ref["_debug"] == {
        "mode": "step",
        "breakpoints": ["route"],
    }
    assert created.input_ref["execution"]["flow_sha256"] == accepted_sha256
    assert created.input_ref["execution"]["runtime_mode"] == "dag_overlay"
    assert result["runtime_mode"] == "dag_overlay"

    system.flow_definition = {"schema_version": 3, "nodes": [], "edges": []}
    db_session.commit()
    db_session.refresh(created)
    assert created.flow_snapshot == accepted_flow


@pytest.mark.asyncio
async def test_run_post_rejects_stale_hash_without_creating_run(db_session):
    workspace = _workspace(db_session, slug=f"trigger-stale-{uuid4().hex[:8]}")
    admin = _user(db_session, role="admin")
    system = _managed_system(db_session, workspace)

    with pytest.raises(HTTPException) as exc_info:
        await systems.trigger_run(
            system.id,
            systems.RunCreate(
                input_ref={"query": "stale"},
                expected_flow_sha256="0" * 64,
            ),
            BackgroundTasks(),
            workspace,
            admin,
            db_session,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "RUN_FLOW_SHA256_MISMATCH"
    assert db_session.query(systems.Run).filter(systems.Run.system_id == system.id).count() == 0


@pytest.mark.asyncio
async def test_run_post_rejects_debug_for_sequential_legacy(db_session):
    workspace = _workspace(db_session, slug=f"trigger-debug-{uuid4().hex[:8]}")
    admin = _user(db_session, role="admin")
    system = _managed_system(db_session, workspace)

    with pytest.raises(HTTPException) as exc_info:
        await systems.trigger_run(
            system.id,
            systems.RunCreate(
                input_ref={"_debug": {"mode": "step"}},
                expected_flow_sha256=systems._flow_sha256(system.flow_definition),
            ),
            BackgroundTasks(),
            workspace,
            admin,
            db_session,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "RUN_DEBUG_REQUIRES_DAG"
    assert db_session.query(systems.Run).filter(systems.Run.system_id == system.id).count() == 0


@pytest.mark.asyncio
async def test_public_system_run_cannot_forge_reserved_chat_trigger(db_session):
    workspace = _workspace(db_session, slug=f"trigger-reserved-{uuid4().hex[:8]}")
    admin = _user(db_session, role="admin")
    system = _managed_system(db_session, workspace)

    with pytest.raises(HTTPException) as exc_info:
        await systems.trigger_run(
            system.id,
            systems.RunCreate(
                trigger="chat_agentic",
                input_ref={"chat_adapter": {"assistant_message_id": "victim"}},
                expected_flow_sha256=systems._flow_sha256(system.flow_definition),
            ),
            BackgroundTasks(),
            workspace,
            admin,
            db_session,
        )

    assert exc_info.value.status_code == 400
    assert db_session.query(systems.Run).filter(systems.Run.system_id == system.id).count() == 0


@pytest.mark.asyncio
async def test_member_cannot_patch_migration_managed_control_policy(db_session):
    workspace = _workspace(db_session, slug=f"policy-member-{uuid4().hex[:8]}")
    member = _user(db_session)
    system = _managed_system(db_session, workspace)
    policy = _managed_policy(db_session, workspace, system)

    with pytest.raises(HTTPException) as exc_info:
        await control_plane.update_policy(
            policy.id,
            control_plane.ControlPolicyBody(name="Sabotaged membrane"),
            workspace,
            member,
            db_session,
        )

    assert exc_info.value.status_code == 403
    db_session.refresh(policy)
    assert policy.name == "Production membrane"


@pytest.mark.asyncio
async def test_global_admin_can_patch_migration_managed_control_policy(db_session):
    workspace = _workspace(db_session, slug=f"policy-admin-{uuid4().hex[:8]}")
    admin = _user(db_session, role="admin")
    system = _managed_system(db_session, workspace)
    policy = _managed_policy(db_session, workspace, system)

    result = await control_plane.update_policy(
        policy.id,
        control_plane.ControlPolicyBody(name="Reviewed membrane"),
        workspace,
        admin,
        db_session,
    )

    assert result["name"] == "Reviewed membrane"
