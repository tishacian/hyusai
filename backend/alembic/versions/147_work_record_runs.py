"""Work record identity on bindings and the record ↔ Run attempt ledger.

Additive only: two nullable binding columns and one new table. Existing
bindings keep no identity contract, so nothing is linked until an author
declares one; historical Runs are never rewritten by this migration.
"""

import sqlalchemy as sa

from alembic import op

revision = "147_work_record_runs"
down_revision = "146_model_usage_budgets"
branch_labels = depends_on = None


def upgrade():
    op.add_column("system_bindings", sa.Column("record_namespace", sa.String(80), nullable=True))
    op.add_column("system_bindings", sa.Column("record_input_field", sa.String(80), nullable=True))
    op.create_table(
        "work_record_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("experience_id", sa.String(36), nullable=False),
        sa.Column("binding_key", sa.String(120), nullable=False),
        sa.Column("record_namespace", sa.String(80), nullable=False),
        sa.Column("record_ref", sa.String(200), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("initiated_by_user_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("run_id", name="uq_work_record_runs_run"),
    )
    op.create_index(
        "ix_work_record_runs_record",
        "work_record_runs",
        ["workspace_id", "record_namespace", "record_ref", "created_at"],
    )


def downgrade():
    op.drop_index("ix_work_record_runs_record", table_name="work_record_runs")
    op.drop_table("work_record_runs")
    op.drop_column("system_bindings", "record_input_field")
    op.drop_column("system_bindings", "record_namespace")
