"""Retain each mission attempt with a fenced worker lease."""

import sqlalchemy as sa

from alembic import op

revision = "143_task_executions"
down_revision = "142_experience_wizard_state"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "task_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("agent_id", sa.String(100)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("fence", sa.Integer(), nullable=False),
        sa.Column("lease_until", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("artifacts", sa.JSON(), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text()),
    )
    op.create_index("ix_task_executions_task_id", "task_executions", ["task_id"])
    op.create_index("ix_task_executions_workspace_id", "task_executions", ["workspace_id"])


def downgrade():
    op.drop_index("ix_task_executions_workspace_id", table_name="task_executions")
    op.drop_index("ix_task_executions_task_id", table_name="task_executions")
    op.drop_table("task_executions")
