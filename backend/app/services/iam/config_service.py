"""Workspace IAM configuration loading and rollout helpers."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.models.workspace import Workspace, WorkspaceIAMConfig


DEFAULT_ROLE_FLAGS: Dict[str, Any] = {
    "contributors_see_only_own_sessions": True,
    "require_second_eye_for_ingestion": True,
    "reviewers_inherit_contributor": False,
}


def is_iam_enforced_for_workspace(workspace: Workspace) -> bool:
    """Whether the role manifests decide for this workspace.

    Enforced unless the workspace carries an explicit ``iam_enforced: false``.
    Migration 111 wrote that ``false`` on every workspace that was open before
    it, so the default only governs workspaces created since: a new workspace
    starts governed instead of open by omission. ``iam_generic_engine`` still
    enforces everywhere, including on those opt-outs.
    """
    from app.services.workspace_features import graduated_feature_enabled

    return bool(
        settings.iam_generic_engine
        or graduated_feature_enabled(workspace, "iam_enforced")
    )


def effective_role_flags(config: Optional[WorkspaceIAMConfig]) -> Dict[str, Any]:
    flags = dict(DEFAULT_ROLE_FLAGS)
    if config and isinstance(config.role_flags, dict):
        flags.update(config.role_flags)
    return flags


def load_iam_config(
    db: DBSession,
    workspace_id: str,
    *,
    create: bool = False,
    updated_by_user_id: Optional[str] = None,
) -> Optional[WorkspaceIAMConfig]:
    config = db.query(WorkspaceIAMConfig).filter(WorkspaceIAMConfig.workspace_id == workspace_id).first()
    if config or not create:
        return config
    config = WorkspaceIAMConfig(
        workspace_id=workspace_id,
        version=1,
        role_flags=dict(DEFAULT_ROLE_FLAGS),
        capability_overrides={},
        updated_by_user_id=updated_by_user_id,
    )
    db.add(config)
    db.flush()
    return config


def patch_iam_config(
    db: DBSession,
    *,
    workspace_id: str,
    role_flags: Optional[Dict[str, Any]] = None,
    capability_overrides: Optional[Dict[str, Any]] = None,
    updated_by_user_id: Optional[str] = None,
) -> WorkspaceIAMConfig:
    config = load_iam_config(db, workspace_id, create=True, updated_by_user_id=updated_by_user_id)
    assert config is not None
    if role_flags is not None:
        config.role_flags = {**effective_role_flags(config), **role_flags}
    if capability_overrides is not None:
        config.capability_overrides = capability_overrides
    config.version = int(config.version or 0) + 1
    config.updated_at = datetime.utcnow()
    config.updated_by_user_id = updated_by_user_id
    db.flush()
    return config

