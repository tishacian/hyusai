"""Nightly public retrieval bench runs.

Revision ID: 125_retrieval_bench_runs
Revises: 124_secret_registry
"""

import sqlalchemy as sa

from alembic import op

revision = "125_retrieval_bench_runs"
down_revision = "124_secret_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retrieval_bench_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("bench", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("git_sha", sa.String(length=40), nullable=True),
        sa.Column("k", sa.Integer(), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("recall_at_k", sa.Float(), nullable=True),
        sa.Column("supporting_fact_rate", sa.Float(), nullable=True),
        sa.Column("mean_latency_ms", sa.Float(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running','completed','failed','skipped')",
            name="ck_retrieval_bench_runs_status",
        ),
    )
    op.create_index("ix_retrieval_bench_runs_bench", "retrieval_bench_runs", ["bench"])
    op.create_index("ix_retrieval_bench_runs_started_at", "retrieval_bench_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_retrieval_bench_runs_started_at", table_name="retrieval_bench_runs")
    op.drop_index("ix_retrieval_bench_runs_bench", table_name="retrieval_bench_runs")
    op.drop_table("retrieval_bench_runs")
