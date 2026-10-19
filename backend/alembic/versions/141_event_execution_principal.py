"""Explicit delegated authority for unattended event execution.

Existing hooks, schedules and Runs remain unassigned. No human initiator or
execution grant is backfilled from creator strings, payloads or administrators.
"""

import sqlalchemy as sa

from alembic import op

revision = "141_event_execution_principal"
down_revision = "140_mlops_prod_explanations"
branch_labels = depends_on = None


def upgrade():
    op.add_column("webhook_hooks", sa.Column("execution_identity", sa.JSON(), nullable=True))
    op.add_column("run_schedules", sa.Column("execution_identity", sa.JSON(), nullable=True))
    op.add_column("runs", sa.Column("execution_principal", sa.JSON(), nullable=True))


def downgrade():
    connection = op.get_bind()
    for table, column in (
        ("webhook_hooks", "execution_identity"),
        ("run_schedules", "execution_identity"),
        ("runs", "execution_principal"),
    ):
        # JSON null is used by SQLAlchemy for an unassigned optional value.
        if connection.execute(
            sa.text(
                f"SELECT 1 FROM {table} WHERE {column} IS NOT NULL "
                f"AND CAST({column} AS TEXT) <> 'null' LIMIT 1"
            )
        ).first():
            raise RuntimeError("EVENT_EXECUTION_PRINCIPAL_DOWNGRADE_NOT_EMPTY")
    op.drop_column("runs", "execution_principal")
    op.drop_column("run_schedules", "execution_identity")
    op.drop_column("webhook_hooks", "execution_identity")
