"""Seal leftover RPA tokens and Client360 SMTP passwords.

Demo stores used the HANA Fernet key for MCP, and left RPA tokens in a
plaintext envelope whenever ``RPA_CONNECTOR_FERNET_KEY`` was unset. The
runtime now falls back to that HANA key; this revision rewrites every
unsealed RPA token and every leftover SMTP ``password`` so the database
holds a sealed envelope. Already-sealed blobs are left alone. The secret
values are never logged.

Revision ID: 115_rpa_smtp_reencrypt
Revises: 114_value_contracts
Create Date: 2026-09-24
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "115_rpa_smtp_reencrypt"
down_revision = "114_value_contracts"
branch_labels = None
depends_on = None


def _workspaces_table() -> sa.Table:
    return sa.table(
        "workspaces",
        sa.column("id", sa.String(length=36)),
        sa.column("settings", sa.JSON()),
    )


def _as_settings(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def upgrade() -> None:
    from app.services.client360_pdr import reencrypt_workspace_smtp_password
    from app.services.connectors.rpa import service as rpa_service

    bind = op.get_bind()
    workspaces = _workspaces_table()
    rows = bind.execute(sa.select(workspaces.c.id, workspaces.c.settings)).fetchall()
    for workspace_id, settings in rows:
        current = _as_settings(settings)
        current, rpa_changed = rpa_service.reencrypt_workspace_rpa_token(current)
        current, smtp_changed = reencrypt_workspace_smtp_password(current)
        if rpa_changed or smtp_changed:
            bind.execute(
                workspaces.update()
                .where(workspaces.c.id == workspace_id)
                .values(settings=current)
            )


def downgrade() -> None:
    # Sealing is not reversible without writing the secret back in the clear.
    return
