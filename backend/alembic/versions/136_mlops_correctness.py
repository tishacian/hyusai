"""Explicit per-sample ground truth; ambiguous historical batch labels stay untouched."""

import sqlalchemy as sa

from alembic import op

revision = "136_mlops_correctness"
down_revision = "135_mlops_governance"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ml_prediction_feedback",
        sa.Column("sample_id", sa.String(64), primary_key=True),
        sa.Column(
            "prediction_id",
            sa.String(36),
            sa.ForeignKey("ml_predictions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sample_index", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("labeled_at", sa.DateTime(), nullable=False),
        sa.Column("labeled_by", sa.String(36)),
        sa.UniqueConstraint(
            "prediction_id", "sample_index", name="uq_ml_feedback_prediction_sample"
        ),
    )
    op.create_index(
        "ix_ml_prediction_feedback_prediction_id", "ml_prediction_feedback", ["prediction_id"]
    )
    op.create_index(
        "ix_ml_prediction_feedback_workspace_id", "ml_prediction_feedback", ["workspace_id"]
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM ml_prediction_feedback LIMIT 1")).first():
        raise RuntimeError("ML_FEEDBACK_DOWNGRADE_REFUSED: retained sample labels require this schema")
    op.drop_table("ml_prediction_feedback")
