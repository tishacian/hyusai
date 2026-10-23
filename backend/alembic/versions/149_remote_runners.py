"""External runners and their jobs.

Additive only: two new tables. Nothing existing is rewritten; a workspace has
no runner until an administrator declares one.
"""

import sqlalchemy as sa

from alembic import op

revision = "149_remote_runners"
down_revision = "148_work_record_backfill"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "remote_runners",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("transport", sa.String(16), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(80), nullable=False),
        sa.Column("host_key", sa.Text(), nullable=False),
        sa.Column("key_secret_ref", sa.String(255), nullable=False),
        sa.Column("bastion", sa.JSON(), nullable=True),
        sa.Column("work_root", sa.String(512), nullable=False),
        sa.Column("allowed_commands", sa.JSON(), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("max_concurrent_jobs", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_probe", sa.JSON(), nullable=True),
        sa.Column("last_probe_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_remote_runners_workspace_slug"),
        sa.CheckConstraint("transport IN ('ssh','local')", name="ck_remote_runners_transport"),
        sa.CheckConstraint(
            "port > 0 AND port < 65536 AND max_concurrent_jobs > 0",
            name="ck_remote_runners_limits",
        ),
    )
    op.create_index("ix_remote_runners_workspace_id", "remote_runners", ["workspace_id"])
    op.create_table(
        "remote_runner_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "runner_id",
            sa.String(36),
            sa.ForeignKey("remote_runners.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("command", sa.String(120), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=True),
        sa.Column("node_id", sa.String(160), nullable=True),
        sa.Column("correlation_key", sa.String(200), nullable=True),
        sa.Column("notify_system_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("remote_dir", sa.String(1024), nullable=True),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("artifacts", sa.JSON(), nullable=False),
        sa.Column("log_tail", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("cancel_sent_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deadline_at", sa.DateTime(), nullable=False),
        sa.Column("launched_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("event_emitted_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued','launching','running','cancelling',"
            "'succeeded','failed','cancelled','timed_out','lost')",
            name="ck_remote_runner_jobs_status",
        ),
    )
    for column in (
        "workspace_id",
        "runner_id",
        "run_id",
        "status",
        "deadline_at",
        "correlation_key",
    ):
        op.create_index(f"ix_remote_runner_jobs_{column}", "remote_runner_jobs", [column])


def downgrade():
    for column in (
        "workspace_id",
        "runner_id",
        "run_id",
        "status",
        "deadline_at",
        "correlation_key",
    ):
        op.drop_index(f"ix_remote_runner_jobs_{column}", table_name="remote_runner_jobs")
    op.drop_table("remote_runner_jobs")
    op.drop_index("ix_remote_runners_workspace_id", table_name="remote_runners")
    op.drop_table("remote_runners")
