"""Pin the Andritz workspace default knowledge scope to the SPL context.

The ``setup_andritz_notices_spl.py`` seed already marks the
``andritz-spl-knowledge-experiment`` scope (label "Contexte Andritz SPL") as the
workspace default, because that scope spans the large SPL technical-notices
collection plus the BBA120 and France-Excel pilots. Production had drifted back
to the tiny ``andritz_manuals_bba120_pilot`` scope (22 docs) being the default,
which silently confined unscoped chat queries to that pilot and tripped the
exact-match guardrail for project-code questions. This migration re-converges
the DB to the seeded intent so rebuilds/restores stay aligned without manual
hotfixes.

Revision ID: 041_andritz_default_scope_spl
Revises: 040_source_status_deduplicated
Create Date: 2026-06-15
"""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "041_andritz_default_scope_spl"
down_revision = "040_source_status_deduplicated"
branch_labels = None
depends_on = None


_DEFAULT_SCOPE_KEY = "andritz-spl-knowledge-experiment"


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


def _set_default_scope(settings: dict[str, Any], target_key: str) -> bool:
    """Mark ``target_key`` as the only default scope. Returns True if changed."""
    scopes = settings.get("knowledge_scopes")
    if not isinstance(scopes, list):
        return False
    # Only converge when the target scope actually exists; never invent it.
    if not any(isinstance(s, dict) and s.get("key") == target_key for s in scopes):
        return False
    changed = False
    for scope in scopes:
        if not isinstance(scope, dict):
            continue
        should_be_default = scope.get("key") == target_key
        if bool(scope.get("is_default")) != should_be_default:
            scope["is_default"] = should_be_default
            changed = True
    return changed


def _apply(target_key: str) -> None:
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
        if not _set_default_scope(settings, target_key):
            continue
        bind.execute(
            sa.update(workspaces)
            .where(workspaces.c.id == row_data["id"])
            .values(settings=settings)
        )


def upgrade() -> None:
    _apply(_DEFAULT_SCOPE_KEY)


def downgrade() -> None:
    # Restore the historical default (BBA120 pilot) when present.
    _apply("andritz_manuals_bba120_pilot")
