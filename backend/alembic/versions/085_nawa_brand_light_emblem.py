"""Give the Nawa platform brand a light-surface emblem.

The wordmark the customer delivered is a JPEG on opaque black: it has no alpha
channel, so on the light chrome the title bar shows a black plate instead of a
mark. The frontend brand reader now accepts an optional ``emblem_light`` and the
title bar uses it when the resolved theme is light. This migration declares that
variant for the ``nawa`` workspace, pointing at the keyed-out artwork the
business screens already use for their own light theme.

Same convention as 065, which wrote the brand in the first place:

* additive and idempotent;
* a brand authored by an operator is theirs — we only fill the hole, and here
  the hole is one key inside a brand we recognise as the one 065 wrote;
* the downgrade removes only the value we wrote ourselves.

One ordering note. 065's downgrade removes the brand only when it still equals
its own ``PLATFORM_BRAND`` literal, so while this revision is applied that test
fails by design. Downgrading in revision order — this one, then 065 — restores
the exact literal first, and 065 then removes it as it always did. There is no
supported path that skips a revision, so this is the whole of the interaction.

Revision ID: 085_nawa_brand_light_emblem
Revises: 084_decision_condition_repair
Create Date: 2026-08-12
"""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "085_nawa_brand_light_emblem"
down_revision = "084_decision_condition_repair"
branch_labels = None
depends_on = None


NAWA_SLUG = "nawa"
BRAND_KEY = "platform_brand"
EMBLEM_LIGHT_KEY = "emblem_light"

# The keyed-out twin of the delivered artwork, already shipped in the frontend
# bundle and already used by the NAWA business screens on their light theme.
EMBLEM_LIGHT = "/assets/nawa/nawa-logo-transparent.png"

# Verbatim copy of 065's ``PLATFORM_BRAND``. It is the fingerprint of a brand we
# wrote: only such a brand gets the new key. Copied rather than imported because
# a migration must keep describing the state of the world at the time it ran,
# whatever later revisions do to their own constants.
BRAND_WE_WROTE = {
    "label": "NAWA",
    "emblem": "/assets/nawa/nawa-logo.png",
    "home": "/nawa/itsd",
}


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
    # The workspace is created by the operator and may not exist yet: its
    # absence is a normal state, not a failure.
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
    def add_variant(brand: dict[str, Any]) -> dict[str, Any] | None:
        # Recognise the brand 065 wrote, ignoring the key we are about to set so
        # a second run sees the same brand it saw the first time.
        without_variant = {k: v for k, v in brand.items() if k != EMBLEM_LIGHT_KEY}
        if without_variant != BRAND_WE_WROTE:
            return None
        # An operator who already named a variant has answered the question.
        if brand.get(EMBLEM_LIGHT_KEY):
            return None
        brand[EMBLEM_LIGHT_KEY] = EMBLEM_LIGHT
        return brand

    _rewrite_brand(add_variant)


def downgrade() -> None:
    def drop_variant(brand: dict[str, Any]) -> dict[str, Any] | None:
        if brand.get(EMBLEM_LIGHT_KEY) != EMBLEM_LIGHT:
            return None
        brand.pop(EMBLEM_LIGHT_KEY)
        return brand

    _rewrite_brand(drop_variant)
