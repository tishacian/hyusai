"""Pin the Andritz voice/capture domain strings as workspace overrides.

The voice STT steering prompt, the FINAL-reformulation rewrite context and the
reformulation glossary domain framing were de-hardcoded to domain-neutral
defaults in code. To keep the live Andritz workspace byte-identical, this
slug-scoped migration writes the EXACT legacy strings as workspace overrides
under ``settings.voice``. It also pins the capture endpointing thresholds that
used to be hardcoded for the ``andritz`` slug in the capture UI, now carried in
``settings.voice_loop`` after the frontend stopped special-casing the slug.

Set-if-absent and idempotent: existing operator-tuned values are never
clobbered, and re-running changes nothing. Modelled on
``042_andritz_disable_review`` / ``044_andritz_business_nav``.

Revision ID: 046_andritz_voice_capture_overrides
Revises: 045_fact_text_trgm_index
Create Date: 2026-06-24
"""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "046_andritz_voice_capture_overrides"
down_revision = "045_fact_text_trgm_index"
branch_labels = None
depends_on = None


# Exact legacy strings that were hardcoded in code before genericization.
_VOICE_OVERRIDES: dict[str, Any] = {
    "transcript_context": "Transcription en français d'un expert industriel Andritz.",
    "transcript_rewrite_context": "Nous sommes dans le contexte industriel Andritz.",
    "transcript_glossary_domain": "terminologie métier Andritz",
}
# Endpointing thresholds previously injected by the capture UI for the Andritz
# slug; pinned so the de-hardcoded frontend keeps the same conversation cadence.
_VOICE_LOOP_OVERRIDES: dict[str, Any] = {
    "silence_ms": 900,
    "min_speech_ms": 350,
    "max_turn_ms": 25000,
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


def _set_if_absent(settings: dict[str, Any], section_key: str, overrides: dict[str, Any]) -> bool:
    """Add missing ``overrides`` into ``settings[section_key]``. Returns True if changed."""
    section = settings.get(section_key)
    if not isinstance(section, dict):
        section = {}
    changed = False
    for key, value in overrides.items():
        if key not in section:
            section[key] = value
            changed = True
    if changed:
        settings[section_key] = section
    return changed


def _remove_pinned(settings: dict[str, Any], section_key: str, overrides: dict[str, Any]) -> bool:
    """Drop keys we pinned, only when still equal to the pinned value. Returns True if changed."""
    section = settings.get(section_key)
    if not isinstance(section, dict):
        return False
    changed = False
    for key, value in overrides.items():
        if section.get(key) == value:
            section.pop(key, None)
            changed = True
    if changed:
        if section:
            settings[section_key] = section
        else:
            settings.pop(section_key, None)
    return changed


def _andritz_rows(bind):
    workspaces = sa.table(
        "workspaces",
        sa.column("id"),
        sa.column("slug"),
        sa.column("settings", sa.JSON()),
    )
    rows = bind.execute(
        sa.select(workspaces.c.id, workspaces.c.settings).where(workspaces.c.slug == "andritz")
    ).all()
    return workspaces, rows


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "workspaces" not in set(inspector.get_table_names()):
        return

    workspaces, rows = _andritz_rows(bind)
    for row in rows:
        row_data = row._mapping
        settings = _as_settings(row_data["settings"])
        changed = _set_if_absent(settings, "voice", _VOICE_OVERRIDES)
        changed = _set_if_absent(settings, "voice_loop", _VOICE_LOOP_OVERRIDES) or changed
        if changed:
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

    workspaces, rows = _andritz_rows(bind)
    for row in rows:
        row_data = row._mapping
        settings = _as_settings(row_data["settings"])
        changed = _remove_pinned(settings, "voice", _VOICE_OVERRIDES)
        changed = _remove_pinned(settings, "voice_loop", _VOICE_LOOP_OVERRIDES) or changed
        if changed:
            bind.execute(
                sa.update(workspaces)
                .where(workspaces.c.id == row_data["id"])
                .values(settings=settings)
            )
