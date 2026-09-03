"""The workspace rollout service: generic invariants, Andritz as a plugin."""

from __future__ import annotations

import json
from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import chat_execution as chat_execution_endpoint
from app.models.audit import AuditLog
from app.models.knowledge_collection import KnowledgeCollection
from app.models.policy import ControlPolicy
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services import chat_execution_policy as policy
from app.services import chat_execution_rollout as rollout
from app.services.chat_agentic_contract import ANDRITZ_MIGRATION_FLOW_REVISION
from app.services.skills_registry.seed import seed_skills_and_capabilities
from app.services.systems import agentic_chat_bootstrap as boot
from app.services.systems import agentic_chat_template as tpl


@pytest.fixture(autouse=True)
def _kill_switch_on(monkeypatch):
    monkeypatch.setattr(rollout.app_settings, "enable_agentic_chat", True)
    monkeypatch.setattr(policy.settings, "enable_agentic_chat", True)


def _provisioned_workspace(db_session, *, slug: str, settings: dict | None = None) -> Workspace:
    workspace = Workspace(id=f"ws-{slug}", name=slug.upper(), slug=slug, settings=settings or {})
    db_session.add(workspace)
    db_session.flush()
    seed_skills_and_capabilities(db_session)
    assert boot.ensure_workspace_agentic_chat_system_default(db_session, workspace.id) is not None
    db_session.refresh(workspace)
    return workspace


def _audit_rows(db_session, workspace_id: str) -> list[AuditLog]:
    return (
        db_session.query(AuditLog)
        .filter(AuditLog.workspace_id == workspace_id, AuditLog.event_type == rollout.AUDIT_EVENT_TYPE)
        .all()
    )


def test_a_generic_workspace_rolls_out_and_the_router_follows(db_session):
    workspace = _provisioned_workspace(db_session, slug="acme")
    before = rollout.describe_chat_execution(db_session, workspace)
    assert (before.mode, before.percentage, before.managed_by) == ("hybrid", 0, "workspace")
    assert before.rollout_ready is True
    assert before.contract_valid is True
    assert before.target_system_name == boot.WORKSPACE_AGENTIC_CHAT_SYSTEM_NAME

    dry = rollout.set_chat_execution(
        db_session, workspace, mode="agentic_default", percentage=100, actor="ops", dry_run=True
    )
    assert dry.changed is True and dry.audit_event_id is None
    db_session.refresh(workspace)
    assert workspace.settings["chat_execution"]["rollout"]["percentage"] == 0

    state = rollout.set_chat_execution(
        db_session, workspace, mode="agentic_default", percentage=100, actor="ops"
    )
    db_session.commit()
    db_session.refresh(workspace)
    assert (state.mode, state.percentage, state.changed) == ("agentic_default", 100, True)
    assert workspace.settings["chat_execution"] == {
        "version": 1,
        "mode": "agentic_default",
        "target": {"system_type": "chat_agentic", "variant": "chat_agentic_thinking_v1"},
        "fallback": "classic",
        "rollout": {"percentage": 100, "salt": boot.DEFAULT_CHAT_EXECUTION_SALT},
    }
    rows = _audit_rows(db_session, workspace.id)
    assert len(rows) == 1 and rows[0].id == state.audit_event_id
    assert rows[0].details["previous_percentage"] == 0
    assert rows[0].details["managed_by"] == "workspace"
    assert rows[0].agent_id == state.target_system_id

    decision = policy.resolve_chat_execution(
        db_session,
        workspace=workspace,
        requested_system_id=None,
        session_id="s",
        answer_profile="precise_fact",
    )
    assert (decision.route, decision.reason) == ("agentic", "policy_agentic_default")
    assert decision.executor_system.id == state.target_system_id

    # Back to classic: accepted, and the salt survives so cohorts stay stable.
    back = rollout.set_chat_execution(db_session, workspace, mode="classic", percentage=0, actor="ops")
    db_session.commit()
    db_session.refresh(workspace)
    assert back.mode == "classic"
    assert workspace.settings["chat_execution"]["rollout"]["salt"] == boot.DEFAULT_CHAT_EXECUTION_SALT
    assert len(_audit_rows(db_session, workspace.id)) == 2


def test_the_generic_invariants_block_a_rollout_but_never_a_rollback(db_session, monkeypatch):
    workspace = _provisioned_workspace(db_session, slug="acme-guard")

    monkeypatch.setattr(rollout.app_settings, "enable_agentic_chat", False)
    with pytest.raises(rollout.RolloutInvariantError, match="ENABLE_AGENTIC_CHAT"):
        rollout.set_chat_execution(db_session, workspace, mode="hybrid", percentage=10, actor="ops")
    assert "ENABLE_AGENTIC_CHAT is disabled (master kill switch)" in (
        rollout.describe_chat_execution(db_session, workspace).invariants
    )
    monkeypatch.setattr(rollout.app_settings, "enable_agentic_chat", True)

    # Two active targets: ambiguous.
    twin = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="twin",
        objective="x",
        settings={"system_type": "chat_agentic"},
        flow_definition={"variant": "chat_agentic_thinking_v1"},
        status="active",
    )
    db_session.add(twin)
    db_session.flush()
    with pytest.raises(rollout.RolloutInvariantError, match="exactly one is required"):
        rollout.set_chat_execution(db_session, workspace, mode="hybrid", percentage=10, actor="ops")
    twin.status = "retired"
    db_session.flush()

    # Drifted flow: the contract no longer matches the declared revision.
    target = db_session.get(System, rollout.describe_chat_execution(db_session, workspace).target_system_id)
    pristine = deepcopy(target.flow_definition)
    drifted = deepcopy(pristine)
    drifted["nodes"] = [n for n in drifted["nodes"] if n["id"] != "task.self_correct"]
    target.flow_definition = drifted
    db_session.flush()
    with pytest.raises(rollout.RolloutInvariantError, match="does not match its declared contract"):
        rollout.set_chat_execution(db_session, workspace, mode="hybrid", percentage=10, actor="ops")
    # ... yet rolling back to 0 % is accepted and records the drift.
    state = rollout.set_chat_execution(db_session, workspace, mode="classic", percentage=0, actor="ops")
    assert state.changed is True
    assert any("declared contract" in item for item in state.invariants)
    row = _audit_rows(db_session, workspace.id)[-1]
    assert row.severity == "warning"
    assert row.details["validation_mode"] == "risk_reduction_rollback"
    target.flow_definition = pristine
    db_session.flush()

    with pytest.raises(ValueError):
        rollout.set_chat_execution(db_session, workspace, mode="turbo", percentage=10, actor="ops")
    with pytest.raises(ValueError):
        rollout.set_chat_execution(db_session, workspace, mode="hybrid", percentage=101, actor="ops")


def test_a_bound_collection_must_be_ready_before_the_rollout(db_session):
    workspace = _provisioned_workspace(
        db_session,
        slug="hydro",
        settings={
            "family": "industrial",
            "knowledge_scopes": [{"key": "docs", "is_default": True, "collection_slugs": ["hydro-manuals"]}],
        },
    )
    state = rollout.describe_chat_execution(db_session, workspace)
    assert state.collection_slug == "hydro-manuals"
    assert "bound collection hydro-manuals is missing" in state.invariants
    with pytest.raises(rollout.RolloutInvariantError, match="hydro-manuals is missing"):
        rollout.set_chat_execution(db_session, workspace, mode="hybrid", percentage=5, actor="ops")

    collection = KnowledgeCollection(
        id=str(uuid4()),
        workspace_id=workspace.id,
        slug="hydro-manuals",
        name="Hydro manuals",
        status="ready",
        chunk_count=12,
        vector_collection_name="ws-hydro__hydro-manuals",
        artifact_prefix="ws-hydro/hydro-manuals",
    )
    db_session.add(collection)
    db_session.flush()
    ready = rollout.set_chat_execution(db_session, workspace, mode="hybrid", percentage=5, actor="ops")
    assert ready.collection_status == "ready" and ready.collection_chunk_count == 12
    assert ready.rollout_ready is True


def test_andritz_is_a_plugin_mode_is_immutable_and_the_marker_rules(db_session):
    artifact = json.load(open(tpl.ARTIFACT_PATH, encoding="utf-8"))
    system = System(
        id="874211ee-1111-0000-0000-000000000000",
        workspace_id="ws-andritz-r",
        name="Andritz Chat Agentic",
        objective="x",
        flow_definition=deepcopy(artifact["flow_definition"]),
        settings={
            "system_type": "chat_agentic",
            "variant": "chat_agentic_thinking_v1",
            "flow_revision": ANDRITZ_MIGRATION_FLOW_REVISION,
            "retrieval_contract": deepcopy(policy.ANDRITZ_RETRIEVAL_CONTRACT),
        },
        execution_profile={"max_runtime_s": 40},
        status="active",
        created_by="migration",
    )
    membrane = ControlPolicy(
        id="cp-andritz-r",
        workspace_id="ws-andritz-r",
        name="m",
        scope="system",
        target_id=system.id,
        extra={"membrane_spec": artifact["membrane_spec"]},
    )
    system.control_policy_id = membrane.id
    andritz_policy = {
        "version": 1,
        "mode": "agentic_default",
        "target": {"system_type": "chat_agentic", "variant": "chat_agentic_thinking_v1"},
        "fallback": "classic",
        "rollout": {"percentage": 0, "salt": "andritz-agentic-v1"},
    }
    # A trusted-identity marker without the strict restore snapshots: enough
    # for rollback, not for a rollout above zero (exactly the 059 contract).
    workspace = Workspace(
        id="ws-andritz-r",
        name="Andritz",
        slug="andritz-r",
        settings={
            "family": "andritz",
            "chat_execution": andritz_policy,
            policy.ANDRITZ_MIGRATION_MARKER: {
                "revision": policy.ANDRITZ_MIGRATION_REVISION,
                "schema": 1,
                "system_id": system.id,
                "control_policy": {"id": membrane.id},
            },
        },
    )
    db_session.add_all([workspace, membrane, system])
    db_session.flush()

    state = rollout.describe_chat_execution(db_session, workspace)
    assert state.managed_by == "andritz_migration_059"
    assert state.target_system_id == system.id
    assert any("migration marker" in item for item in state.invariants)

    with pytest.raises(rollout.RolloutInvariantError, match="only the rollout percentage"):
        rollout.set_chat_execution(db_session, workspace, mode="hybrid", percentage=0, actor="ops")
    with pytest.raises(rollout.RolloutInvariantError, match="migration marker"):
        rollout.set_chat_execution(db_session, workspace, mode="agentic_default", percentage=10, actor="ops")

    rolled_back = rollout.set_chat_execution(
        db_session, workspace, mode="agentic_default", percentage=0, actor="ops"
    )
    assert rolled_back.changed is False
    assert rolled_back.percentage == 0
    db_session.refresh(workspace)
    assert workspace.settings["chat_execution"] == andritz_policy
    row = _audit_rows(db_session, workspace.id)[-1]
    assert row.details["migration_revision"] == policy.ANDRITZ_MIGRATION_REVISION
    assert row.details["validation_mode"] == "risk_reduction_rollback"


def _client(db_session, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(chat_execution_endpoint.router, prefix="/api/v1/workspaces")
    app.dependency_overrides[chat_execution_endpoint.get_current_user] = lambda: user
    app.dependency_overrides[chat_execution_endpoint.get_db] = lambda: db_session
    return TestClient(app)


def _member(db_session, workspace: Workspace, *, role: str, role_template: str) -> User:
    user = User(id=str(uuid4()), username=f"u-{uuid4().hex[:6]}", email=f"{uuid4().hex[:6]}@x.test", is_active=True)
    db_session.add(user)
    db_session.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=role, role_template=role_template)
    )
    db_session.commit()
    return user


def test_the_api_reads_for_members_and_writes_for_admins_only(db_session):
    workspace = _provisioned_workspace(db_session, slug="acme-api")
    db_session.commit()
    viewer = _member(db_session, workspace, role="member", role_template="workspace_contributor")
    admin = _member(db_session, workspace, role="admin", role_template="workspace_admin")

    res = _client(db_session, viewer).get(f"/api/v1/workspaces/{workspace.slug}/chat-execution")
    assert res.status_code == 200
    assert res.json()["mode"] == "hybrid"
    assert res.json()["rollout_ready"] is True
    assert res.json()["modes"] == ["agentic_default", "classic", "hybrid"]

    res = _client(db_session, viewer).put(
        f"/api/v1/workspaces/{workspace.slug}/chat-execution",
        json={"mode": "agentic_default", "percentage": 50},
    )
    assert res.status_code == 403

    res = _client(db_session, admin).put(
        f"/api/v1/workspaces/{workspace.slug}/chat-execution",
        json={"mode": "agentic_default", "percentage": 50},
    )
    assert res.status_code == 200, res.text
    assert (res.json()["mode"], res.json()["percentage"]) == ("agentic_default", 50)
    db_session.refresh(workspace)
    assert workspace.settings["chat_execution"]["rollout"]["percentage"] == 50

    res = _client(db_session, admin).put(
        f"/api/v1/workspaces/{workspace.slug}/chat-execution",
        json={"mode": "turbo", "percentage": 50},
    )
    assert res.status_code == 422

    twin = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="twin",
        objective="x",
        settings={"system_type": "chat_agentic"},
        flow_definition={"variant": "chat_agentic_thinking_v1"},
        status="active",
    )
    db_session.add(twin)
    db_session.commit()
    res = _client(db_session, admin).put(
        f"/api/v1/workspaces/{workspace.slug}/chat-execution",
        json={"mode": "hybrid", "percentage": 10},
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "CHAT_EXECUTION_ROLLOUT_BLOCKED"
