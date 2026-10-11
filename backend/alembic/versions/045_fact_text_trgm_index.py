"""GIN pg_trgm indexes on knowledge_document_facts for fact-scope inference.

The corpus planner scopes retrieval to candidate documents by ILIKE-matching the
query's discriminating terms against the structured fact fields (subject,
value_raw, section_path, document_filename). On a large corpus (~1.7M facts) the
unindexed OR(ILIKE) was a ~48s sequential scan, which forced fact-scope to be
deep-only and let high-volume common terms crowd out the answer-bearing fact.

These GIN trigram indexes turn the bounded candidate scan into an index-backed
BitmapOr (single-digit seconds), so balanced (interactive) retrieval can run
fact-scope on large collections too. The free-text ``content`` column is
intentionally left unindexed: candidate gating no longer touches it (it is the
main source of ubiquitous-term noise and the heaviest column to index).

Revision ID: 045_fact_text_trgm_index
Revises: 044_andritz_business_nav
Create Date: 2026-06-19
"""
from __future__ import annotations

from alembic import op


revision = "045_fact_text_trgm_index"
down_revision = "044_andritz_business_nav"
branch_labels = None
depends_on = None


_TABLE = "knowledge_document_facts"
_INDEXES = {
    "ix_kdf_subject_trgm": "subject",
    "ix_kdf_value_raw_trgm": "value_raw",
    "ix_kdf_section_path_trgm": "section_path",
    "ix_kdf_document_filename_trgm": "document_filename",
}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite dev databases use plain LIKE scans on small data; pg_trgm is a
        # PostgreSQL extension and not available there.
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for index_name, column in _INDEXES.items():
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {index_name} ON {_TABLE} "
            f"USING gin ({column} gin_trgm_ops)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for index_name in _INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {index_name}")
