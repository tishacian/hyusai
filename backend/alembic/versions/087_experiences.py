"""Experience draft, release, and deployment tables.

Revision ID: 087_experiences
Revises: 086_system_bindings

Additive. Empty on a fresh install. Publish and deploy stay separate:
creating a release never writes a channel pointer.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "087_experiences"
down_revision = "086_system_bindings"
branch_labels = None
depends_on = None


def _enum_check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    op.create_table(
        "experiences",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("pattern", sa.String(length=32), nullable=False),
        sa.Column("languages", sa.JSON(), nullable=False),
        sa.Column("theme", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            _enum_check(
                "pattern",
                (
                    "assistant",
                    "form_result",
                    "queue",
                    "approval",
                    "dashboard",
                    "mission_cockpit",
                ),
            ),
            name="ck_experiences_pattern",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "slug",
            name="uq_experiences_workspace_slug",
        ),
    )
    op.create_index(
        "ix_experiences_workspace_id",
        "experiences",
        ["workspace_id"],
        unique=False,
    )

    op.create_table(
        "experience_draft_revisions",
        sa.Column("experience_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("pages", sa.JSON(), nullable=False),
        sa.Column("binding_keys", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_experience_draft_revisions_revision_positive",
        ),
        sa.ForeignKeyConstraint(
            ["experience_id"], ["experiences.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("experience_id"),
    )
    op.create_index(
        "ix_experience_draft_revisions_workspace_id",
        "experience_draft_revisions",
        ["workspace_id"],
        unique=False,
    )

    op.create_table(
        "experience_releases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("experience_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("release_number", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("pages", sa.JSON(), nullable=False),
        sa.Column("bindings_snapshot", sa.JSON(), nullable=False),
        sa.Column("access_snapshot", sa.JSON(), nullable=False),
        sa.Column("languages", sa.JSON(), nullable=False),
        sa.Column("theme", sa.JSON(), nullable=False),
        sa.Column("renderer_version", sa.String(length=80), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "release_number >= 1",
            name="ck_experience_releases_number_positive",
        ),
        sa.ForeignKeyConstraint(
            ["experience_id"], ["experiences.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "experience_id",
            "release_number",
            name="uq_experience_releases_experience_number",
        ),
    )
    op.create_index(
        "ix_experience_releases_experience_id",
        "experience_releases",
        ["experience_id"],
        unique=False,
    )
    op.create_index(
        "ix_experience_releases_workspace_id",
        "experience_releases",
        ["workspace_id"],
        unique=False,
    )

    op.create_table(
        "experience_deployments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("experience_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("release_id", sa.String(length=36), nullable=False),
        sa.Column("previous_release_id", sa.String(length=36), nullable=True),
        sa.Column("audience", sa.JSON(), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            _enum_check("channel", ("pilot", "live")),
            name="ck_experience_deployments_channel",
        ),
        sa.ForeignKeyConstraint(
            ["experience_id"], ["experiences.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["release_id"], ["experience_releases.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["previous_release_id"],
            ["experience_releases.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "experience_id",
            "channel",
            name="uq_experience_deployments_experience_channel",
        ),
    )
    op.create_index(
        "ix_experience_deployments_experience_id",
        "experience_deployments",
        ["experience_id"],
        unique=False,
    )
    op.create_index(
        "ix_experience_deployments_workspace_id",
        "experience_deployments",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_experience_deployments_release_id",
        "experience_deployments",
        ["release_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_experience_deployments_release_id",
        table_name="experience_deployments",
    )
    op.drop_index(
        "ix_experience_deployments_workspace_id",
        table_name="experience_deployments",
    )
    op.drop_index(
        "ix_experience_deployments_experience_id",
        table_name="experience_deployments",
    )
    op.drop_table("experience_deployments")
    op.drop_index(
        "ix_experience_releases_workspace_id",
        table_name="experience_releases",
    )
    op.drop_index(
        "ix_experience_releases_experience_id",
        table_name="experience_releases",
    )
    op.drop_table("experience_releases")
    op.drop_index(
        "ix_experience_draft_revisions_workspace_id",
        table_name="experience_draft_revisions",
    )
    op.drop_table("experience_draft_revisions")
    op.drop_index("ix_experiences_workspace_id", table_name="experiences")
    op.drop_table("experiences")
