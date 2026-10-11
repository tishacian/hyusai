"""Declare the Nawa appearance the Agent Studio used to hard-code.

The PR to PO Agent Studio wore a NAWA skin written into the shared Work and
chat styles: near-black surfaces and a coral accent. ADR 0003 lot 2 takes that
skin out of the product shell. The Studio now wears the workspace appearance
(``platform_brand.appearance``, the mechanism the shell and the Work launcher
already read), so the look it had becomes data on the ``nawa`` workspace: the
``graphite`` palette and the ``#e8543a`` accent.

The appearance also dresses the Nawa Agentium shell and Work launcher, which
the release notes say. The NAWA business application (``/nawa/itsd``) keeps
its own theme.

Same convention as 065 and 085:

* additive and idempotent;
* an appearance an operator declared is theirs: we only fill the hole, and a
  workspace without a platform brand gets none from us;
* the downgrade removes only the value we wrote ourselves.

Ordering note, as in 085: 065's downgrade removes the brand only when it still
equals its own literal, so downgrade in revision order.

Revision ID: 113_nawa_studio_appearance
Revises: 112_sap_write_intents
Create Date: 2026-09-24
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "113_nawa_studio_appearance"
down_revision = "112_sap_write_intents"
branch_labels = None
depends_on = None


NAWA_SLUG = "nawa"
BRAND_KEY = "platform_brand"
APPEARANCE_KEY = "appearance"

# The Studio skin as the product's appearance vocabulary says it: the graphite
# palette (near-black surfaces in the dark) and the coral accent.
APPEARANCE = {"palette": "graphite", "accent": "#e8543a"}


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return deepcopy(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _workspaces():
    return sa.table(
        "workspaces",
        sa.column("id"),
        sa.column("slug"),
        sa.column("settings", sa.JSON()),
    )


def _rewrite_brand(rewrite) -> None:
    """Apply ``rewrite`` to the ``nawa`` brand, writing back only on a change."""
    bind = op.get_bind()
    if "workspaces" not in set(sa.inspect(bind).get_table_names()):
        return
    workspaces = _workspaces()
    rows = bind.execute(
        sa.select(workspaces.c.id, workspaces.c.settings).where(workspaces.c.slug == NAWA_SLUG)
    ).all()
    for row in rows:
        ws = row._mapping
        settings = _as_dict(ws["settings"])
        brand = settings.get(BRAND_KEY)
        if not isinstance(brand, dict):
            continue
        updated = rewrite(dict(brand))
        if updated is None or updated == brand:
            continue
        settings[BRAND_KEY] = updated
        bind.execute(
            sa.update(workspaces).where(workspaces.c.id == ws["id"]).values(settings=settings)
        )


def upgrade() -> None:
    def add_appearance(brand: dict[str, Any]) -> dict[str, Any] | None:
        if brand.get(APPEARANCE_KEY):
            return None
        brand[APPEARANCE_KEY] = dict(APPEARANCE)
        return brand

    _rewrite_brand(add_appearance)


def downgrade() -> None:
    def drop_appearance(brand: dict[str, Any]) -> dict[str, Any] | None:
        if brand.get(APPEARANCE_KEY) != APPEARANCE:
            return None
        brand.pop(APPEARANCE_KEY)
        return brand

    _rewrite_brand(drop_appearance)
