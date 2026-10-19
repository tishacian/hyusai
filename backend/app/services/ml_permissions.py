"""ML actions use current workspace roles, including calls made by a Flow."""

from app.core.config import settings
from app.core.iam.roles import CANONICAL_WORKSPACE_ROLES, LEGACY_ROLE_TO_TEMPLATE
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.audit_logger import emit_audit_event
from app.services.huggingface.access import is_platform_admin
from app.services.tabular_datasets import TabularError

READ = frozenset(CANONICAL_WORKSPACE_ROLES)
WRITE = READ - {"workspace_viewer"}
ADMIN = frozenset({"workspace_admin", "workspace_owner"})
ACTIONS = {
    "read": READ,
    "predict": READ,
    "train": WRITE,
    "feedback": WRITE,
    "shadow": WRITE,
    "cancel": WRITE,
    "score": WRITE,
    "promote": ADMIN | {"workspace_reviewer"},
    "delete": ADMIN,
    "keys": ADMIN,
    "publish": ADMIN,
    "policy": ADMIN,
    "export": ADMIN,
    "import": ADMIN,
    # M4.2: capture references, requalify and revoke runtime attestations.
    "requalify": ADMIN,
}
# New trust-expanding actions never fall back to report mode: report mode
# measures role changes on existing actions, it does not grant new ones.
STRICT = frozenset({"export", "import", "requalify"})


def allowed(db, action, workspace, user):
    if action not in ACTIONS or not user or not user.is_active or not workspace:
        return False
    if not workspace.is_active or workspace.deleted_at:
        return False
    if is_platform_admin(user):
        return True
    member = (
        db.query(WorkspaceMember)
        .populate_existing()
        .filter_by(workspace_id=workspace.id, user_id=user.id)
        .first()
    )
    if member is None:
        return False
    role = member.role_template or LEGACY_ROLE_TO_TEMPLATE.get(member.role)
    return role in ACTIONS[action]


def capabilities(db, workspace, user):
    return {action: allowed(db, action, workspace, user) for action in ACTIONS}


def require(db, action, workspace, user):
    if allowed(db, action, workspace, user):
        return
    # Report mode can measure role changes, never grant workspace membership.
    member = bool(
        user
        and workspace
        and db.query(WorkspaceMember).filter_by(workspace_id=workspace.id, user_id=user.id).first()
    )
    if (
        action in ACTIONS
        and action not in STRICT
        and not settings.ml_rbac_enforced
        and member
        and user.is_active
        and workspace.is_active
        and not workspace.deleted_at
    ):
        audit(
            db,
            action="permission_report",
            workspace_id=workspace.id,
            actor=user.id,
            after={"action": action, "would_deny": True},
        )
        return
    raise TabularError(
        code="ML_FORBIDDEN_ACTION",
        message="Your role does not allow this model action.",
        status_code=403,
        details={"action": action},
    )


def require_context(db, action, workspace_id, context):
    """Resolve authority from persisted Run metadata, never Skill arguments."""
    from app.models.run import Run

    run_id = (context or {}).get("run_id")
    user_id = (context or {}).get("user_id")
    if run_id:
        run = db.get(Run, run_id)
        if run is None or str(run.workspace_id) != str(workspace_id):
            raise TabularError(
                code="ML_FORBIDDEN_ACTION",
                message="A matching authorized Run is required.",
                status_code=403,
            )
        from app.services.run_engine.execution_principal import (
            ExecutionPrincipalError,
            execution_user_id,
        )

        try:
            user_id = execution_user_id(db, run)
        except ExecutionPrincipalError as exc:
            raise TabularError(
                code=exc.code,
                message="The Run's delegated execution authority is no longer available.",
                status_code=403,
            ) from exc
        # System.created_by is a display name, not an authority identifier.
        # Legacy scheduled Runs need an explicit persisted initiator before
        # invoking ML; a matching username must never grant another identity.
    user = db.get(User, user_id, populate_existing=True) if user_id else None
    workspace = db.get(Workspace, workspace_id, populate_existing=True)
    require(db, action, workspace, user)
    return user


def audit(db, *, action, workspace_id, actor, model=None, before=None, after=None, ip=None):
    details = {
        "model_id": getattr(model, "id", None),
        "version": getattr(model, "version", None),
        "before": before or {},
        "after": after or {},
    }
    if ip:
        details["client_ip"] = str(ip)[:64]
    if (
        emit_audit_event(
            db=db,
            workspace_id=workspace_id,
            event_type="ml.model." + action,
            actor=str(actor or "system"),
            details=details,
        )
        is None
    ):
        raise TabularError(
            code="ML_AUDIT_UNAVAILABLE",
            message="The model action could not be audited.",
            status_code=503,
        )
