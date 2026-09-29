"""Add per-collection read/write ACLs.

Revision ID: 117_collection_access
Revises: 116_backfill_role_template
Create Date: 2026-09-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "117_collection_access"
down_revision = "116_backfill_role_template"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_collections", sa.Column("access", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("knowledge_collections", "access")
