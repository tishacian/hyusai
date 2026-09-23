"""Stamp Secure Deposit as a per-workspace flag before the global CSV goes.

``is_workspace_enabled`` read ``workspaces.settings["features"]["secure_deposit"]``
first and fell back to a comma-separated list of slugs in global config. The
fallback is the last thing tying a customer capability to a deployment-wide
environment variable, which is exactly what
``app.services.workspace_features`` says runtime code must not do: a workspace
should differ because its use cases differ.

This migration freezes what the fallback would have answered and writes it
where the runtime already looks. It only fills workspaces that have no
explicit value, so an operator decision recorded before this runs is never
overwritten, and it records what it wrote so the downgrade removes exactly
that and nothing else.
"""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "110_secure_deposit_ws_flag"
down_revision = "109_automation_review"
branch_labels = None
depends_on = None

FEATURE = "secure_deposit"
MARKER_KEY = "_migration_110_secure_deposit_flag"
# The shipped default. A deployment that narrowed or widened the list through
# the environment is honoured when the variable is still present at migrate
# time; otherwise this frozen value is what the fallback would have answered.
DEFAULT_SLUG_CSV = "andritz"
ENV_VAR = "SECURE_DEPOSIT_ENABLED_WORKSPACE_SLUGS"


def _workspaces_table() -> sa.Table:
    return sa.table(
        "workspaces",
        sa.column("id", sa.String(length=36)),
        sa.column("slug", sa.String(length=100)),
        sa.column("settings", sa.JSON()),
    )


def _legacy_slugs() -> set[str]:
    raw = os.environ.get(ENV_VAR)
    if raw is None:
        raw = DEFAULT_SLUG_CSV
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _as_settings(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return deepcopy(value)
    if value is None:
        return {}
    raise RuntimeError("workspaces.settings must be a JSON object")


def upgrade() -> None:
    bind = op.get_bind()
    workspaces = _workspaces_table()
    legacy = _legacy_slugs()

    rows = bind.execute(
        sa.select(workspaces.c.id, workspaces.c.slug, workspaces.c.settings)
    ).all()
    for row in rows:
        mapping = row._mapping
        settings = _as_settings(mapping["settings"])
        features = settings.get("features")
        if not isinstance(features, dict):
            features = {}
        if FEATURE in features:
            continue  # an explicit decision already exists; leave it alone
        enabled = str(mapping["slug"] or "").strip().lower() in legacy
        features[FEATURE] = enabled
        settings["features"] = features
        settings[MARKER_KEY] = {"schema": 1, "wrote": enabled}
        bind.execute(
            sa.update(workspaces)
            .where(workspaces.c.id == mapping["id"])
            .values(settings=settings)
        )


def downgrade() -> None:
    bind = op.get_bind()
    workspaces = _workspaces_table()

    rows = bind.execute(
        sa.select(workspaces.c.id, workspaces.c.settings)
    ).all()
    for row in rows:
        mapping = row._mapping
        settings = _as_settings(mapping["settings"])
        marker = settings.pop(MARKER_KEY, None)
        if not isinstance(marker, dict):
            continue
        features = settings.get("features")
        if isinstance(features, dict) and features.get(FEATURE) == marker.get("wrote"):
            features.pop(FEATURE, None)
            if features:
                settings["features"] = features
            else:
                settings.pop("features", None)
        bind.execute(
            sa.update(workspaces)
            .where(workspaces.c.id == mapping["id"])
            .values(settings=settings)
        )
