"""Migration 120 stamps each RSS article with its feed source's workspace."""
from __future__ import annotations

import importlib.util
import logging
import sys
import types
from pathlib import Path

import sqlalchemy as sa

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext


def _load():
    path = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "120_feed_article_workspace.py"
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace()
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_120", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            sys.modules.pop("alembic", None)
    return module


MIG = _load()


def _schema(bind):
    metadata = sa.MetaData()
    sa.Table("workspaces", metadata, sa.Column("id", sa.String(36), primary_key=True))
    sa.Table(
        "feed_sources",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=True),
    )
    sa.Table(
        "feed_articles",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("url", sa.String(2000)),
    )
    metadata.create_all(bind)


def test_revision_chains_onto_the_claim_trials_head():
    assert MIG.revision == "120_feed_article_workspace"
    assert MIG.down_revision == "119_claim_trials"


def test_upgrade_backfills_from_the_feed_source_and_downgrade_drops_the_column(monkeypatch, caplog):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as bind:
        _schema(bind)
        bind.execute(sa.text("INSERT INTO workspaces (id) VALUES ('ws-a'), ('ws-b')"))
        bind.execute(
            sa.text("INSERT INTO feed_sources (id, workspace_id) VALUES ('f-a', 'ws-a'), ('f-b', 'ws-b'), ('f-null', NULL)")
        )
        bind.execute(
            sa.text(
                "INSERT INTO feed_articles (id, source_id, url) VALUES "
                "('a1', 'f-a', 'https://x'), ('b1', 'f-b', 'https://y'), "
                "('n1', 'f-null', 'https://z'), ('o1', 'f-gone', 'https://w')"
            )
        )
        monkeypatch.setattr(MIG, "op", Operations(MigrationContext.configure(bind)))

        with caplog.at_level(logging.WARNING, logger="alembic.runtime.migration"):
            MIG.upgrade()

        stamped = dict(bind.execute(sa.text("SELECT id, workspace_id FROM feed_articles")).all())
        assert stamped == {"a1": "ws-a", "b1": "ws-b", "n1": None, "o1": None}
        assert "2 article(s) have no workspace" in caplog.text
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes("feed_articles")}
        assert MIG.INDEX in indexes

        MIG.downgrade()

        columns = {column["name"] for column in sa.inspect(bind).get_columns("feed_articles")}
        assert columns == {"id", "source_id", "url"}
        assert bind.execute(sa.text("SELECT COUNT(*) FROM feed_articles")).scalar_one() == 4
