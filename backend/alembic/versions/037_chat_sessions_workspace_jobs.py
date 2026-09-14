"""Durable chat sessions and workspace deep retrieval jobs.

Revision ID: 037_chat_sessions_workspace_jobs
Revises: 036_retrieval_job_kinds
Create Date: 2026-06-03

Cross-dialect note (2026-09-13): the check constraint on ``sessions`` and
the four foreign keys on ``workspace_jobs`` were added with bare
``op.create_check_constraint`` / ``op.create_foreign_key``. Both are ALTER
TABLE ... ADD CONSTRAINT, which SQLite does not have at all, so a clean
bootstrap died here with ``NotImplementedError: No support for ALTER of
constraints in SQLite dialect``.

Everything that touches a constraint now goes through ``batch_alter_table``.
On PostgreSQL batch mode emits the very same ALTER statements in the same
order; on SQLite it copies the table and replays the constraints, which is
the only way to get them there. The constraints were already named, so the
schema this produces is unchanged on both sides.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "037_chat_sessions_workspace_jobs"
down_revision = "036_retrieval_job_kinds"
branch_labels = None
depends_on = None


SESSIONS_STATUS_CHECK = "ck_sessions_status"

# (constraint name, column, referred table) for the workspace_jobs links.
WORKSPACE_JOB_LINKS = (
    ("fk_workspace_jobs_session_id_sessions", "session_id", "sessions"),
    (
        "fk_workspace_jobs_collection_id_knowledge_collections",
        "collection_id",
        "knowledge_collections",
    ),
    ("fk_workspace_jobs_parent_message_id_messages", "parent_message_id", "messages"),
    ("fk_workspace_jobs_message_id_messages", "message_id", "messages"),
)


def upgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        # The default is what makes the new NOT NULL column legal for rows
        # that already exist, and it is also what keeps them inside the
        # check constraint added in the same breath.
        batch.add_column(
            sa.Column("status", sa.String(length=32), nullable=False, server_default="active")
        )
        batch.add_column(sa.Column("context_signature", sa.String(length=512), nullable=True))
        batch.add_column(sa.Column("archived_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
        batch.create_check_constraint(
            SESSIONS_STATUS_CHECK,
            "status IN ('active', 'archived', 'deleted')",
        )
    op.create_index("ix_sessions_context_signature", "sessions", ["context_signature"])
    op.create_index(
        "ix_sessions_workspace_user_status", "sessions", ["workspace_id", "user_id", "status"]
    )

    with op.batch_alter_table("workspace_jobs") as batch:
        for _name, column, _referent in WORKSPACE_JOB_LINKS:
            batch.add_column(sa.Column(column, sa.String(length=36), nullable=True))
        for name, column, referent in WORKSPACE_JOB_LINKS:
            batch.create_foreign_key(
                name,
                referent,
                [column],
                ["id"],
                ondelete="SET NULL",
            )
    op.create_index("ix_workspace_jobs_session_id", "workspace_jobs", ["session_id"])
    op.create_index("ix_workspace_jobs_collection_id", "workspace_jobs", ["collection_id"])
    op.create_index("ix_workspace_jobs_parent_message_id", "workspace_jobs", ["parent_message_id"])
    op.create_index("ix_workspace_jobs_message_id", "workspace_jobs", ["message_id"])
    op.create_index(
        "ix_workspace_jobs_workspace_session_status",
        "workspace_jobs",
        ["workspace_id", "session_id", "status"],
    )
    op.create_index(
        "ix_workspace_jobs_workspace_user_status",
        "workspace_jobs",
        ["workspace_id", "created_by_user_id", "status"],
    )
    op.create_index(
        "ix_workspace_jobs_workspace_kind_status",
        "workspace_jobs",
        ["workspace_id", "kind", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_workspace_jobs_workspace_kind_status", table_name="workspace_jobs")
    op.drop_index("ix_workspace_jobs_workspace_user_status", table_name="workspace_jobs")
    op.drop_index("ix_workspace_jobs_workspace_session_status", table_name="workspace_jobs")
    op.drop_index("ix_workspace_jobs_message_id", table_name="workspace_jobs")
    op.drop_index("ix_workspace_jobs_parent_message_id", table_name="workspace_jobs")
    op.drop_index("ix_workspace_jobs_collection_id", table_name="workspace_jobs")
    op.drop_index("ix_workspace_jobs_session_id", table_name="workspace_jobs")
    with op.batch_alter_table("workspace_jobs") as batch:
        for name, column, _referent in reversed(WORKSPACE_JOB_LINKS):
            batch.drop_constraint(name, type_="foreignkey")
            batch.drop_column(column)

    op.drop_index("ix_sessions_workspace_user_status", table_name="sessions")
    op.drop_index("ix_sessions_context_signature", table_name="sessions")
    with op.batch_alter_table("sessions") as batch:
        batch.drop_constraint(SESSIONS_STATUS_CHECK, type_="check")
        batch.drop_column("deleted_at")
        batch.drop_column("archived_at")
        batch.drop_column("context_signature")
        batch.drop_column("status")
