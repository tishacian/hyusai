"""Disable the expert-review workflow for the Andritz rollout.

The expert correction/capture review gate is now per-workspace
(``source_policy.expert_review_required``, layered like
``expert_fiche_correction_enabled``). For the Andritz rollout we turn review
OFF so a validated expert fiche is auto-published immediately, and ensure the
expert-fiche correction feature is ON. Both the workspace ``settings`` and the
always-on chat ``System`` settings carry the policy (parity with how ``/chat``
folds the System policy over the workspace one), so we converge both.

Idempotent: only writes when a value actually changes. Modelled on
``041_andritz_default_scope_spl``.

Revision ID: 042_andritz_disable_expert_review
Revises: 041_andritz_default_scope_spl
Create Date: 2026-06-18
"""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "042_andritz_disable_expert_review"
down_revision = "041_andritz_default_scope_spl"
branch_labels = None
depends_on = None


_WORKSPACE_CHAT_VARIANT = "chat_transverse_v1"


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


def _merge_source_policy(settings: dict[str, Any], updates: dict[str, Any]) -> bool:
    """Apply ``updates`` to ``settings["source_policy"]``. Returns True if changed."""
    policy = settings.get("source_policy")
    if not isinstance(policy, dict):
        policy = {}
    changed = False
    for key, value in updates.items():
        if policy.get(key) != value:
            policy[key] = value
            changed = True
    if changed:
        settings["source_policy"] = policy
    return changed


def _is_workspace_chat_system(settings: dict[str, Any], flow: dict[str, Any], name: str) -> bool:
    if flow.get("variant") == _WORKSPACE_CHAT_VARIANT:
        return True
    if settings.get("system_type") == "workspace_chat":
        return True
    return name in {"Agentium Workspace Chat", "Andritz Workspace Chat"}


def _apply(updates: dict[str, Any]) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    if "workspaces" not in table_names:
        return

    workspaces = sa.table(
        "workspaces",
        sa.column("id"),
        sa.column("slug"),
        sa.column("settings", sa.JSON()),
    )

    workspace_rows = bind.execute(
        sa.select(workspaces.c.id, workspaces.c.settings).where(workspaces.c.slug == "andritz")
    ).all()
    workspace_ids = [row._mapping["id"] for row in workspace_rows]

    for row in workspace_rows:
        row_data = row._mapping
        settings = _as_settings(row_data["settings"])
        if _merge_source_policy(settings, updates):
            bind.execute(
                sa.update(workspaces)
                .where(workspaces.c.id == row_data["id"])
                .values(settings=settings)
            )

    if not workspace_ids or "systems" not in table_names:
        return

    systems = sa.table(
        "systems",
        sa.column("id"),
        sa.column("workspace_id"),
        sa.column("name"),
        sa.column("flow_definition", sa.JSON()),
        sa.column("settings", sa.JSON()),
    )

    system_rows = bind.execute(
        sa.select(
            systems.c.id,
            systems.c.name,
            systems.c.flow_definition,
            systems.c.settings,
        ).where(systems.c.workspace_id.in_(workspace_ids))
    ).all()

    for row in system_rows:
        row_data = row._mapping
        settings = _as_settings(row_data["settings"])
        flow = _as_settings(row_data["flow_definition"])
        if not _is_workspace_chat_system(settings, flow, str(row_data["name"] or "")):
            continue
        if _merge_source_policy(settings, updates):
            bind.execute(
                sa.update(systems)
                .where(systems.c.id == row_data["id"])
                .values(settings=settings)
            )


def upgrade() -> None:
    _apply({"expert_review_required": False, "expert_fiche_correction_enabled": True})


def downgrade() -> None:
    # Re-enable the review gate. Leave expert_fiche_correction_enabled in place:
    # the correction feature is orthogonal to the review gate and may have been
    # enabled independently of this rollout.
    _apply({"expert_review_required": True})
