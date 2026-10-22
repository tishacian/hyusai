"""Bind qualification executions and their artifacts to a separate campaign domain."""

import sqlalchemy as sa

from alembic import op

revision = "145_evaluation_isolation"
down_revision = "144_sharepoint_file_outcomes"
branch_labels = depends_on = None
TABLES = ("runs", "tabular_datasets", "recipe_executions", "ml_predictions")


def upgrade():
    for table in TABLES:
        op.add_column(table, sa.Column("evaluation_campaign_id", sa.String(36), nullable=True))
        op.create_index(f"ix_{table}_evaluation_campaign_id", table, ["evaluation_campaign_id"])
        op.create_foreign_key(
            f"fk_{table}_evaluation_campaign",
            table,
            "evaluation_campaigns",
            ["evaluation_campaign_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.add_column("runs", sa.Column("evaluation_binding", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("runs", "evaluation_binding")
    for table in reversed(TABLES):
        op.drop_constraint(f"fk_{table}_evaluation_campaign", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_evaluation_campaign_id", table_name=table)
        op.drop_column(table, "evaluation_campaign_id")
