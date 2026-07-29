import pytest
from fastapi import HTTPException

from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember
from app.services.system_engine_authorization import enforce_system_engine_run


def _subject(db_session, *, suffix: str, role_template: str):
    workspace = Workspace(
        id=f"workspace-engine-auth-{suffix}",
        slug=f"engine-auth-{suffix}",
        name=f"Engine auth {suffix}",
    )
    user = User(id=f"user-engine-auth-{suffix}", username=f"engine-auth-{suffix}")
    membership = WorkspaceMember(
        user_id=user.id,
        workspace_id=workspace.id,
        role="member",
        role_template=role_template,
    )
    system = System(
        id=f"system-engine-auth-{suffix}",
        workspace_id=workspace.id,
        name="Authorized System",
        objective="Exercise the resource-scoped execution boundary",
    )
    db_session.add_all([workspace, user, membership, system])
    db_session.commit()
    return workspace, user, system


def test_shadow_engine_run_keeps_legacy_surface_and_records_the_candidate_denial(db_session):
    workspace, user, system = _subject(
        db_session,
        suffix="shadow",
        role_template="workspace_viewer",
    )
    db_session.add(
        WorkspaceIAMConfig(
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
        )
    )
    db_session.commit()

    resolution = enforce_system_engine_run(
        db_session,
        user=user,
        workspace=workspace,
        system=system,
        source="test.shadow",
    )

    assert resolution.mode == "shadow"
    assert resolution.legacy_allowed is True
    assert resolution.candidate_allowed is False
    assert resolution.effective_allowed is True


def test_attested_engine_run_enforcement_denies_viewer_and_allows_contributor(
    db_session,
    attest_authorization_v2,
):
    denied_workspace, denied_user, denied_system = _subject(
        db_session,
        suffix="denied",
        role_template="workspace_viewer",
    )
    allowed_workspace, allowed_user, allowed_system = _subject(
        db_session,
        suffix="allowed",
        role_template="workspace_contributor",
    )
    for workspace in (denied_workspace, allowed_workspace):
        config = WorkspaceIAMConfig(
            workspace_id=workspace.id,
            version=1,
            role_flags={},
            capability_overrides={
                "authorization_v2": {
                    "policy_version": 2,
                    "default_mode": "compat",
                    "modes": {"system.engine.run": "enforce"},
                }
            },
        )
        db_session.add(config)
        db_session.flush()
        attest_authorization_v2(config, ["system.engine.run"])
    db_session.commit()

    with pytest.raises(HTTPException) as denied:
        enforce_system_engine_run(
            db_session,
            user=denied_user,
            workspace=denied_workspace,
            system=denied_system,
            source="test.denied",
        )
    assert denied.value.status_code == 403

    allowed = enforce_system_engine_run(
        db_session,
        user=allowed_user,
        workspace=allowed_workspace,
        system=allowed_system,
        source="test.allowed",
    )
    assert allowed.mode == "enforce"
    assert allowed.effective_allowed is True


def test_engine_run_authorization_hides_a_foreign_system(db_session):
    workspace, user, _system = _subject(
        db_session,
        suffix="tenant-a",
        role_template="workspace_admin",
    )
    foreign_workspace, _foreign_user, foreign_system = _subject(
        db_session,
        suffix="tenant-b",
        role_template="workspace_admin",
    )

    with pytest.raises(HTTPException) as hidden:
        enforce_system_engine_run(
            db_session,
            user=user,
            workspace=workspace,
            system=foreign_system,
            source="test.foreign",
        )
    assert hidden.value.status_code == 404
    assert foreign_workspace.id != workspace.id
