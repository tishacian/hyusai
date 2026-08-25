"""Complete the ML model row for training and serving.

What 096 could not know until the training and predict planes existed: a fit
cannot be interrupted from inside, so a run needs a cooperative stop flag; a
probability vector is unreadable without the class labels; and a published model
is only visibly in use if the serving path counts.

Revision ID: 097_ml_training_plane
Revises: 096_tabular_data_plane
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "097_ml_training_plane"
down_revision = "096_tabular_data_plane"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ml_models",
        sa.Column(
            "cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column("ml_models", sa.Column("classes_json", sa.JSON(), nullable=True))
    op.add_column(
        "ml_models", sa.Column("artifact_bytes", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "ml_models",
        sa.Column(
            "predict_count", sa.BigInteger(), nullable=False, server_default="0"
        ),
    )
    op.add_column("ml_models", sa.Column("last_predict_at", sa.DateTime(), nullable=True))
    # The champion lookup is per (workspace, slug) on every predict call.
    op.create_index(
        "ix_ml_models_workspace_slug_champion",
        "ml_models",
        ["workspace_id", "slug", "is_champion"],
    )


def downgrade() -> None:
    op.drop_index("ix_ml_models_workspace_slug_champion", table_name="ml_models")
    op.drop_column("ml_models", "last_predict_at")
    op.drop_column("ml_models", "predict_count")
    op.drop_column("ml_models", "artifact_bytes")
    op.drop_column("ml_models", "classes_json")
    op.drop_column("ml_models", "cancel_requested")
