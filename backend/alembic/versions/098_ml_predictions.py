"""Journal every serving call so drift and feedback have something to measure.

A model card without a prediction log can show a fit and not whether the fit
still holds. One row per call — playground, API key, or batch score — carries
the version that answered, a capped payload, the output and a place for the
ground truth to land later.

Revision ID: 098_ml_predictions
Revises: 097_ml_training_plane
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "098_ml_predictions"
down_revision = "097_ml_training_plane"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ml_predictions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "model_id",
            sa.String(36),
            sa.ForeignKey("ml_models.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "served_id",
            sa.String(36),
            sa.ForeignKey("ml_models.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("served_version", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("caller", sa.String(32), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("scores_json", sa.JSON(), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("dataset_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column("labeled_at", sa.DateTime(), nullable=True),
        sa.Column("labeled_by", sa.String(36), nullable=True),
    )
    op.create_index("ix_ml_predictions_workspace_id", "ml_predictions", ["workspace_id"])
    op.create_index("ix_ml_predictions_model_id", "ml_predictions", ["model_id"])
    op.create_index("ix_ml_predictions_served_id", "ml_predictions", ["served_id"])
    op.create_index("ix_ml_predictions_slug", "ml_predictions", ["slug"])
    op.create_index("ix_ml_predictions_created_at", "ml_predictions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_ml_predictions_created_at", table_name="ml_predictions")
    op.drop_index("ix_ml_predictions_slug", table_name="ml_predictions")
    op.drop_index("ix_ml_predictions_served_id", table_name="ml_predictions")
    op.drop_index("ix_ml_predictions_model_id", table_name="ml_predictions")
    op.drop_index("ix_ml_predictions_workspace_id", table_name="ml_predictions")
    op.drop_table("ml_predictions")
