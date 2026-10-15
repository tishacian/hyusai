"""Model credentials, retention consent and shared inference admission."""

from datetime import datetime, timedelta

import sqlalchemy as sa

from alembic import op

revision = "135_mlops_governance"
down_revision = "134_execution_control"
branch_labels = depends_on = None


def upgrade():
    for column in (
        sa.Column("expires_at", sa.DateTime()),
        sa.Column("revoke_after", sa.DateTime()),
        sa.Column("pinned_version", sa.Integer()),
        sa.Column("allowed_cidrs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("scope", sa.String(24), nullable=False, server_default="predict"),
    ):
        op.add_column("ml_model_api_keys", column)
    # Existing integrations get a finite transition period, never an immediate
    # expiry based on their historical creation date.
    op.get_bind().execute(
        sa.text("UPDATE ml_model_api_keys SET expires_at = :expiry WHERE expires_at IS NULL"),
        {"expiry": datetime.utcnow() + timedelta(days=365)},
    )
    op.add_column(
        "ml_predictions",
        sa.Column("input_storage_allowed", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "ml_admission_counters",
        sa.Column("scope", sa.String(96), primary_key=True),
        sa.Column("window_at", sa.DateTime(), primary_key=True),
        sa.Column("requests", sa.Integer(), nullable=False),
        sa.Column("rows", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "ml_workspace_locks",
        sa.Column("workspace_id", sa.String(36), primary_key=True),
        sa.Column("generation", sa.BigInteger(), nullable=False),
    )


def downgrade():
    db = op.get_bind()
    if (
        db.execute(sa.text("SELECT 1 FROM ml_model_api_keys LIMIT 1")).first()
        or db.execute(
            sa.text("SELECT 1 FROM ml_predictions WHERE input_storage_allowed = false LIMIT 1")
        ).first()
    ):
        raise RuntimeError(
            "ML_GOVERNANCE_DOWNGRADE_REFUSED: retained credential or consent guarantees require this schema"
        )
    op.drop_table("ml_workspace_locks")
    op.drop_table("ml_admission_counters")
    op.drop_column("ml_predictions", "input_storage_allowed")
    for name in ("scope", "allowed_cidrs", "pinned_version", "revoke_after", "expires_at"):
        op.drop_column("ml_model_api_keys", name)
