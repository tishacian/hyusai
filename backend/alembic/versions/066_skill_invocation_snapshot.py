"""Add immutable execution evidence to Skill invocations.

Revision ID: 066_skill_invocation_snapshot
Revises: 065_system_version_config

Both columns are nullable by design.  Existing invocations stay explicitly
unknown; application producers populate the fields only for new executions.
``cost_measured=True`` is reserved for provider measurements or calculations
backed by an identifiable configured tariff.  No historical or default zero is
backfilled as evidence.
"""
import sqlalchemy as sa

from alembic import op

revision = "066_skill_invocation_snapshot"
down_revision = "065_system_version_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "skill_invocations",
        sa.Column("execution_snapshot", sa.JSON(), nullable=True),
    )
    op.add_column(
        "skill_invocations",
        sa.Column("cost_measured", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("skill_invocations", "cost_measured")
    op.drop_column("skill_invocations", "execution_snapshot")
