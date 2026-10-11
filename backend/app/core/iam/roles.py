"""Workspace IAM role templates and legacy compatibility helpers."""
from __future__ import annotations

from typing import Optional

WORKSPACE_VIEWER = "workspace_viewer"
WORKSPACE_CONTRIBUTOR = "workspace_contributor"
WORKSPACE_REVIEWER = "workspace_reviewer"
WORKSPACE_ADMIN = "workspace_admin"
WORKSPACE_OWNER = "workspace_owner"

CANONICAL_WORKSPACE_ROLES = {
    WORKSPACE_VIEWER,
    WORKSPACE_CONTRIBUTOR,
    WORKSPACE_REVIEWER,
    WORKSPACE_ADMIN,
    WORKSPACE_OWNER,
}

LEGACY_ROLE_TO_TEMPLATE = {
    "member": WORKSPACE_CONTRIBUTOR,
    "user": WORKSPACE_CONTRIBUTOR,
    "admin": WORKSPACE_ADMIN,
    "owner": WORKSPACE_OWNER,
}

TEMPLATE_TO_LEGACY_ROLE = {
    WORKSPACE_VIEWER: "member",
    WORKSPACE_CONTRIBUTOR: "member",
    WORKSPACE_REVIEWER: "member",
    WORKSPACE_ADMIN: "admin",
    WORKSPACE_OWNER: "owner",
}

ADMIN_ROLE_TEMPLATES = {WORKSPACE_ADMIN, WORKSPACE_OWNER}


def normalize_role_template(role_template: Optional[str], legacy_role: Optional[str] = None) -> str:
    """Return a canonical workspace role template.

    ``role`` is intentionally kept as a legacy compatibility column. New IAM
    decisions should call this helper so old rows continue to behave exactly as
    before until ``role_template`` has been backfilled.
    """
    if role_template in CANONICAL_WORKSPACE_ROLES:
        return role_template  # type: ignore[return-value]
    return LEGACY_ROLE_TO_TEMPLATE.get((legacy_role or "member").strip(), WORKSPACE_CONTRIBUTOR)


def legacy_role_for_template(role_template: Optional[str]) -> str:
    return TEMPLATE_TO_LEGACY_ROLE.get(
        normalize_role_template(role_template, "member"),
        "member",
    )


def is_admin_template(role_template: Optional[str], legacy_role: Optional[str] = None) -> bool:
    return normalize_role_template(role_template, legacy_role) in ADMIN_ROLE_TEMPLATES

