"""Hub artefacts, workspace grants, import reservations and RAG generations.

Revision ID: 123_huggingface_connector
Revises: 122_ml_families
"""

import sqlalchemy as sa

from alembic import op

revision = "123_huggingface_connector"
down_revision = "122_ml_families"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hf_platform_config",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("connection", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("policy", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("limits", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False, primary_key=False),
    )
    op.create_table(
        "hf_license_acceptances",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(length=36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=False,
        ),
        sa.Column("hub_endpoint", sa.String(length=500), nullable=False, primary_key=False),
        sa.Column("kind", sa.String(length=16), nullable=False, primary_key=False),
        sa.Column("repo_id", sa.String(length=255), nullable=False, primary_key=False),
        sa.Column("revision", sa.String(length=40), nullable=False, primary_key=False),
        sa.Column("license_digest", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("license_text", sa.Text(), nullable=False, primary_key=False),
        sa.Column("accepted_by", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=False, primary_key=False),
        sa.UniqueConstraint(
            "workspace_id",
            "hub_endpoint",
            "kind",
            "repo_id",
            "revision",
            "license_digest",
            "policy_version",
            name="uq_hf_license_acceptance",
        ),
    )
    op.create_index(
        "ix_hf_license_acceptances_workspace_id",
        "hf_license_acceptances",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "hf_license_exceptions",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(length=36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=False,
        ),
        sa.Column("hub_endpoint", sa.String(length=500), nullable=False, primary_key=False),
        sa.Column("kind", sa.String(length=16), nullable=False, primary_key=False),
        sa.Column("repo_id", sa.String(length=255), nullable=False, primary_key=False),
        sa.Column("revision", sa.String(length=40), nullable=False, primary_key=False),
        sa.Column("license_digest", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("license_text", sa.Text(), nullable=False, primary_key=False),
        sa.Column("reason", sa.Text(), nullable=False, primary_key=False),
        sa.Column("created_by", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, primary_key=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True, primary_key=False),
    )
    op.create_index(
        "ix_hf_license_exceptions_workspace_id",
        "hf_license_exceptions",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "hub_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("identity_hash", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("hub_endpoint", sa.String(length=500), nullable=False, primary_key=False),
        sa.Column("kind", sa.String(length=16), nullable=False, primary_key=False),
        sa.Column("repo_id", sa.String(length=255), nullable=False, primary_key=False),
        sa.Column("revision", sa.String(length=40), nullable=False, primary_key=False),
        sa.Column("requested_ref", sa.String(length=255), nullable=False, primary_key=False),
        sa.Column("format", sa.String(length=24), nullable=False, primary_key=False),
        sa.Column("variant", sa.String(length=255), nullable=True, primary_key=False),
        sa.Column("selection_digest", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("files_json", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("selection_json", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("manifest_key", sa.String(length=500), nullable=True, primary_key=False),
        sa.Column("total_bytes", sa.BigInteger(), nullable=False, primary_key=False),
        sa.Column("status", sa.String(length=24), nullable=False, primary_key=False),
        sa.Column("error_code", sa.String(length=80), nullable=True, primary_key=False),
        sa.Column(
            "in_catalogue", sa.Boolean(), nullable=False, primary_key=False, server_default="false"
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, primary_key=False),
        sa.Column("imported_at", sa.DateTime(), nullable=True, primary_key=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True, primary_key=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True, primary_key=False),
        sa.Column("revocation_reason", sa.Text(), nullable=True, primary_key=False),
        sa.Column("purged_at", sa.DateTime(), nullable=True, primary_key=False),
        sa.UniqueConstraint("identity_hash", name=None),
        sa.CheckConstraint("total_bytes >= 0", name="ck_hub_artifacts_bytes"),
        sa.CheckConstraint("kind IN ('model', 'dataset')", name="ck_hub_artifacts_kind"),
        sa.CheckConstraint(
            "status IN ('pending', 'fetching', 'ready', 'failed', 'revoked')",
            name="ck_hub_artifacts_status",
        ),
    )
    op.create_index("ix_hub_artifacts_status", "hub_artifacts", ["status"], unique=False)
    op.create_table(
        "hub_artifact_grants",
        sa.Column(
            "workspace_id",
            sa.String(length=36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "artifact_id",
            sa.String(length=36),
            sa.ForeignKey("hub_artifacts.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column("granted_by", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("granted_at", sa.DateTime(), nullable=False, primary_key=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True, primary_key=False),
        sa.Column("revocation_reason", sa.Text(), nullable=True, primary_key=False),
        sa.Column("license_accepted_by", sa.String(length=36), nullable=True, primary_key=False),
        sa.Column("license_accepted_at", sa.DateTime(), nullable=True, primary_key=False),
        sa.Column("license_digest", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False, primary_key=False),
    )
    op.create_table(
        "hub_artifact_usages",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(length=36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=False,
        ),
        sa.Column(
            "artifact_id",
            sa.String(length=36),
            sa.ForeignKey("hub_artifacts.id", ondelete="RESTRICT"),
            nullable=False,
            primary_key=False,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False, primary_key=False),
        sa.Column("target_id", sa.String(length=255), nullable=False, primary_key=False),
        sa.Column("status", sa.String(length=32), nullable=False, primary_key=False),
        sa.Column("details_json", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True, primary_key=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, primary_key=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False, primary_key=False),
        sa.UniqueConstraint(
            "workspace_id", "kind", "target_id", name="uq_hub_artifact_usage_target"
        ),
    )
    op.create_index(
        "ix_hub_artifact_usages_artifact_id", "hub_artifact_usages", ["artifact_id"], unique=False
    )
    op.create_index(
        "ix_hub_artifact_usages_workspace_id", "hub_artifact_usages", ["workspace_id"], unique=False
    )
    op.create_table(
        "hub_import_reservations",
        sa.Column(
            "job_id",
            sa.String(length=36),
            sa.ForeignKey("workspace_jobs.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "workspace_id",
            sa.String(length=36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=False,
        ),
        sa.Column(
            "artifact_id",
            sa.String(length=36),
            sa.ForeignKey("hub_artifacts.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=False,
        ),
        sa.Column("temporary_bytes", sa.BigInteger(), nullable=False, primary_key=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False, primary_key=False),
        sa.Column("lease_owner", sa.String(length=36), nullable=True, primary_key=False),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True, primary_key=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, primary_key=False),
    )
    op.create_index(
        "ix_hub_import_reservations_artifact_id",
        "hub_import_reservations",
        ["artifact_id"],
        unique=False,
    )
    op.create_index(
        "ix_hub_import_reservations_expires_at",
        "hub_import_reservations",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_hub_import_reservations_workspace_id",
        "hub_import_reservations",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "hub_import_requests",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(length=36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=False,
        ),
        sa.Column("request_key", sa.String(length=128), nullable=False, primary_key=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column(
            "job_id",
            sa.String(length=36),
            sa.ForeignKey("workspace_jobs.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=False,
        ),
        sa.UniqueConstraint("workspace_id", "request_key", name="uq_hub_import_request"),
    )
    # JSON has no SQLAlchemy literal renderer in Alembic's offline mode.
    # This static seed is valid SQL in both PostgreSQL and SQLite.
    op.execute(
        sa.text(
            "INSERT INTO hf_platform_config (id, connection, policy, limits, updated_at) VALUES ('default', '{}', '{}', '{}', CURRENT_TIMESTAMP)"
        )
    )
    with op.batch_alter_table("knowledge_collections") as batch:
        batch.add_column(sa.Column("embedding_artifact_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_knowledge_collections_embedding_artifact_id",
            "hub_artifacts",
            ["embedding_artifact_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.add_column(sa.Column("reranker_artifact_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_knowledge_collections_reranker_artifact_id",
            "hub_artifacts",
            ["reranker_artifact_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.add_column(sa.Column("embedding_dimension", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("embedding_params", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("active_generation", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("pending_generation", sa.String(length=36), nullable=True))
    with op.batch_alter_table("worker_jobs") as batch:
        batch.drop_constraint("ck_worker_jobs_kind", type_="check")
        batch.create_check_constraint(
            "ck_worker_jobs_kind",
            "kind IN ('document_ingest_index', 'vector_reindex', 'rag_reranker_activate', 'bm25_rebuild', 'rag_deep_retrieval', 'sparse_index_rebuild', 'summary_index_rebuild', 'qdrant_sparse_reindex')",
        )


def downgrade() -> None:
    # Refuse to remove an enum value while a queued/running task still needs it.
    bind = op.get_bind()
    if bind.execute(
        sa.text("SELECT COUNT(*) FROM worker_jobs WHERE kind = :kind"),
        {"kind": "rag_reranker_activate"},
    ).scalar():
        raise RuntimeError("Remove retired reranker jobs before downgrading the Hub schema.")
    with op.batch_alter_table("worker_jobs") as batch:
        batch.drop_constraint("ck_worker_jobs_kind", type_="check")
        batch.create_check_constraint(
            "ck_worker_jobs_kind",
            "kind IN ('document_ingest_index', 'vector_reindex', 'bm25_rebuild', 'rag_deep_retrieval', 'sparse_index_rebuild', 'summary_index_rebuild', 'qdrant_sparse_reindex')",
        )
    with op.batch_alter_table("knowledge_collections") as batch:
        batch.drop_constraint("fk_knowledge_collections_embedding_artifact_id", type_="foreignkey")
        batch.drop_constraint("fk_knowledge_collections_reranker_artifact_id", type_="foreignkey")
        batch.drop_column("pending_generation")
        batch.drop_column("active_generation")
        batch.drop_column("embedding_params")
        batch.drop_column("embedding_dimension")
        batch.drop_column("reranker_artifact_id")
        batch.drop_column("embedding_artifact_id")
    op.drop_table("hub_import_requests")
    op.drop_table("hub_import_reservations")
    op.drop_table("hub_artifact_usages")
    op.drop_table("hub_artifact_grants")
    op.drop_table("hub_artifacts")
    op.drop_table("hf_license_exceptions")
    op.drop_table("hf_license_acceptances")
    op.drop_table("hf_platform_config")
