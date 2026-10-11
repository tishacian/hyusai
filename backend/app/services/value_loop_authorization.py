"""Authorization-v2 gate shared by the Lot 8 rollout and runtime.

The value-loop feature must never open while one of its subordinate actions is
still governed by legacy compatibility. ``resolve_mode`` validates both the
exact ``enforce`` declaration and its SHA-bound promotion attestation, so an
invalid or drifted attestation closes the feature just like ``shadow`` does.
"""
from __future__ import annotations

from sqlalchemy.orm import Session as DBSession

from app.models.workspace import WorkspaceIAMConfig
from app.services.iam.decision_plane import AuthorizationMode, resolve_mode

REQUIRED_VALUE_LOOP_AUTHORIZATION_ACTIONS = (
    "system.read",
    "system.engine.run",
    "run.read",
    "decision.read",
    "control_policy.read",
    "control_policy.admin",
    "value_scenario.read",
    "value_scenario.create",
    "value_scenario.simulate",
    "value_scenario.approve",
    "value_scenario.act",
    "value_scenario.measure",
)


def value_loop_authorization_modes(
    db: DBSession,
    *,
    workspace_id: str,
    lock: bool = False,
) -> dict[str, str]:
    query = db.query(WorkspaceIAMConfig).filter(
        WorkspaceIAMConfig.workspace_id == workspace_id
    )
    if lock:
        query = query.populate_existing().with_for_update(of=WorkspaceIAMConfig)
    config = query.one_or_none()
    if config is None:
        return {
            action: AuthorizationMode.COMPAT.value
            for action in REQUIRED_VALUE_LOOP_AUTHORIZATION_ACTIONS
        }
    result: dict[str, str] = {}
    for key in REQUIRED_VALUE_LOOP_AUTHORIZATION_ACTIONS:
        resource_kind, action = key.split(".", maxsplit=1)
        result[key] = resolve_mode(
            config,
            resource_kind=resource_kind,
            action=action,
        ).value
    return result


def value_loop_authorization_ready(
    db: DBSession,
    *,
    workspace_id: str,
    lock: bool = False,
) -> bool:
    modes = value_loop_authorization_modes(
        db,
        workspace_id=workspace_id,
        lock=lock,
    )
    return all(
        modes.get(action) == AuthorizationMode.ENFORCE.value
        for action in REQUIRED_VALUE_LOOP_AUTHORIZATION_ACTIONS
    )


__all__ = [
    "REQUIRED_VALUE_LOOP_AUTHORIZATION_ACTIONS",
    "value_loop_authorization_modes",
    "value_loop_authorization_ready",
]
