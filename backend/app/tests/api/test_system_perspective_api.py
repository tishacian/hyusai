"""API contract for the gated, workspace-scoped System 360 projection."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.v1.endpoints import systems
from app.models.audit import AuditLog
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(systems.router, prefix="/systems")
    app.dependency_overrides[systems.get_current_workspace] = lambda: workspace
    app.dependency_overrides[systems.get_current_user] = lambda: user
    app.dependency_overrides[systems.get_db] = lambda: db_session
    return TestClient(app)


def _seed(db_session) -> tuple[Workspace, Workspace, User, System, System]:
    enabled = {
        "features": {
            "cockpit_router_axes_v4": True,
            "system_360_projection_v1": True,
        }
    }
    workspace = Workspace(id="ws-perspective-api", slug="perspective-api", name="Perspective", settings=enabled)
    other = Workspace(id="ws-perspective-other", slug="perspective-other", name="Other", settings=enabled)
    user = User(
        id="user-perspective-api",
        username="perspective-api@test",
        email="perspective-api@test",
        role="admin",
    )
    membership = WorkspaceMember(
        user_id=user.id,
        workspace_id=workspace.id,
        role="owner",
        role_template="workspace_owner",
    )
    system = System(
        id="system-perspective-api",
        workspace_id=workspace.id,
        name="Marked System",
        objective="Give four honest readings of the same object.",
        status="active",
        settings={"experience": {"system_360_canary": "v1"}},
        flow_definition={"schema_version": 3, "io_mode": "strict", "nodes": [], "edges": []},
    )
    foreign = System(
        id="system-perspective-foreign",
        workspace_id=other.id,
        name="Foreign System",
        status="active",
        settings={"experience": {"system_360_canary": "v1"}},
    )
    db_session.add_all([workspace, other, user, membership, system, foreign])
    db_session.commit()
    return workspace, other, user, system, foreign


def test_perspective_returns_requested_lens_for_marked_system(db_session):
    workspace, _other, user, system, _foreign = _seed(db_session)
    response = _client(db_session, workspace, user).get(
        f"/systems/{system.id}/perspective",
        params={"lens": "build", "window": "7d"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["lens"] == "build"
    assert payload["window"] == "7d"
    assert payload["identity"]["workspace_id"] == workspace.id
    assert payload["identity"]["system_id"] == system.id


@pytest.mark.parametrize("missing", [False, True])
def test_unverifiable_published_mandate_returns_explicit_unavailable(db_session, missing):
    workspace, _, user, system, _ = _seed(db_session)
    if not missing:
        db_session.add(SystemVersion(id="invalid-publication", system_id=system.id,
                        workspace_id=workspace.id, version_number=1, flow_definition={},
                        execution_contract={"control_policy_snapshot": {"state": "forged"}}))
        db_session.flush()
    system.published_flow_version_id = "invalid-publication"
    db_session.commit()
    response = _client(db_session, workspace, user).get(
        f"/systems/{system.id}/perspective", params={"lens": "govern"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "published_mandate_unavailable"
    assert "could not be verified" in response.json()["detail"]["message"]
    assert "forged" not in response.text


def test_system_detail_and_perspective_share_canonical_read_decision(
    db_session,
    monkeypatch,
):
    workspace, _other, user, system, _foreign = _seed(db_session)
    calls: list[tuple[str, str, bool]] = []

    def _record(*_args, **kwargs):
        calls.append(
            (
                kwargs["resource_kind"],
                kwargs["action"],
                kwargs["legacy_allowed"],
            )
        )

    monkeypatch.setattr(systems, "enforce_action", _record)
    client = _client(db_session, workspace, user)

    assert client.get(f"/systems/{system.id}").status_code == 200
    assert client.get(
        f"/systems/{system.id}/perspective",
        params={"lens": "govern"},
    ).status_code == 200
    assert calls == [
        ("system", "read", True),
        ("system", "read", True),
    ]


def test_perspective_is_fail_closed_across_workspaces(db_session):
    workspace, _other, user, _system, foreign = _seed(db_session)
    response = _client(db_session, workspace, user).get(
        f"/systems/{foreign.id}/perspective",
        params={"lens": "operate"},
    )

    assert response.status_code == 404


def test_perspective_validates_lens_and_window(db_session):
    workspace, _other, user, system, _foreign = _seed(db_session)
    client = _client(db_session, workspace, user)

    assert client.get(
        f"/systems/{system.id}/perspective",
        params={"lens": "hypervisor"},
    ).status_code == 422
    assert client.get(
        f"/systems/{system.id}/perspective",
        params={"lens": "build", "window": "365d"},
    ).status_code == 422


def test_perspective_requires_both_workspace_flags_and_system_marker(db_session):
    workspace, _other, user, system, _foreign = _seed(db_session)
    client = _client(db_session, workspace, user)

    workspace.settings = {"features": {"cockpit_router_axes_v4": True}}
    db_session.commit()
    assert client.get(
        f"/systems/{system.id}/perspective",
        params={"lens": "build"},
    ).status_code == 404


def test_patch_audits_only_changed_field_names(db_session):
    workspace, _other, user, system, _foreign = _seed(db_session)
    response = _client(db_session, workspace, user).patch(
        f"/systems/{system.id}",
        json={
            "objective": "Updated objective",
            "settings": {
                "experience": {"system_360_canary": "v1"},
                "private_note": "must-never-enter-audit",
            },
        },
    )

    assert response.status_code == 200
    event = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.workspace_id == workspace.id,
            AuditLog.event_type == "system.updated",
            AuditLog.agent_id == system.id,
        )
        .one()
    )
    assert event.actor == user.email
    assert event.details == {
        "system_id": system.id,
        "fields": ["objective", "settings"],
    }
    assert "must-never-enter-audit" not in str(event.details)


def test_system_govern_reports_granular_v2_modes_over_real_legacy_decisions(
    db_session,
    attest_authorization_v2,
):
    workspace, _other, user, system, _foreign = _seed(db_session)
    user.role = None
    membership = db_session.query(WorkspaceMember).filter_by(
        workspace_id=workspace.id,
        user_id=user.id,
    ).one()
    membership.role = "member"
    membership.role_template = "workspace_viewer"
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=1,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {"system.engine.run": "shadow"},
            }
        },
        updated_by_user_id=user.id,
    )
    db_session.add(config)
    db_session.commit()
    client = _client(db_session, workspace, user)

    payload = client.get(
        f"/systems/{system.id}/perspective",
        params={"lens": "govern"},
    ).json()
    actions = payload["facets"]["overview"]["blocks"][0]["facts"][1]["value"]
    engine = actions["system.engine.run"]
    assert engine["mode"] == "shadow"
    assert engine["legacy_allowed"] is True
    assert engine["candidate_allowed"] is False
    assert engine["effective_allowed"] is True
    assert actions["system.admin"]["legacy_allowed"] is True
    assert actions["system.admin"]["effective_allowed"] is True

    config.capability_overrides = {
        "authorization_v2": {
            "policy_version": 2,
            "default_mode": "compat",
            "modes": {"system.engine.run": "enforce"},
        }
    }
    attest_authorization_v2(config, ["system.engine.run"])
    db_session.commit()
    enforced = client.get(
        f"/systems/{system.id}/perspective",
        params={"lens": "govern"},
    ).json()
    actions = enforced["facets"]["overview"]["blocks"][0]["facts"][1]["value"]
    assert actions["system.engine.run"]["mode"] == "enforce"
    assert actions["system.engine.run"]["effective_allowed"] is False
    assert actions["system.engine.run"]["allowed"] is False
