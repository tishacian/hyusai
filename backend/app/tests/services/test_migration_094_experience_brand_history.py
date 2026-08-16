"""Migration 094 preserves the current draft and adds lifecycle receipts."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from alembic.migration import MigrationContext
from alembic.operations import Operations


def _load_migration():
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "094_experience_brand_history.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace()
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_094", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            sys.modules.pop("alembic", None)
    return module


MIG = _load_migration()


def test_upgrade_backfills_history_and_enforces_release_request_uniqueness() -> None:
    assert MIG.revision == "094_experience_brand_history"
    assert MIG.down_revision == "093_experience_run_idempotency"
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    workspaces = sa.Table(
        "workspaces",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
    )
    experiences = sa.Table(
        "experiences",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
    )
    drafts = sa.Table(
        "experience_draft_revisions",
        metadata,
        sa.Column("experience_id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("pages", sa.JSON(), nullable=False),
        sa.Column("binding_keys", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("updated_by", sa.String(255)),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    releases = sa.Table(
        "experience_releases",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("experience_id", sa.String(36), nullable=False),
    )
    sa.Table(
        "experience_deployments",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
    )
    metadata.create_all(engine)
    updated_at = datetime(2026, 8, 14, 10, 0, 0)

    with engine.begin() as connection:
        connection.execute(workspaces.insert(), {"id": "workspace-1"})
        connection.execute(
            experiences.insert(), {"id": "experience-1", "workspace_id": "workspace-1"}
        )
        connection.execute(
            drafts.insert(),
            {
                "experience_id": "experience-1",
                "workspace_id": "workspace-1",
                "revision": 7,
                "pages": {"pages": [{"id": "home"}]},
                "binding_keys": ["expenses.submit"],
                "content_sha256": "a" * 64,
                "updated_by": "author@example.test",
                "updated_at": updated_at,
            },
        )
        MIG.op = Operations(MigrationContext.configure(connection))
        MIG.upgrade()

        history = sa.Table(
            "experience_draft_history", sa.MetaData(), autoload_with=connection
        )
        backfill = connection.execute(sa.select(history)).one()._mapping
        assert backfill["revision"] == 7
        assert backfill["pages"] == {"pages": [{"id": "home"}]}
        assert backfill["binding_keys"] == ["expenses.submit"]
        assert backfill["saved_by"] == "author@example.test"
        assert {
            "last_mutation_sha256",
            "previous_audience",
        } <= {
            item["name"]
            for item in sa.inspect(connection).get_columns("experience_deployments")
        }

        upgraded_releases = sa.Table(
            "experience_releases", sa.MetaData(), autoload_with=connection
        )
        connection.execute(
            upgraded_releases.insert(),
            {
                "id": "release-1",
                "experience_id": "experience-1",
                "creation_request_sha256": "b" * 64,
            },
        )
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                upgraded_releases.insert(),
                {
                    "id": "release-2",
                    "experience_id": "experience-1",
                    "creation_request_sha256": "b" * 64,
                },
            )

        MIG.downgrade()
        assert "experience_draft_history" not in sa.inspect(connection).get_table_names()
        assert "description" not in {
            item["name"] for item in sa.inspect(connection).get_columns("experiences")
        }
