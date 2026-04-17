"""Add MFA challenges table and mfa_enabled column on users

Revision ID: 002_mfa_account
Revises: 001_initial
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa


revision = "002_mfa_account"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "mfa_challenges",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("code", sa.String(length=6), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0"),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("kc_payload", sa.Text(), nullable=False),
    )
    op.create_index("ix_mfa_challenges_user_id", "mfa_challenges", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_mfa_challenges_user_id", table_name="mfa_challenges")
    op.drop_table("mfa_challenges")
    op.drop_column("users", "mfa_enabled")
