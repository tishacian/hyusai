"""Add the tabular data plane: datasets, ML models and scoped predict keys.

Revision ID: 096_tabular_data_plane
Revises: 095_python_recipes
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "096_tabular_data_plane"
down_revision = "095_python_recipes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tabular_datasets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False, server_default="upload"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("status_detail", sa.String(300), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("storage_key", sa.String(500), nullable=True),
        sa.Column("upload_key", sa.String(500), nullable=True),
        sa.Column("original_filename", sa.String(400), nullable=True),
        sa.Column("content_type", sa.String(200), nullable=True),
        sa.Column("row_count", sa.BigInteger(), nullable=True),
        sa.Column("column_count", sa.Integer(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("schema_json", sa.JSON(), nullable=True),
        sa.Column("preview_json", sa.JSON(), nullable=True),
        sa.Column("stats_json", sa.JSON(), nullable=True),
        sa.Column("run_id", sa.String(36), nullable=True),
        sa.Column("node_id", sa.String(160), nullable=True),
        sa.Column("parent_ids", sa.JSON(), nullable=True),
        sa.Column("produced_by", sa.String(120), nullable=True),
        sa.Column("lineage_json", sa.JSON(), nullable=True),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(), nullable=True),
        sa.Column("ingest_duration_ms", sa.Float(), nullable=True),
        sa.UniqueConstraint(
            "workspace_id",
            "slug",
            "version",
            name="uq_tabular_datasets_workspace_slug_version",
        ),
    )
    op.create_index(
        "ix_tabular_datasets_workspace_id", "tabular_datasets", ["workspace_id"]
    )
    op.create_index("ix_tabular_datasets_slug", "tabular_datasets", ["slug"])
    op.create_index("ix_tabular_datasets_status", "tabular_datasets", ["status"])
    op.create_index("ix_tabular_datasets_source", "tabular_datasets", ["source"])
    op.create_index("ix_tabular_datasets_run_id", "tabular_datasets", ["run_id"])

    op.create_table(
        "ml_models",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("task", sa.String(20), nullable=False),
        sa.Column("algo", sa.String(80), nullable=False),
        sa.Column("target", sa.String(200), nullable=False),
        sa.Column("features", sa.JSON(), nullable=True),
        sa.Column("params_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("status_detail", sa.String(300), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "is_champion", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "dataset_id",
            sa.String(36),
            sa.ForeignKey("tabular_datasets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("dataset_slug", sa.String(200), nullable=True),
        sa.Column("row_count", sa.BigInteger(), nullable=True),
        sa.Column("test_size", sa.Float(), nullable=True),
        sa.Column("cross_validation", sa.Integer(), nullable=True),
        sa.Column("metrics_json", sa.JSON(), nullable=True),
        sa.Column("signature_json", sa.JSON(), nullable=True),
        sa.Column("input_example_json", sa.JSON(), nullable=True),
        sa.Column("classes_json", sa.JSON(), nullable=True),
        sa.Column("model_uri", sa.String(500), nullable=True),
        sa.Column("artifact_bytes", sa.BigInteger(), nullable=True),
        sa.Column("mlflow_run_id", sa.String(64), nullable=True),
        sa.Column("mlflow_model_name", sa.String(300), nullable=True),
        sa.Column("predict_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_predict_at", sa.DateTime(), nullable=True),
        sa.Column("run_id", sa.String(36), nullable=True),
        sa.Column("node_id", sa.String(160), nullable=True),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
        sa.Column("published_skill_slug", sa.String(200), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("trained_at", sa.DateTime(), nullable=True),
        sa.Column("train_duration_ms", sa.Float(), nullable=True),
        sa.UniqueConstraint(
            "workspace_id",
            "slug",
            "version",
            name="uq_ml_models_workspace_slug_version",
        ),
    )
    op.create_index("ix_ml_models_workspace_id", "ml_models", ["workspace_id"])
    op.create_index("ix_ml_models_slug", "ml_models", ["slug"])
    op.create_index("ix_ml_models_status", "ml_models", ["status"])
    op.create_index("ix_ml_models_dataset_id", "ml_models", ["dataset_id"])
    op.create_index("ix_ml_models_run_id", "ml_models", ["run_id"])

    op.create_table(
        "ml_model_api_keys",
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
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("key_sha256", sa.String(64), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_ml_model_api_keys_workspace_id", "ml_model_api_keys", ["workspace_id"]
    )
    op.create_index("ix_ml_model_api_keys_model_id", "ml_model_api_keys", ["model_id"])
    op.create_index(
        "ix_ml_model_api_keys_key_prefix", "ml_model_api_keys", ["key_prefix"]
    )
    op.create_index(
        "ix_ml_model_api_keys_key_sha256", "ml_model_api_keys", ["key_sha256"]
    )


def downgrade() -> None:
    op.drop_index("ix_ml_model_api_keys_key_sha256", table_name="ml_model_api_keys")
    op.drop_index("ix_ml_model_api_keys_key_prefix", table_name="ml_model_api_keys")
    op.drop_index("ix_ml_model_api_keys_model_id", table_name="ml_model_api_keys")
    op.drop_index("ix_ml_model_api_keys_workspace_id", table_name="ml_model_api_keys")
    op.drop_table("ml_model_api_keys")
    op.drop_index("ix_ml_models_run_id", table_name="ml_models")
    op.drop_index("ix_ml_models_dataset_id", table_name="ml_models")
    op.drop_index("ix_ml_models_status", table_name="ml_models")
    op.drop_index("ix_ml_models_slug", table_name="ml_models")
    op.drop_index("ix_ml_models_workspace_id", table_name="ml_models")
    op.drop_table("ml_models")
    op.drop_index("ix_tabular_datasets_run_id", table_name="tabular_datasets")
    op.drop_index("ix_tabular_datasets_source", table_name="tabular_datasets")
    op.drop_index("ix_tabular_datasets_status", table_name="tabular_datasets")
    op.drop_index("ix_tabular_datasets_slug", table_name="tabular_datasets")
    op.drop_index("ix_tabular_datasets_workspace_id", table_name="tabular_datasets")
    op.drop_table("tabular_datasets")
