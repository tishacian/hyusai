"""Clean legacy Andritz chat surface labels.

Revision ID: 039_cleanup_andritz_chat_surface
Revises: 038_default_model_gpt5
Create Date: 2026-06-04
"""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "039_cleanup_andritz_chat_surface"
down_revision = "038_default_model_gpt5"
branch_labels = None
depends_on = None


_LEGACY_SCOPE_LABEL = "Andritz SPL knowledge experiment"
_CLEAN_SCOPE_LABEL = "Contexte Andritz SPL"


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


def _clean_text(value: Any, *, placeholder: bool = False) -> Any:
    if not isinstance(value, str):
        return value
    if _LEGACY_SCOPE_LABEL not in value:
        return value
    if placeholder:
        return "Posez votre question..."
    return value.replace(_LEGACY_SCOPE_LABEL, _CLEAN_SCOPE_LABEL)


def _clean_chat_surface(settings: dict[str, Any]) -> bool:
    changed = False

    scopes = settings.get("knowledge_scopes")
    if isinstance(scopes, list):
        for scope in scopes:
            if not isinstance(scope, dict):
                continue
            if scope.get("label") == _LEGACY_SCOPE_LABEL:
                scope["label"] = _CLEAN_SCOPE_LABEL
                changed = True

    chat = settings.get("chat")
    if isinstance(chat, dict):
        for key in ("title", "subtitle"):
            next_value = _clean_text(chat.get(key))
            if next_value != chat.get(key):
                chat[key] = next_value
                changed = True
        next_placeholder = _clean_text(chat.get("placeholder"), placeholder=True)
        if next_placeholder != chat.get("placeholder"):
            chat["placeholder"] = next_placeholder
            changed = True

    profiles = settings.get("assistant_profiles")
    if isinstance(profiles, list):
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            chat = profile.get("chat")
            if not isinstance(chat, dict):
                continue
            for key in ("title", "subtitle"):
                next_value = _clean_text(chat.get(key))
                if next_value != chat.get(key):
                    chat[key] = next_value
                    changed = True
            next_placeholder = _clean_text(chat.get("placeholder"), placeholder=True)
            if next_placeholder != chat.get("placeholder"):
                chat["placeholder"] = next_placeholder
                changed = True

    return changed


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
        if not _clean_chat_surface(settings):
            continue
        bind.execute(
            sa.update(workspaces)
            .where(workspaces.c.id == row_data["id"])
            .values(settings=settings)
        )


def downgrade() -> None:
    # Keep cleaned user-facing labels; this migration is cosmetic and safe.
    pass
