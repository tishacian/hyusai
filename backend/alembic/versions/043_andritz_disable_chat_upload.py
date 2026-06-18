"""Disable the chat drop-and-ask document upload for the Andritz rollout.

The transverse workspace chat exposes a "drop-and-ask" document upload that
hits ``POST /api/v1/documents/upload-batch``. This is gated per-workspace by
the ``settings["features"]["chat_document_upload"]`` flag (default ON / opt-out,
resolved by ``chat_document_upload_enabled``). For the Andritz rollout we turn
the flag OFF so the chat dropzone is hidden and the endpoint rejects
``source=chat_drop_and_ask`` uploads. The Knowledge Base upload is untouched
(it never sends ``source``).

The flag is workspace-only — unlike ``042_andritz_disable_review`` there is no
systems-table policy to converge.

Idempotent: only writes when the value actually changes, and merges into
``settings["features"]`` without clobbering other features or settings keys.
Modelled on ``042_andritz_disable_review``.

Revision ID: 043_andritz_disable_chat_upload
Revises: 042_andritz_disable_review
Create Date: 2026-06-18
"""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "043_andritz_disable_chat_upload"
down_revision = "042_andritz_disable_review"
branch_labels = None
depends_on = None


_FEATURE = "chat_document_upload"


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


def _set_feature(settings: dict[str, Any], value: bool) -> bool:
    """Set ``settings["features"][_FEATURE] = value``. Returns True if changed."""
    features = settings.get("features")
    if not isinstance(features, dict):
        features = {}
    if features.get(_FEATURE) == value:
        return False
    features[_FEATURE] = value
    settings["features"] = features
    return True


def _clear_feature(settings: dict[str, Any]) -> bool:
    """Remove ``settings["features"][_FEATURE]``. Returns True if changed."""
    features = settings.get("features")
    if not isinstance(features, dict) or _FEATURE not in features:
        return False
    features = dict(features)
    del features[_FEATURE]
    settings["features"] = features
    return True


def _apply(mutate) -> None:
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
        if mutate(settings):
            bind.execute(
                sa.update(workspaces)
                .where(workspaces.c.id == row_data["id"])
                .values(settings=settings)
            )


def upgrade() -> None:
    _apply(lambda settings: _set_feature(settings, False))


def downgrade() -> None:
    # Remove the explicit flag, restoring the default-on behaviour. Other
    # features keys (and the rest of settings) are left intact.
    _apply(_clear_feature)
