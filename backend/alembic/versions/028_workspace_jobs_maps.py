"""Workspace jobs and maps.

Revision ID: 028_workspace_jobs_maps
Revises: 027_workspace_action_items
Create Date: 2026-05-12
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "028_workspace_jobs_maps"
down_revision = "027_workspace_action_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("system_id", sa.String(length=36), sa.ForeignKey("systems.id", ondelete="SET NULL"), nullable=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="created"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stage", sa.String(length=80), nullable=False, server_default="created"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("input_ref", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("result", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("events", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("queued_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('created', 'queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_workspace_jobs_status",
        ),
    )
    op.create_index("ix_workspace_jobs_workspace_id", "workspace_jobs", ["workspace_id"])
    op.create_index("ix_workspace_jobs_system_id", "workspace_jobs", ["system_id"])
    op.create_index("ix_workspace_jobs_run_id", "workspace_jobs", ["run_id"])
    op.create_index("ix_workspace_jobs_workspace_status", "workspace_jobs", ["workspace_id", "status"])
    op.create_index("ix_workspace_jobs_workspace_kind", "workspace_jobs", ["workspace_id", "kind"])

    op.create_table(
        "workspace_maps",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("system_id", sa.String(length=36), sa.ForeignKey("systems.id", ondelete="SET NULL"), nullable=True),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("country", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("projection", sa.String(length=80), nullable=False, server_default="illustrative_exec_demo"),
        sa.Column("view_box", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("center", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("settings", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_workspace_maps_workspace_slug"),
    )
    op.create_index("ix_workspace_maps_workspace_id", "workspace_maps", ["workspace_id"])
    op.create_index("ix_workspace_maps_system_id", "workspace_maps", ["system_id"])
    op.create_index("ix_workspace_maps_workspace_slug", "workspace_maps", ["workspace_id", "slug"])

    op.create_table(
        "workspace_map_layers",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("map_id", sa.String(length=36), sa.ForeignKey("workspace_maps.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=80), nullable=False, server_default="zone"),
        sa.Column("visible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("map_id", "key", name="uq_workspace_map_layers_map_key"),
    )
    op.create_index("ix_workspace_map_layers_map_id", "workspace_map_layers", ["map_id"])
    op.create_index("ix_workspace_map_layers_map_sort", "workspace_map_layers", ["map_id", "sort_order"])

    op.create_table(
        "workspace_map_zones",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("map_id", sa.String(length=36), sa.ForeignKey("workspace_maps.id", ondelete="CASCADE"), nullable=False),
        sa.Column("zone_key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tone", sa.String(length=32), nullable=False, server_default="stable"),
        sa.Column("polygon", sa.Text(), nullable=False, server_default=""),
        sa.Column("centroid", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("source_refs", sa.JSON(), nullable=False, server_default="[]"),
        sa.UniqueConstraint("map_id", "zone_key", name="uq_workspace_map_zones_map_key"),
    )
    op.create_index("ix_workspace_map_zones_map_id", "workspace_map_zones", ["map_id"])
    op.create_index("ix_workspace_map_zones_map_level", "workspace_map_zones", ["map_id", "level"])

    op.create_table(
        "workspace_map_signals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("map_id", sa.String(length=36), sa.ForeignKey("workspace_maps.id", ondelete="CASCADE"), nullable=False),
        sa.Column("zone_id", sa.String(length=36), sa.ForeignKey("workspace_map_zones.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_kind", sa.String(length=80), nullable=False, server_default="mission_room"),
        sa.Column("source_id", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.65"),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_workspace_map_signals_map_id", "workspace_map_signals", ["map_id"])
    op.create_index("ix_workspace_map_signals_zone_id", "workspace_map_signals", ["zone_id"])
    op.create_index("ix_workspace_map_signals_map_source", "workspace_map_signals", ["map_id", "source_kind", "source_id"])

    op.create_table(
        "workspace_map_scores",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("map_id", sa.String(length=36), sa.ForeignKey("workspace_maps.id", ondelete="CASCADE"), nullable=False),
        sa.Column("zone_id", sa.String(length=36), sa.ForeignKey("workspace_map_zones.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("workspace_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("level_label", sa.String(length=32), nullable=False, server_default="stable"),
        sa.Column("drivers", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("recommendations", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("recommended_windows", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_workspace_map_scores_map_id", "workspace_map_scores", ["map_id"])
    op.create_index("ix_workspace_map_scores_zone_id", "workspace_map_scores", ["zone_id"])
    op.create_index("ix_workspace_map_scores_job_id", "workspace_map_scores", ["job_id"])
    op.create_index("ix_workspace_map_scores_map_zone", "workspace_map_scores", ["map_id", "zone_id"])


def downgrade() -> None:
    op.drop_index("ix_workspace_map_scores_map_zone", table_name="workspace_map_scores")
    op.drop_index("ix_workspace_map_scores_job_id", table_name="workspace_map_scores")
    op.drop_index("ix_workspace_map_scores_zone_id", table_name="workspace_map_scores")
    op.drop_index("ix_workspace_map_scores_map_id", table_name="workspace_map_scores")
    op.drop_table("workspace_map_scores")

    op.drop_index("ix_workspace_map_signals_map_source", table_name="workspace_map_signals")
    op.drop_index("ix_workspace_map_signals_zone_id", table_name="workspace_map_signals")
    op.drop_index("ix_workspace_map_signals_map_id", table_name="workspace_map_signals")
    op.drop_table("workspace_map_signals")

    op.drop_index("ix_workspace_map_zones_map_level", table_name="workspace_map_zones")
    op.drop_index("ix_workspace_map_zones_map_id", table_name="workspace_map_zones")
    op.drop_table("workspace_map_zones")

    op.drop_index("ix_workspace_map_layers_map_sort", table_name="workspace_map_layers")
    op.drop_index("ix_workspace_map_layers_map_id", table_name="workspace_map_layers")
    op.drop_table("workspace_map_layers")

    op.drop_index("ix_workspace_maps_workspace_slug", table_name="workspace_maps")
    op.drop_index("ix_workspace_maps_system_id", table_name="workspace_maps")
    op.drop_index("ix_workspace_maps_workspace_id", table_name="workspace_maps")
    op.drop_table("workspace_maps")

    op.drop_index("ix_workspace_jobs_workspace_kind", table_name="workspace_jobs")
    op.drop_index("ix_workspace_jobs_workspace_status", table_name="workspace_jobs")
    op.drop_index("ix_workspace_jobs_run_id", table_name="workspace_jobs")
    op.drop_index("ix_workspace_jobs_system_id", table_name="workspace_jobs")
    op.drop_index("ix_workspace_jobs_workspace_id", table_name="workspace_jobs")
    op.drop_table("workspace_jobs")
