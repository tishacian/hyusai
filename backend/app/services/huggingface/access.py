"""Hub permissions derived from authenticated platform and workspace roles."""

from app.core.iam.roles import is_admin_template, normalize_role_template
from app.models.workspace import WorkspaceMember
from app.services.huggingface.errors import HFError


def is_platform_admin(user):
    return bool(user and user.is_active and user.role == "admin")


def _membership(db, user, workspace):
    return (
        db.query(WorkspaceMember)
        .populate_existing()
        .filter_by(user_id=user.id, workspace_id=workspace.id)
        .first()
    )


def is_workspace_admin(db, user, workspace):
    if (
        not user
        or not user.is_active
        or not workspace
        or not workspace.is_active
        or workspace.deleted_at
    ):
        return False
    if is_platform_admin(user):
        return True
    member = _membership(db, user, workspace)
    return bool(member and is_admin_template(member.role_template, member.role))


def can_import_dataset(db, user, workspace):
    if (
        not user
        or not user.is_active
        or not workspace
        or not workspace.is_active
        or workspace.deleted_at
    ):
        return False
    if is_workspace_admin(db, user, workspace):
        return True
    member = _membership(db, user, workspace)
    return bool(
        member
        and normalize_role_template(member.role_template, member.role) == "workspace_contributor"
    )


def require_workspace_admin(db, user, workspace):
    if not is_workspace_admin(db, user, workspace):
        raise HFError("WORKSPACE_PERMISSION_DENIED", "A workspace administrator is required.", 403)


def require_platform_admin(user):
    if not is_platform_admin(user):
        raise HFError("PLATFORM_PERMISSION_DENIED", "A platform administrator is required.", 403)


def require_import_permission(db, user, workspace, kind):
    if kind == "model":
        require_workspace_admin(db, user, workspace)
    elif not can_import_dataset(db, user, workspace):
        raise HFError("WORKSPACE_PERMISSION_DENIED", "A workspace contributor is required.", 403)


def require_job_actor(db, job, kind="model"):
    """A queued action cannot retain a deleted account's or removed role's rights."""
    from app.models.user import User
    from app.models.workspace import Workspace

    user = (
        db.get(User, job.created_by_user_id, populate_existing=True)
        if job.created_by_user_id
        else None
    )
    workspace = db.get(Workspace, job.workspace_id, populate_existing=True)
    require_import_permission(db, user, workspace, kind)
    return workspace
