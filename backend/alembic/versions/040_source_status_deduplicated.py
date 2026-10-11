"""Allow 'deduplicated' status on knowledge collection sources.

Revision ID: 040_source_status_deduplicated
Revises: 039_cleanup_andritz_chat_surface
Create Date: 2026-06-10
"""
from __future__ import annotations

from alembic import op


revision = "040_source_status_deduplicated"
down_revision = "039_cleanup_andritz_chat_surface"
branch_labels = None
depends_on = None


_TABLE = "knowledge_collection_sources"
_CONSTRAINT = "ck_knowledge_collection_sources_status"
_OLD_STATUSES = "'queued', 'ingesting', 'indexed', 'ready', 'error', 'deleted'"
_NEW_STATUSES = _OLD_STATUSES + ", 'deduplicated'"


def _replace_constraint(statuses: str) -> None:
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_CONSTRAINT} "
        f"CHECK (status IN ({statuses}))"
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite dev databases are created via metadata create_all and already
        # carry the new constraint; rebuilding the table there is not worth it.
        return
    _replace_constraint(_NEW_STATUSES)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"UPDATE {_TABLE} SET status = 'deleted' WHERE status = 'deduplicated'")
    _replace_constraint(_OLD_STATUSES)
