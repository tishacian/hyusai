"""Server-owned operational jobs shared by ML monitoring and shadow scoring.

These kinds are never writable through the generic job API. Their input and
result JSON are execution authority, not user-authored job metadata.
"""
from uuid import NAMESPACE_URL, uuid5

from app.core.iam.roles import normalize_role_template
from app.models.workspace import WorkspaceMember

SERVER_MANAGED_JOB_KINDS = frozenset({"brd_generation", "llm_label_dataset", "ml_shadow"})


def operational_job_id(kind: str, *parts: str) -> str:
    return str(uuid5(NAMESPACE_URL, "agentium:mlops:" + ":".join((kind, *parts))))


def can_configure_mlops(db, *, workspace, user, admin_only: bool = False) -> bool:
    if not workspace.is_active or not user.is_active:
        return False
    if user.role == "admin":
        return True
    member = db.query(WorkspaceMember).filter_by(workspace_id=workspace.id, user_id=user.id).first()
    if member is None:
        return False
    # Unknown legacy roles must not become contributors via normalize's legacy
    # fallback. In particular an old literal "viewer" remains read-only.
    role = member.role_template or member.role
    if role not in {"workspace_owner", "workspace_admin", "workspace_contributor",
                    "owner", "admin", "member", "user"}:
        return False
    template = normalize_role_template(member.role_template, member.role)
    allowed = {"workspace_owner", "workspace_admin"}
    if not admin_only:
        allowed.add("workspace_contributor")
    return template in allowed
