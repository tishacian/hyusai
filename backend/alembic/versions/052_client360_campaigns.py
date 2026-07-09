"""Client360 PDR campaign entity and transformation tracking.

Revision ID: 052_client360_campaigns
Revises: 051_client360_pdr_merge
Create Date: 2026-07-09
"""
from __future__ import annotations

from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "052_client360_campaigns"
down_revision = "051_client360_pdr_merge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    existing_indexes = {
        table_name: {index["name"] for index in inspector.get_indexes(table_name)}
        for table_name in existing_tables
    }

    def _safe_create_table(table_name: str, *columns: Any, **kwargs: Any) -> None:
        if table_name in existing_tables:
            return
        op.create_table(table_name, *columns, **kwargs)
        existing_tables.add(table_name)
        existing_indexes.setdefault(table_name, set())

    def _safe_create_index(index_name: str, table_name: str, columns: list[str]) -> None:
        if index_name in existing_indexes.get(table_name, set()):
            return
        op.create_index(index_name, table_name, columns)
        existing_indexes.setdefault(table_name, set()).add(index_name)

    def _column_names(table_name: str) -> set[str]:
        if table_name not in existing_tables:
            return set()
        return {column["name"] for column in inspector.get_columns(table_name)}

    _safe_create_table(
        "client360_campaigns",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("campaign_type", sa.String(length=40), nullable=False, server_default="free"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft", index=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("selection_criteria", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("targeted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("drafts_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "campaign_type IN ('first_replacement', 'maintenance_education', 'renewal', 'cross_selling', 'upselling', 'free')",
            name="ck_client360_campaigns_type",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'in_review', 'active', 'completed', 'archived')",
            name="ck_client360_campaigns_status",
        ),
    )
    _safe_create_index("ix_client360_campaigns_workspace_status", "client360_campaigns", ["workspace_id", "status"])

    if "campaign_id" not in _column_names("client360_mail_drafts"):
        op.add_column(
            "client360_mail_drafts",
            sa.Column(
                "campaign_id",
                sa.String(length=36),
                sa.ForeignKey("client360_campaigns.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        _safe_create_index("ix_client360_mail_drafts_campaign_id", "client360_mail_drafts", ["campaign_id"])

    if "campaign_id" not in _column_names("client360_impact_events"):
        op.add_column(
            "client360_impact_events",
            sa.Column(
                "campaign_id",
                sa.String(length=36),
                sa.ForeignKey("client360_campaigns.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        _safe_create_index("ix_client360_impact_events_campaign_id", "client360_impact_events", ["campaign_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    def _column_names(table_name: str) -> set[str]:
        if table_name not in tables:
            return set()
        return {column["name"] for column in inspector.get_columns(table_name)}

    def _index_names(table_name: str) -> set[str]:
        if table_name not in tables:
            return set()
        return {index["name"] for index in inspector.get_indexes(table_name)}

    if "campaign_id" in _column_names("client360_impact_events"):
        if "ix_client360_impact_events_campaign_id" in _index_names("client360_impact_events"):
            op.drop_index("ix_client360_impact_events_campaign_id", table_name="client360_impact_events")
        op.drop_column("client360_impact_events", "campaign_id")

    if "campaign_id" in _column_names("client360_mail_drafts"):
        if "ix_client360_mail_drafts_campaign_id" in _index_names("client360_mail_drafts"):
            op.drop_index("ix_client360_mail_drafts_campaign_id", table_name="client360_mail_drafts")
        op.drop_column("client360_mail_drafts", "campaign_id")

    if "client360_campaigns" in tables:
        if "ix_client360_campaigns_workspace_status" in _index_names("client360_campaigns"):
            op.drop_index("ix_client360_campaigns_workspace_status", table_name="client360_campaigns")
        op.drop_table("client360_campaigns")
