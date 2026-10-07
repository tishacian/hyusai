"""Model families: which declaration trains a model, and which runtimes listen.

A model row now names its ``family`` (the tabular rows that exist are
tabular, which the server default backfills), keeps the family's problem
definition in ``spec_json`` and the fitting interpreter's identity in
``runtime_json``. ``ml_runtime_heartbeats`` is where a worker image that
trains a non-default family says it is up.

Additive only.

Revision ID: 122_ml_families
Revises: 121_provider_run_costs
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "122_ml_families"
down_revision = "121_provider_run_costs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ml_models",
        sa.Column("family", sa.String(24), nullable=False, server_default="tabular"),
    )
    op.create_index("ix_ml_models_family", "ml_models", ["family"])
    op.add_column("ml_models", sa.Column("spec_json", sa.JSON(), nullable=True))
    op.add_column("ml_models", sa.Column("runtime_json", sa.JSON(), nullable=True))
    op.create_table(
        "ml_runtime_heartbeats",
        sa.Column("runtime", sa.String(40), primary_key=True),
        sa.Column("hostname", sa.String(200), primary_key=True),
        sa.Column("queues", sa.JSON(), nullable=True),
        sa.Column("image_revision", sa.String(80), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=True),
        sa.Column("packages_json", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("seen_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_ml_runtime_heartbeats_seen_at", "ml_runtime_heartbeats", ["seen_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_ml_runtime_heartbeats_seen_at", table_name="ml_runtime_heartbeats")
    op.drop_table("ml_runtime_heartbeats")
    op.drop_column("ml_models", "runtime_json")
    op.drop_column("ml_models", "spec_json")
    op.drop_index("ix_ml_models_family", table_name="ml_models")
    op.drop_column("ml_models", "family")
