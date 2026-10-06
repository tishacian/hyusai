"""Add provider cost columns to runs and skill invocations."""

import sqlalchemy as sa
from alembic import op

revision = "121_provider_run_costs"
down_revision = "120_feed_article_workspace"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("runs", sa.Column("provider_cost_usd", sa.Float(), nullable=True))
    op.add_column(
        "skill_invocations",
        sa.Column("provider_cost_usd", sa.Float(), nullable=True),
    )


def downgrade():
    op.drop_column("skill_invocations", "provider_cost_usd")
    op.drop_column("runs", "provider_cost_usd")
