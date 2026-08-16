"""Keep Experience action idempotency stable across deployments.

Revision ID: 093_experience_run_idempotency
Revises: 092_experience_access_policy
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "093_experience_run_idempotency"
down_revision = "092_experience_access_policy"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "uq_runs_experience_idempotency_key"


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("experience_idempotency_key", sa.String(64), nullable=True))
        batch.create_unique_constraint(CONSTRAINT_NAME, ["experience_idempotency_key"])


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.drop_constraint(CONSTRAINT_NAME, type_="unique")
        batch.drop_column("experience_idempotency_key")
