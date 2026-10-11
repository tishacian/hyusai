"""Add the Python recipe execution plane: managed venvs + executions.

Revision ID: 095_python_recipes
Revises: 094_experience_brand_history
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "095_python_recipes"
down_revision = "094_experience_brand_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "python_envs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("python_version", sa.String(16), nullable=False),
        sa.Column("requirements_text", sa.Text(), nullable=False),
        sa.Column("lock_text", sa.Text(), nullable=True),
        sa.Column("index_url", sa.String(500), nullable=True),
        sa.Column("extra_index_urls", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("build_log_tail", sa.Text(), nullable=True),
        sa.Column("build_error", sa.Text(), nullable=True),
        sa.Column("built_at", sa.DateTime(), nullable=True),
        sa.Column("build_duration_ms", sa.Float(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "fingerprint",
            name="uq_python_envs_workspace_fingerprint",
        ),
    )
    op.create_index("ix_python_envs_workspace_id", "python_envs", ["workspace_id"])
    op.create_index("ix_python_envs_fingerprint", "python_envs", ["fingerprint"])
    op.create_index("ix_python_envs_status", "python_envs", ["status"])
    op.create_index("ix_python_envs_last_used_at", "python_envs", ["last_used_at"])

    op.create_table(
        "recipe_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("run_id", sa.String(36), nullable=True),
        sa.Column("node_id", sa.String(160), nullable=True),
        sa.Column("invocation_id", sa.String(36), nullable=True),
        sa.Column(
            "env_id",
            sa.String(36),
            sa.ForeignKey("python_envs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("env_fingerprint", sa.String(64), nullable=True),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column(
            "cancel_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("code_sha256", sa.String(64), nullable=True),
        sa.Column("timeout_s", sa.Float(), nullable=True),
        sa.Column("input_json", sa.JSON(), nullable=True),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("stdout_tail", sa.Text(), nullable=True),
        sa.Column("stderr_tail", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
    )
    op.create_index(
        "ix_recipe_executions_workspace_id", "recipe_executions", ["workspace_id"]
    )
    op.create_index("ix_recipe_executions_run_id", "recipe_executions", ["run_id"])
    op.create_index(
        "ix_recipe_executions_invocation_id", "recipe_executions", ["invocation_id"]
    )
    op.create_index("ix_recipe_executions_env_id", "recipe_executions", ["env_id"])
    op.create_index("ix_recipe_executions_status", "recipe_executions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_recipe_executions_status", table_name="recipe_executions")
    op.drop_index("ix_recipe_executions_env_id", table_name="recipe_executions")
    op.drop_index(
        "ix_recipe_executions_invocation_id", table_name="recipe_executions"
    )
    op.drop_index("ix_recipe_executions_run_id", table_name="recipe_executions")
    op.drop_index(
        "ix_recipe_executions_workspace_id", table_name="recipe_executions"
    )
    op.drop_table("recipe_executions")
    op.drop_index("ix_python_envs_last_used_at", table_name="python_envs")
    op.drop_index("ix_python_envs_status", table_name="python_envs")
    op.drop_index("ix_python_envs_fingerprint", table_name="python_envs")
    op.drop_index("ix_python_envs_workspace_id", table_name="python_envs")
    op.drop_table("python_envs")
