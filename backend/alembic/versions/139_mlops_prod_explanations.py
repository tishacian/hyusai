"""Production explanation reports of model versions (aggregated only).

Chained after 137 on its branch; the integrator re-chains it after M4.2's 138.
The id is shorter than the table name: ``alembic_version.version_num`` is
varchar(32).
"""

import sqlalchemy as sa

from alembic import op

revision = "139_mlops_prod_explanations"
down_revision = "137_mlops_operations"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "ml_production_explanations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("model_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("window_from", sa.DateTime(), nullable=True),
        sa.Column("window_until", sa.DateTime(), nullable=True),
        sa.Column("labeled_count", sa.Integer(), nullable=False),
        sa.Column("used_count", sa.Integer(), nullable=False),
        sa.Column("excluded_json", sa.JSON(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("report_json", sa.JSON(), nullable=False),
        sa.Column("fairness_badge", sa.String(length=16), nullable=True),
        sa.Column("source_digest", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["model_id"], ["ml_models.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ml_production_explanations_model_created",
        "ml_production_explanations",
        ["model_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_ml_production_explanations_workspace",
        "ml_production_explanations",
        ["workspace_id"],
        unique=False,
    )


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM ml_production_explanations LIMIT 1")).first():
        raise RuntimeError("ML_EXPLANATIONS_DOWNGRADE_NOT_EMPTY")
    op.drop_index("ix_ml_production_explanations_workspace", "ml_production_explanations")
    op.drop_index("ix_ml_production_explanations_model_created", "ml_production_explanations")
    op.drop_table("ml_production_explanations")
