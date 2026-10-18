"""Runtime requalification attestations (metadata only, no rows or predictions).

The revision id is shorter than the lot's working name on purpose:
``alembic_version.version_num`` is varchar(32).
"""

import sqlalchemy as sa

from alembic import op

revision = "139_mlops_requalification"
down_revision = "138_activity_measures"
branch_labels = depends_on = None

ACTIVE = "verdict = 'qualified' AND revoked_at IS NULL"


def upgrade():
    op.create_table(
        "ml_runtime_attestations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("model_id", sa.String(length=36), nullable=False),
        sa.Column("artifact_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("producer_runtime", sa.JSON(), nullable=False),
        sa.Column("reader_runtime", sa.JSON(), nullable=False),
        sa.Column("reader_digest", sa.String(length=64), nullable=False),
        sa.Column("reference_sha256", sa.String(length=64), nullable=False),
        sa.Column("rows_compared", sa.Integer(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("tolerances", sa.JSON(), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_by", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "verdict IN ('qualified', 'failed')", name="ck_ml_runtime_attestation_verdict"
        ),
        sa.ForeignKeyConstraint(["model_id"], ["ml_models.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ml_runtime_attestations_model",
        "ml_runtime_attestations",
        ["model_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_ml_runtime_attestations_workspace",
        "ml_runtime_attestations",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "uq_ml_runtime_attestation_active",
        "ml_runtime_attestations",
        ["model_id", "artifact_fingerprint", "reader_digest"],
        unique=True,
        postgresql_where=sa.text(ACTIVE),
        sqlite_where=sa.text(ACTIVE),
    )


def downgrade():
    # An attestation is the only record of why a model loads under another
    # runtime; dropping it would silently turn attested serving into refusals
    # and erase the evidence. Revoke or archive explicitly before downgrading.
    if op.get_bind().execute(sa.text("SELECT 1 FROM ml_runtime_attestations LIMIT 1")).first():
        raise RuntimeError(
            "ML_REQUALIFICATION_DOWNGRADE_REFUSED: runtime attestations require this schema"
        )
    op.drop_table("ml_runtime_attestations")
