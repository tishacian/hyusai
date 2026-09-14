"""Capture and run attribution.

Revision ID: 023_capture_attribution
Revises: 022_workspace_iam_foundations
Create Date: 2026-05-07

Cross-dialect note (2026-09-13): the four attribution columns were added
with a bare ``op.add_column(..., sa.ForeignKey(...))``. On PostgreSQL that
becomes ``ALTER TABLE ... ADD COLUMN`` followed by ``ALTER TABLE ... ADD
CONSTRAINT``, so it shipped and ran fine. SQLite has no ALTER for
constraints at all and the same call dies with ``NotImplementedError: No
support for ALTER of constraints in SQLite dialect`` — which is where a
clean ``alembic upgrade head`` on a new SQLite file stopped.

The fix is ``batch_alter_table`` with explicitly named foreign keys, the
same shape 014 already uses. Batch mode passes straight through to ALTER on
PostgreSQL and copy-and-move on SQLite; the copy replays constraints, which
needs each one to carry a name. Naming them changes the constraint
identifier a *new* PostgreSQL database gets (previously the server-generated
``<table>_<column>_fkey``) and nothing else — same columns, same targets,
same nullability. Databases already stamped past this revision never walk
through here.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "023_capture_attribution"
down_revision = "022_workspace_iam_foundations"
branch_labels = None
depends_on = None


# (table, column, index, foreign key name), applied in this order.
ATTRIBUTIONS = (
    (
        "expert_capture_sessions",
        "created_by_user_id",
        "ix_expert_capture_sessions_created_by_user_id",
        "fk_expert_capture_sessions_created_by_user_id_users",
    ),
    (
        "knowledge_update_proposals",
        "created_by_user_id",
        "ix_knowledge_update_proposals_created_by_user_id",
        "fk_knowledge_update_proposals_created_by_user_id_users",
    ),
    (
        "knowledge_update_proposals",
        "reviewer_user_id",
        "ix_knowledge_update_proposals_reviewer_user_id",
        "fk_knowledge_update_proposals_reviewer_user_id_users",
    ),
    (
        "runs",
        "initiated_by_user_id",
        "ix_runs_initiated_by_user_id",
        "fk_runs_initiated_by_user_id_users",
    ),
)


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    for table, column, index, fk_name in ATTRIBUTIONS:
        if column not in _columns(table):
            with op.batch_alter_table(table) as batch:
                batch.add_column(
                    sa.Column(
                        column,
                        sa.String(length=36),
                        sa.ForeignKey("users.id", name=fk_name),
                        nullable=True,
                    )
                )
        if index not in _indexes(table):
            op.create_index(index, table, [column])


def downgrade() -> None:
    for table, column, index, _fk_name in reversed(ATTRIBUTIONS):
        if index in _indexes(table):
            op.drop_index(index, table_name=table)
        if column in _columns(table):
            # Batch again: on SQLite the column carries a foreign key, and a
            # plain DROP COLUMN would leave the table constraint dangling.
            with op.batch_alter_table(table) as batch:
                batch.drop_column(column)
