"""Persist idempotent Celery subflow delegation state.

Revision ID: 061_subflow_delegation_state
Revises: 060_andritz_fse_reports
"""
import sqlalchemy as sa

from alembic import op

revision = "061_subflow_delegation_state"
down_revision = "060_andritz_fse_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("delegation_key", sa.String(64), nullable=True))
    op.add_column("runs", sa.Column("delegation_node_id", sa.String(160), nullable=True))
    op.add_column("runs", sa.Column("delegation_branch", sa.String(160), nullable=True))
    op.add_column("runs", sa.Column("celery_task_id", sa.String(255), nullable=True))
    op.add_column(
        "runs",
        sa.Column("waiting_subflows", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    )
    op.create_index("uq_runs_delegation_key", "runs", ["delegation_key"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_runs_delegation_key", table_name="runs")
    for name in (
        "waiting_subflows",
        "celery_task_id",
        "delegation_branch",
        "delegation_node_id",
        "delegation_key",
    ):
        op.drop_column("runs", name)
