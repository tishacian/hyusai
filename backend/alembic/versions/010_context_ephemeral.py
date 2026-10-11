"""Ephemeral contexts for drop-and-ask chat sessions (Vague D / D0).

Revision ID: 010_context_ephemeral
Revises: 009_rag_presets
Create Date: 2026-04-22

Adds two additive columns to `contexts`:

- `ephemeral` (bool, default false, indexed) — flags contexts created by
  the chat workspace drop-and-ask flow. These are auto-purged once past
  `ttl_expires_at`.
- `ttl_expires_at` (datetime, nullable) — absolute expiration timestamp
  set at creation time (e.g. `now() + 24h`). Null for regular contexts.

Purely additive — no data migration needed, existing contexts default to
`ephemeral=false, ttl_expires_at=null` which matches their current
semantic (permanent contexts).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "010_context_ephemeral"
down_revision = "009_rag_presets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("contexts") as batch:
        batch.add_column(
            sa.Column(
                "ephemeral",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(sa.Column("ttl_expires_at", sa.DateTime(), nullable=True))
        batch.create_index(
            "ix_contexts_ephemeral",
            ["ephemeral"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("contexts") as batch:
        batch.drop_index("ix_contexts_ephemeral")
        batch.drop_column("ttl_expires_at")
        batch.drop_column("ephemeral")
