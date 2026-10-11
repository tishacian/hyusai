"""Shared workspace, System and workspace-application vocabularies."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.v1.endpoints.auth import WorkspaceModeUpdate, WorkspaceUpdate
from app.api.v1.endpoints.systems import SystemCreate, SystemUpdate
from app.core.auth import _ensure_personal_workspace
from app.models.system import System
from app.models.user import User
from app.models.workspace import (
    Workspace,
    WorkspaceMember,
    WorkspaceMemberAppEntitlement,
)
from app.schemas.canonical import (
    ExecutionMode,
    SystemStatus,
    WorkspaceApp,
    WorkspaceFamily,
    WorkspaceMode,
)
from app.services.iam.app_entitlements import BUSINESS_APP_KEYS


def _check_names(model) -> set[str]:
    return {
        constraint.name for constraint in model.__table__.constraints if constraint.name is not None
    }


def test_canonical_enum_values_are_stable():
    assert tuple(mode.value for mode in WorkspaceMode) == (
        "builder",
        "operator",
        "executive",
        "demo",
        "portfolio",
    )
    assert tuple(status.value for status in SystemStatus) == (
        "draft",
        "active",
        "paused",
        "retired",
    )
    assert tuple(family.value for family in WorkspaceFamily) == (
        "andritz",
        "industrial",
        "sentinel_ci",
        "generic",
    )
    assert tuple(mode.value for mode in ExecutionMode) == (
        "real_time_decision",
        "batch_processing",
        "event_driven_automation",
        "continuous_monitoring",
        "human_augmented",
    )
    assert tuple(app.value for app in WorkspaceApp) == BUSINESS_APP_KEYS


def test_request_schemas_accept_canonical_enum_values():
    assert WorkspaceModeUpdate(mode="portfolio").mode is WorkspaceMode.portfolio
    assert WorkspaceUpdate(mode="demo").mode is WorkspaceMode.demo
    assert SystemCreate(name="Canonical", status="retired").status is SystemStatus.retired
    assert (
        SystemUpdate(execution_mode="continuous_monitoring").execution_mode
        is ExecutionMode.continuous_monitoring
    )
    assert WorkspaceUpdate(settings={"family": " Industrial "}).settings == {"family": "industrial"}
    assert WorkspaceUpdate(settings={}).settings == {}


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (WorkspaceModeUpdate, {"mode": "archived"}),
        (WorkspaceUpdate, {"mode": "portfolio_admin"}),
        (WorkspaceUpdate, {"settings": {"family": "bogus"}}),
        (SystemCreate, {"name": "Invalid", "status": "archived"}),
        (SystemUpdate, {"execution_mode": "real_time"}),
    ],
)
def test_request_schemas_reject_noncanonical_enum_values(schema, payload):
    with pytest.raises(ValidationError):
        schema.model_validate(payload)


def test_orm_metadata_declares_the_same_database_checks_as_migration_058():
    assert "ck_workspaces_mode" in _check_names(Workspace)
    assert {"ck_systems_status", "ck_systems_execution_mode"} <= _check_names(System)
    assert "ck_workspace_member_app_entitlements_app_key" in _check_names(
        WorkspaceMemberAppEntitlement
    )


def test_new_workspace_persists_a_canonical_generic_family_by_default(db_session):
    workspace = Workspace(id="workspace-default-family", name="New", slug="new")
    db_session.add(workspace)
    db_session.commit()
    db_session.refresh(workspace)

    assert workspace.settings == {"family": WorkspaceFamily.generic.value}


def test_personal_workspace_provisioning_stamps_generic_family(db_session):
    user = User(
        id="user-personal-family",
        username="personal-family",
        email="personal-family@example.test",
    )
    db_session.add(user)
    db_session.flush()

    _ensure_personal_workspace(db_session, user, "Personal")
    db_session.flush()

    workspace = (
        db_session.query(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .filter(WorkspaceMember.user_id == user.id)
        .one()
    )
    assert workspace.settings == {
        "kind": "personal",
        "family": WorkspaceFamily.generic.value,
    }
