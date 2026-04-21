"""Add default_prompt_type, default_model and retrieval_mode_default to systems.

Revision ID: 005_system_defaults
Revises: 004_canon_mental_model
Create Date: 2026-04-16

Wave B + C of the audit plan: expose the canonical mental model's
reasoning templates + retrieval mode + model override at the System
level so the run engine can pick them up without needing a per-run
override on every invocation.
"""
from alembic import op
import sqlalchemy as sa


revision = "005_system_defaults"
down_revision = "004_canon_mental_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("systems") as batch:
        batch.add_column(sa.Column("default_prompt_type", sa.String(length=40), nullable=True))
        batch.add_column(sa.Column("default_model", sa.String(length=120), nullable=True))
        batch.add_column(
            sa.Column(
                "retrieval_mode_default",
                sa.String(length=20),
                nullable=True,
                server_default="auto",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("systems") as batch:
        batch.drop_column("retrieval_mode_default")
        batch.drop_column("default_model")
        batch.drop_column("default_prompt_type")
