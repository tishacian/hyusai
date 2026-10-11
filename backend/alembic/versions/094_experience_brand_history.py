"""Add safe Experience identity fields and durable lifecycle receipts.

Revision ID: 094_experience_brand_history
Revises: 093_experience_run_idempotency
"""

from __future__ import annotations

from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "094_experience_brand_history"
down_revision = "093_experience_run_idempotency"
branch_labels = None
depends_on = None

RELEASE_REQUEST_CONSTRAINT = "uq_experience_releases_creation_request"


def upgrade() -> None:
    op.add_column("experiences", sa.Column("description", sa.String(500), nullable=True))
    op.add_column("experiences", sa.Column("emblem", sa.String(32), nullable=True))
    with op.batch_alter_table("experience_releases") as batch:
        batch.add_column(
            sa.Column("creation_request_sha256", sa.String(64), nullable=True)
        )
        batch.create_unique_constraint(
            RELEASE_REQUEST_CONSTRAINT,
            ["experience_id", "creation_request_sha256"],
        )
    op.add_column(
        "experience_deployments",
        sa.Column("last_mutation_sha256", sa.String(64), nullable=True),
    )
    op.add_column(
        "experience_deployments",
        sa.Column("previous_audience", sa.JSON(), nullable=True),
    )
    op.create_table(
        "experience_draft_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "experience_id",
            sa.String(36),
            sa.ForeignKey("experiences.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("pages", sa.JSON(), nullable=False),
        sa.Column("binding_keys", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("saved_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "experience_id",
            "revision",
            name="uq_experience_draft_history_experience_revision",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_experience_draft_history_revision_positive",
        ),
    )
    op.create_index(
        "ix_experience_draft_history_experience_id",
        "experience_draft_history",
        ["experience_id"],
    )
    op.create_index(
        "ix_experience_draft_history_workspace_id",
        "experience_draft_history",
        ["workspace_id"],
    )

    drafts = sa.table(
        "experience_draft_revisions",
        sa.column("experience_id"),
        sa.column("workspace_id"),
        sa.column("revision"),
        sa.column("pages", sa.JSON()),
        sa.column("binding_keys", sa.JSON()),
        sa.column("content_sha256"),
        sa.column("updated_by"),
        sa.column("updated_at", sa.DateTime()),
    )
    history = sa.table(
        "experience_draft_history",
        sa.column("id"),
        sa.column("experience_id"),
        sa.column("workspace_id"),
        sa.column("revision"),
        sa.column("pages", sa.JSON()),
        sa.column("binding_keys", sa.JSON()),
        sa.column("content_sha256"),
        sa.column("saved_by"),
        sa.column("created_at", sa.DateTime()),
    )
    bind = op.get_bind()
    for row in bind.execute(sa.select(drafts)).all():
        values = row._mapping
        bind.execute(
            history.insert().values(
                id=str(uuid4()),
                experience_id=values["experience_id"],
                workspace_id=values["workspace_id"],
                revision=values["revision"],
                pages=values["pages"],
                binding_keys=values["binding_keys"],
                content_sha256=values["content_sha256"],
                saved_by=values["updated_by"],
                created_at=values["updated_at"],
            )
        )


def downgrade() -> None:
    op.drop_index(
        "ix_experience_draft_history_workspace_id",
        table_name="experience_draft_history",
    )
    op.drop_index(
        "ix_experience_draft_history_experience_id",
        table_name="experience_draft_history",
    )
    op.drop_table("experience_draft_history")
    op.drop_column("experience_deployments", "previous_audience")
    op.drop_column("experience_deployments", "last_mutation_sha256")
    with op.batch_alter_table("experience_releases") as batch:
        batch.drop_constraint(RELEASE_REQUEST_CONSTRAINT, type_="unique")
        batch.drop_column("creation_request_sha256")
    op.drop_column("experiences", "emblem")
    op.drop_column("experiences", "description")
