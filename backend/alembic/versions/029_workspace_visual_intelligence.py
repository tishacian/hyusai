"""Workspace visual intelligence.

Revision ID: 029_visual_intel
Revises: 028_workspace_jobs_maps
Create Date: 2026-05-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "029_visual_intel"
down_revision = "028_workspace_jobs_maps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_visual_sources",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("system_id", sa.String(length=36), sa.ForeignKey("systems.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_type", sa.String(length=80), nullable=False, server_default="webcam"),
        sa.Column("adapter", sa.String(length=80), nullable=False, server_default="http_image"),
        sa.Column("region", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("capture_cadence_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("policy", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("last_captured_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("workspace_id", "name", name="uq_workspace_visual_sources_workspace_name"),
        sa.CheckConstraint("status IN ('active', 'paused', 'error')", name="ck_workspace_visual_sources_status"),
        sa.CheckConstraint("adapter IN ('http_image', 'browser_screenshot', 'demo_static')", name="ck_workspace_visual_sources_adapter"),
        sa.CheckConstraint("source_type IN ('webcam', 'image_snapshot', 'stream_embed')", name="ck_workspace_visual_sources_type"),
    )
    op.create_index("ix_workspace_visual_sources_workspace_id", "workspace_visual_sources", ["workspace_id"])
    op.create_index("ix_workspace_visual_sources_system_id", "workspace_visual_sources", ["system_id"])
    op.create_index("ix_workspace_visual_sources_created_by_user_id", "workspace_visual_sources", ["created_by_user_id"])
    op.create_index("ix_workspace_visual_sources_workspace_status", "workspace_visual_sources", ["workspace_id", "status"])

    op.create_table(
        "workspace_visual_captures",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.String(length=36), sa.ForeignKey("workspace_visual_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("workspace_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="captured"),
        sa.Column("object_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("mime_type", sa.String(length=80), nullable=False, server_default="image/jpeg"),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('captured', 'analyzed', 'failed')", name="ck_workspace_visual_captures_status"),
    )
    op.create_index("ix_workspace_visual_captures_workspace_id", "workspace_visual_captures", ["workspace_id"])
    op.create_index("ix_workspace_visual_captures_source_id", "workspace_visual_captures", ["source_id"])
    op.create_index("ix_workspace_visual_captures_job_id", "workspace_visual_captures", ["job_id"])
    op.create_index("ix_workspace_visual_captures_workspace_source", "workspace_visual_captures", ["workspace_id", "source_id"])

    op.create_table(
        "workspace_visual_observations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.String(length=36), sa.ForeignKey("workspace_visual_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capture_id", sa.String(length=36), sa.ForeignKey("workspace_visual_captures.id", ondelete="CASCADE"), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.65"),
        sa.Column("vigilance_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("level_label", sa.String(length=32), nullable=False, server_default="stable"),
        sa.Column("source_refs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("provider", sa.String(length=80), nullable=False, server_default="rule_based"),
        sa.Column("model", sa.String(length=160), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("level_label IN ('stable', 'monitoring', 'elevated', 'critical')", name="ck_workspace_visual_observations_level"),
    )
    op.create_index("ix_workspace_visual_observations_workspace_id", "workspace_visual_observations", ["workspace_id"])
    op.create_index("ix_workspace_visual_observations_source_id", "workspace_visual_observations", ["source_id"])
    op.create_index("ix_workspace_visual_observations_capture_id", "workspace_visual_observations", ["capture_id"])
    op.create_index("ix_workspace_visual_observations_workspace_created", "workspace_visual_observations", ["workspace_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_workspace_visual_observations_workspace_created", table_name="workspace_visual_observations")
    op.drop_index("ix_workspace_visual_observations_capture_id", table_name="workspace_visual_observations")
    op.drop_index("ix_workspace_visual_observations_source_id", table_name="workspace_visual_observations")
    op.drop_index("ix_workspace_visual_observations_workspace_id", table_name="workspace_visual_observations")
    op.drop_table("workspace_visual_observations")

    op.drop_index("ix_workspace_visual_captures_workspace_source", table_name="workspace_visual_captures")
    op.drop_index("ix_workspace_visual_captures_job_id", table_name="workspace_visual_captures")
    op.drop_index("ix_workspace_visual_captures_source_id", table_name="workspace_visual_captures")
    op.drop_index("ix_workspace_visual_captures_workspace_id", table_name="workspace_visual_captures")
    op.drop_table("workspace_visual_captures")

    op.drop_index("ix_workspace_visual_sources_workspace_status", table_name="workspace_visual_sources")
    op.drop_index("ix_workspace_visual_sources_created_by_user_id", table_name="workspace_visual_sources")
    op.drop_index("ix_workspace_visual_sources_system_id", table_name="workspace_visual_sources")
    op.drop_index("ix_workspace_visual_sources_workspace_id", table_name="workspace_visual_sources")
    op.drop_table("workspace_visual_sources")
