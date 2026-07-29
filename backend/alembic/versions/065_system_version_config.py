"""Add allowlisted configuration evidence to immutable System versions.

Revision ID: 065_system_version_config
Revises: 064_run_dispatch_outbox

The column is nullable by design: existing rows remain valid and existing
flow-only version writes retain their historical behaviour.  Application code
owns the positive allowlist; the database stores only the validated JSON
envelope.
"""
import sqlalchemy as sa

from alembic import op

revision = "065_system_version_config"
down_revision = "064_run_dispatch_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_versions",
        sa.Column("configuration_snapshot", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("system_versions", "configuration_snapshot")
