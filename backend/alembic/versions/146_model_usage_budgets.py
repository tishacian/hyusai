"""Durable LLM attempts, versioned tariffs and shared admission budgets."""

import sqlalchemy as sa

from alembic import op

revision = "146_model_usage_budgets"
down_revision = "145_evaluation_isolation"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "model_usage_tariffs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("rates", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "workspace_id", "provider", "model", "revision", name="uq_model_tariff_revision"
        ),
    )
    op.create_index("ix_model_usage_tariffs_workspace_id", "model_usage_tariffs", ["workspace_id"])
    op.create_table(
        "model_usage_calls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("request_key", sa.String(200), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        *[
            sa.Column(name, sa.String(36), nullable=True)
            for name in (
                "system_id",
                "root_system_id",
                "run_id",
                "root_run_id",
                "invocation_id",
                "job_id",
                "worker_job_id",
                "campaign_id",
                "evaluation_id",
                "actor_user_id",
            )
        ],
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("traffic", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("returned_model", sa.String(200), nullable=True),
        sa.Column("operation", sa.String(40), nullable=False),
        sa.Column("provider_request_id", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        *[
            sa.Column(name, sa.BigInteger(), nullable=True)
            for name in (
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "cached_input_tokens",
                "cache_write_tokens",
                "reasoning_tokens",
                "reserved_tokens",
            )
        ],
        sa.Column("usage_coverage", sa.String(20), nullable=False),
        sa.Column("reserved_amount", sa.Numeric(24, 12), nullable=True),
        sa.Column("amount", sa.Numeric(24, 12), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column(
            "tariff_id", sa.String(36), sa.ForeignKey("model_usage_tariffs.id"), nullable=True
        ),
        sa.Column("tariff_snapshot", sa.JSON(), nullable=True),
        sa.Column("diagnostic", sa.String(160), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.UniqueConstraint("workspace_id", "request_key", name="uq_model_usage_request"),
    )
    for key in (
        "workspace_id",
        "system_id",
        "root_system_id",
        "run_id",
        "root_run_id",
        "invocation_id",
        "job_id",
        "worker_job_id",
        "campaign_id",
        "evaluation_id",
        "started_at",
    ):
        op.create_index("ix_model_usage_calls_" + key, "model_usage_calls", [key])
    op.create_index(
        "ix_model_usage_workspace_started",
        "model_usage_calls",
        ["workspace_id", "started_at", "id"],
    )
    op.create_table(
        "model_usage_budget_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("scope_key", sa.String(80), nullable=False),
        sa.Column("system_id", sa.String(36), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("timezone", sa.String(80), nullable=False),
        sa.Column("max_tokens", sa.BigInteger(), nullable=True),
        sa.Column("reconciliation_required", sa.Boolean(), nullable=False),
        sa.Column("currency_limits", sa.JSON(), nullable=False),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("history", sa.JSON(), nullable=False),
        sa.UniqueConstraint("workspace_id", "scope_key", name="uq_model_budget_scope"),
    )
    for key in ("workspace_id", "system_id"):
        op.create_index(
            "ix_model_usage_budget_policies_" + key, "model_usage_budget_policies", [key]
        )
    op.create_table(
        "model_usage_budget_buckets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "policy_id",
            sa.String(36),
            sa.ForeignKey("model_usage_budget_policies.id"),
            nullable=False,
        ),
        sa.Column("period_start", sa.DateTime(), nullable=False),
        sa.Column("period_end", sa.DateTime(), nullable=False),
        sa.Column("consumed_tokens", sa.BigInteger(), nullable=False),
        sa.Column("reserved_tokens", sa.BigInteger(), nullable=False),
        sa.Column("consumed_amounts", sa.JSON(), nullable=False),
        sa.Column("reserved_amounts", sa.JSON(), nullable=False),
        sa.UniqueConstraint("policy_id", "period_start", name="uq_model_budget_period"),
    )
    op.create_index(
        "ix_model_usage_budget_buckets_policy_id", "model_usage_budget_buckets", ["policy_id"]
    )
    op.create_table(
        "model_usage_reservations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("call_id", sa.String(36), sa.ForeignKey("model_usage_calls.id"), nullable=False),
        sa.Column(
            "bucket_id",
            sa.String(36),
            sa.ForeignKey("model_usage_budget_buckets.id"),
            nullable=False,
        ),
        sa.Column("reserved_tokens", sa.BigInteger(), nullable=False),
        sa.Column("reserved_amount", sa.Numeric(24, 12), nullable=False),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("settled_tokens", sa.BigInteger(), nullable=True),
        sa.Column("settled_amount", sa.Numeric(24, 12), nullable=True),
        sa.Column("released", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("call_id", "bucket_id", name="uq_model_usage_allocation"),
    )
    for key in ("call_id", "bucket_id"):
        op.create_index("ix_model_usage_reservations_" + key, "model_usage_reservations", [key])


def downgrade():
    for table in (
        "model_usage_reservations",
        "model_usage_budget_buckets",
        "model_usage_budget_policies",
        "model_usage_calls",
        "model_usage_tariffs",
    ):
        op.drop_table(table)
