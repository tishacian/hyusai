"""Knowledge guides.

Revision ID: 030_knowledge_guides
Revises: 029_visual_intel
Create Date: 2026-05-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "030_knowledge_guides"
down_revision = "029_visual_intel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "knowledge_guides" in inspector.get_table_names():
        return

    op.create_table(
        "knowledge_guides",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("guide_key", sa.String(length=80), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_ref", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("supersedes_id", sa.String(length=36), sa.ForeignKey("knowledge_guides.id"), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("workspace_id", "guide_key", "version", name="uq_knowledge_guides_workspace_key_version"),
        sa.CheckConstraint("target_type IN ('collection', 'scope')", name="ck_knowledge_guides_target_type"),
        sa.CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_knowledge_guides_status"),
    )
    op.create_index("ix_knowledge_guides_guide_key", "knowledge_guides", ["guide_key"])
    op.create_index("ix_knowledge_guides_workspace_id", "knowledge_guides", ["workspace_id"])
    op.create_index("ix_knowledge_guides_status", "knowledge_guides", ["status"])
    op.create_index("ix_knowledge_guides_is_current", "knowledge_guides", ["is_current"])
    op.create_index(
        "ix_knowledge_guides_target_current",
        "knowledge_guides",
        ["workspace_id", "target_type", "target_ref", "is_current"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_guides_target_current", table_name="knowledge_guides")
    op.drop_index("ix_knowledge_guides_is_current", table_name="knowledge_guides")
    op.drop_index("ix_knowledge_guides_status", table_name="knowledge_guides")
    op.drop_index("ix_knowledge_guides_workspace_id", table_name="knowledge_guides")
    op.drop_index("ix_knowledge_guides_guide_key", table_name="knowledge_guides")
    op.drop_table("knowledge_guides")
