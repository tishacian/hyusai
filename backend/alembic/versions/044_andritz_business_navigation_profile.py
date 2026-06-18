"""Enable the business end-user navigation profile for Andritz.

The profile is stored in ``workspaces.settings`` so it remains a workspace
configuration concern rather than a schema change. Non-admin users get the
mini-shell with Chat transverse + Capture de connaissances; admins keep the
full cockpit unless they explicitly preview the business shell.

Revision ID: 044_andritz_business_navigation_profile
Revises: 043_andritz_disable_chat_upload
Create Date: 2026-06-18
"""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "044_andritz_business_navigation_profile"
down_revision = "043_andritz_disable_chat_upload"
branch_labels = None
depends_on = None


_PROFILE = {
    "key": "business_end_user",
    "default_route": "/chat",
    "primary_surfaces": ["chat", "knowledge-capture"],
    "advanced_access": "admin_only",
}


def _as_settings(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return deepcopy(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "workspaces" not in set(inspector.get_table_names()):
        return

    workspaces = sa.table(
        "workspaces",
        sa.column("id"),
        sa.column("slug"),
        sa.column("settings", sa.JSON()),
    )

    rows = bind.execute(
        sa.select(workspaces.c.id, workspaces.c.settings).where(workspaces.c.slug == "andritz")
    ).all()
    for row in rows:
        row_data = row._mapping
        settings = _as_settings(row_data["settings"])
        if settings.get("navigation_profile") == _PROFILE:
            continue
        settings["navigation_profile"] = deepcopy(_PROFILE)
        bind.execute(
            sa.update(workspaces)
            .where(workspaces.c.id == row_data["id"])
            .values(settings=settings)
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "workspaces" not in set(inspector.get_table_names()):
        return

    workspaces = sa.table(
        "workspaces",
        sa.column("id"),
        sa.column("slug"),
        sa.column("settings", sa.JSON()),
    )

    rows = bind.execute(
        sa.select(workspaces.c.id, workspaces.c.settings).where(workspaces.c.slug == "andritz")
    ).all()
    for row in rows:
        row_data = row._mapping
        settings = _as_settings(row_data["settings"])
        profile = settings.get("navigation_profile")
        if not isinstance(profile, dict) or profile.get("key") != "business_end_user":
            continue
        settings.pop("navigation_profile", None)
        bind.execute(
            sa.update(workspaces)
            .where(workspaces.c.id == row_data["id"])
            .values(settings=settings)
        )
