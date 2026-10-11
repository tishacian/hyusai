"""Scope RSS articles to a workspace.

``feed_articles`` had no workspace: an article belonged to whichever workspace
owned its feed source, and saving de-duplicated by URL across all workspaces,
so a workspace could receive nothing because another one had fetched the same
URL first. The column is backfilled from the article's feed source.

Rows whose source is gone, or whose source has no workspace, stay NULL: the
application never serves a NULL-workspace article (nor feed, target or filter)
to any workspace. Their count is logged here because it cannot be known
offline; nothing is deleted.

Revision ID: 120_feed_article_workspace
Revises: 119_claim_trials
Create Date: 2026-10-05
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op

revision = "120_feed_article_workspace"
down_revision = "119_claim_trials"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

INDEX = "ix_feed_articles_workspace_id"
FOREIGN_KEY = "fk_feed_articles_workspace_id"


def upgrade() -> None:
    with op.batch_alter_table("feed_articles") as batch:
        batch.add_column(sa.Column("workspace_id", sa.String(36), nullable=True))
        batch.create_foreign_key(FOREIGN_KEY, "workspaces", ["workspace_id"], ["id"])
        batch.create_index(INDEX, ["workspace_id"])

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE feed_articles
            SET workspace_id = (
                SELECT feed_sources.workspace_id
                FROM feed_sources
                WHERE feed_sources.id = feed_articles.source_id
            )
            WHERE workspace_id IS NULL
            """
        )
    )
    unscoped = bind.execute(
        sa.text("SELECT COUNT(*) FROM feed_articles WHERE workspace_id IS NULL")
    ).scalar_one()
    if unscoped:
        logger.warning(
            "120_feed_article_workspace: %s article(s) have no workspace after the backfill "
            "and will never be served",
            unscoped,
        )


def downgrade() -> None:
    with op.batch_alter_table("feed_articles") as batch:
        batch.drop_index(INDEX)
        batch.drop_constraint(FOREIGN_KEY, type_="foreignkey")
        batch.drop_column("workspace_id")
