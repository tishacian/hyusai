"""Single source of truth for pre-authorization-v2 object decisions.

Compat and shadow must preserve the authority that the mutation endpoints had
before granular enforcement.  Projectors use the same functions so Govern
never invents a stricter or broader legacy decision than the API it describes.
Managed-System structural guards remain at their endpoint boundary and run
before this role/action decision.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.core.iam.dependencies import current_membership
from app.core.iam.roles import is_admin_template
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.chat_execution_policy import migration_059_system_id


def legacy_workspace_admin(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
) -> bool:
    """Whether the subject holds workspace administration, by role or platform.

    Boundaries introduced after authorization-v2 have no permissive legacy
    behaviour to preserve, so they pass this as their compat decision: compat
    then matches the candidate rule and promotion changes the audit trail
    rather than the answer.
    """

    if getattr(user, "role", None) == "admin":
        return True
    membership = current_membership(db, user, workspace)
    return bool(membership and is_admin_template(membership.role_template, membership.role))


def legacy_run_approval_allowed(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    runs: Iterable[Run],
) -> bool:
    """Mirror the initiator/admin rule after lineage integrity is established."""

    scoped_runs = list(runs)
    if not scoped_runs or any(run.workspace_id != workspace.id for run in scoped_runs):
        return False
    is_admin = getattr(user, "role", None) == "admin"
    if not is_admin:
        membership = current_membership(db, user, workspace)
        is_admin = bool(
            membership
            and is_admin_template(membership.role_template, membership.role)
        )

    system_ids = {str(run.system_id) for run in scoped_runs if run.system_id}
    systems = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.id.in_(system_ids))
        .all()
        if system_ids
        else []
    )
    if {system.id for system in systems} != system_ids:
        return False
    managed_id = migration_059_system_id(workspace)
    if managed_id and managed_id in system_ids and not is_admin:
        return False
    return is_admin or any(run.initiated_by_user_id == user.id for run in scoped_runs)


def legacy_object_action_allowed(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    resource_kind: str,
    action: str,
    resource_attrs: Mapping[str, Any] | None = None,
    runs: Iterable[Run] = (),
) -> bool:
    """Return the exact pre-v2 decision for Lot 7 object actions."""

    attrs = dict(resource_attrs or {})
    if action == "read":
        # Callers invoke this only after the historical visibility lookup.
        return True
    if action == "admin":
        # These mutation routes historically required workspace access but no
        # additional role.  Candidate admin RBAC remains shadow until promoted.
        if resource_kind not in {"capability", "system", "run"}:
            return False
        if resource_kind == "system" and attrs.get("managed_system") is True:
            return legacy_workspace_admin(db, user=user, workspace=workspace)
        return True
    if resource_kind == "run" and action == "approve":
        return legacy_run_approval_allowed(
            db,
            user=user,
            workspace=workspace,
            runs=runs,
        )
    return False
