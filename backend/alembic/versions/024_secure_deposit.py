"""Secure deposit links and staged files.

Revision ID: 024_secure_deposit
Revises: 023_capture_attribution
Create Date: 2026-05-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "024_secure_deposit"
down_revision = "023_capture_attribution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deposit_access_links",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False, server_default="External deposit"),
        sa.Column("access_id", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("max_file_size_mb", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("allowed_extensions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'revoked', 'expired')", name="ck_deposit_access_links_status"),
        sa.UniqueConstraint("access_id", name="uq_deposit_access_links_access_id"),
    )
    op.create_index("ix_deposit_access_links_workspace_id", "deposit_access_links", ["workspace_id"])
    op.create_index("ix_deposit_access_links_created_by_user_id", "deposit_access_links", ["created_by_user_id"])
    op.create_index("ix_deposit_access_links_access_id", "deposit_access_links", ["access_id"])
    op.create_index(
        "ix_deposit_access_links_workspace_status",
        "deposit_access_links",
        ["workspace_id", "status"],
    )

    op.create_table(
        "deposit_files",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("access_link_id", sa.String(length=36), sa.ForeignKey("deposit_access_links.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="received"),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
        sa.Column("promoted_at", sa.DateTime(), nullable=True),
        sa.Column("promoted_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("promoted_collection_slug", sa.String(length=120), nullable=True),
        sa.Column("worker_job_id", sa.String(length=36), nullable=True),
        sa.Column("promotion_result", sa.JSON(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('received', 'rejected', 'promoted')", name="ck_deposit_files_status"),
    )
    op.create_index("ix_deposit_files_workspace_id", "deposit_files", ["workspace_id"])
    op.create_index("ix_deposit_files_access_link_id", "deposit_files", ["access_link_id"])
    op.create_index("ix_deposit_files_workspace_status", "deposit_files", ["workspace_id", "status"])
    op.create_index("ix_deposit_files_uploaded_at", "deposit_files", ["uploaded_at"])


def downgrade() -> None:
    op.drop_index("ix_deposit_files_uploaded_at", table_name="deposit_files")
    op.drop_index("ix_deposit_files_workspace_status", table_name="deposit_files")
    op.drop_index("ix_deposit_files_access_link_id", table_name="deposit_files")
    op.drop_index("ix_deposit_files_workspace_id", table_name="deposit_files")
    op.drop_table("deposit_files")

    op.drop_index("ix_deposit_access_links_workspace_status", table_name="deposit_access_links")
    op.drop_index("ix_deposit_access_links_access_id", table_name="deposit_access_links")
    op.drop_index("ix_deposit_access_links_created_by_user_id", table_name="deposit_access_links")
    op.drop_index("ix_deposit_access_links_workspace_id", table_name="deposit_access_links")
    op.drop_table("deposit_access_links")
