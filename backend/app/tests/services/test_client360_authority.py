from __future__ import annotations

import pytest

from app.models.capability import Capability
from app.models.system import System
from app.models.workspace import Workspace
from app.services.client360_contract import (
    CLIENT360_CAPABILITY_SLUG,
    CLIENT360_SYSTEM_VARIANT,
)
from app.services.client360_pdr import resolve_client360_authority


def _workspace(db_session, suffix: str) -> Workspace:
    workspace = Workspace(
        id=f"workspace-client360-authority-{suffix}",
        slug=f"client360-authority-{suffix}",
        name=f"Client360 authority {suffix}",
        settings={"family": "andritz"},
    )
    db_session.add(workspace)
    db_session.flush()
    return workspace


def _authority(
    db_session,
    workspace: Workspace,
    *,
    suffix: str,
    status: str = "active",
    capability_workspace_id: str | None = None,
    capability_slug: str = CLIENT360_CAPABILITY_SLUG,
) -> tuple[System, Capability]:
    capability = Capability(
        id=f"capability-client360-authority-{suffix}",
        workspace_id=(
            workspace.id if capability_workspace_id is None else capability_workspace_id
        ),
        slug=capability_slug,
        name=f"Client360 capability {suffix}",
        tier="client",
    )
    system = System(
        id=f"system-client360-authority-{suffix}",
        workspace_id=workspace.id,
        name=f"Mutable display name {suffix}",
        objective="Resolve a structural Client360 authority.",
        capability_id=capability.id,
        status=status,
        settings={"system_type": CLIENT360_SYSTEM_VARIANT},
        flow_definition={"variant": CLIENT360_SYSTEM_VARIANT},
    )
    db_session.add_all([capability, system])
    db_session.flush()
    return system, capability


def test_client360_authority_resolves_one_active_structural_binding(db_session) -> None:
    workspace = _workspace(db_session, "valid")
    system, capability = _authority(db_session, workspace, suffix="valid")

    resolved_system, resolved_capability = resolve_client360_authority(
        db_session,
        workspace,
    )

    assert resolved_system.id == system.id
    assert resolved_capability.id == capability.id


def test_client360_authority_ignores_non_active_installations(db_session) -> None:
    workspace = _workspace(db_session, "lifecycle")
    active, capability = _authority(db_session, workspace, suffix="lifecycle-active")
    paused_capability = Capability(
        id="capability-client360-authority-lifecycle-paused",
        workspace_id=workspace.id,
        slug="client360-paused-copy",
        name="Paused Client360 copy",
        tier="client",
    )
    paused = System(
        id="system-client360-authority-lifecycle-paused",
        workspace_id=workspace.id,
        name="Paused Client360 copy",
        objective="Must not become runtime authority.",
        capability_id=paused_capability.id,
        status="paused",
        settings={"system_type": CLIENT360_SYSTEM_VARIANT},
        flow_definition={"variant": CLIENT360_SYSTEM_VARIANT},
    )
    db_session.add_all([paused_capability, paused])
    db_session.flush()

    resolved_system, resolved_capability = resolve_client360_authority(
        db_session,
        workspace,
    )

    assert resolved_system.id == active.id
    assert resolved_capability.id == capability.id


def test_client360_authority_rejects_missing_or_ambiguous_active_binding(db_session) -> None:
    missing = _workspace(db_session, "missing")
    with pytest.raises(LookupError, match="found 0"):
        resolve_client360_authority(db_session, missing)

    ambiguous = _workspace(db_session, "ambiguous")
    _authority(db_session, ambiguous, suffix="ambiguous-a")
    second_capability = Capability(
        id="capability-client360-authority-ambiguous-b",
        workspace_id=ambiguous.id,
        slug="client360-ambiguous-copy",
        name="Second Client360 capability",
        tier="client",
    )
    second_system = System(
        id="system-client360-authority-ambiguous-b",
        workspace_id=ambiguous.id,
        name="Second active Client360",
        objective="Create an ambiguous authority.",
        capability_id=second_capability.id,
        status="active",
        settings={"system_type": CLIENT360_SYSTEM_VARIANT},
        flow_definition={"variant": CLIENT360_SYSTEM_VARIANT},
    )
    db_session.add_all([second_capability, second_system])
    db_session.flush()

    with pytest.raises(LookupError, match="found 2"):
        resolve_client360_authority(db_session, ambiguous)


def test_client360_authority_rejects_wrong_or_cross_workspace_capability(db_session) -> None:
    wrong_contract = _workspace(db_session, "wrong-contract")
    _authority(
        db_session,
        wrong_contract,
        suffix="wrong-contract",
        capability_slug="mutable-client360-copy",
    )
    with pytest.raises(LookupError, match="contract does not match"):
        resolve_client360_authority(db_session, wrong_contract)

    foreign = _workspace(db_session, "foreign")
    crossed = _workspace(db_session, "crossed")
    _authority(
        db_session,
        crossed,
        suffix="crossed",
        capability_workspace_id=foreign.id,
    )
    with pytest.raises(LookupError, match="crosses workspace scope"):
        resolve_client360_authority(db_session, crossed)
