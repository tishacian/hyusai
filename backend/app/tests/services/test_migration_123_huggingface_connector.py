"""Exercise the actual Hub DDL against a populated predecessor SQLite schema."""

from __future__ import annotations

import importlib.util
import io
from datetime import datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.db.base import Base
from app.models.knowledge_collection import WORKER_JOB_KINDS, KnowledgeCollection


def load_migration():
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "123_huggingface_connector.py"
    )
    spec = importlib.util.spec_from_file_location("migration_123_huggingface", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HUB_TABLES = {
    "hf_platform_config",
    "hf_license_acceptances",
    "hf_license_exceptions",
    "hub_artifacts",
    "hub_artifact_grants",
    "hub_artifact_usages",
    "hub_import_reservations",
    "hub_import_requests",
}
GENERATION_COLUMNS = {
    "embedding_artifact_id",
    "reranker_artifact_id",
    "embedding_dimension",
    "embedding_params",
    "active_generation",
    "pending_generation",
}


def predecessor_schema(bind):
    metadata = sa.MetaData()
    sa.Table("workspaces", metadata, sa.Column("id", sa.String(36), primary_key=True))
    sa.Table("workspace_jobs", metadata, sa.Column("id", sa.String(36), primary_key=True))
    sa.Table(
        "knowledge_collections",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("embedding_model", sa.String(255)),
        sa.Column("vector_collection_name", sa.String(255), nullable=False),
    )
    kinds = tuple(kind for kind in WORKER_JOB_KINDS if kind != "rag_reranker_activate")
    sa.Table(
        "worker_jobs",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.CheckConstraint(
            "kind IN (" + ", ".join(repr(kind) for kind in kinds) + ")", name="ck_worker_jobs_kind"
        ),
    )
    metadata.create_all(bind)
    bind.execute(sa.text("INSERT INTO workspaces (id) VALUES ('ws')"))
    bind.execute(
        sa.text(
            "INSERT INTO knowledge_collections (id, workspace_id, slug, embedding_model, vector_collection_name) VALUES ('collection', 'ws', 'manuals', 'legacy-model', 'ws__manuals')"
        )
    )
    bind.execute(
        sa.text(
            "INSERT INTO worker_jobs (id, kind, status) VALUES ('old-job', 'document_ingest_index', 'completed')"
        )
    )


def signature_columns(table):
    return {
        column.name: (
            column.type.compile(dialect=sa.dialects.sqlite.dialect()),
            column.nullable,
            column.primary_key,
        )
        for column in table.columns
    }


def signature_foreign_keys(table):
    return {
        (
            tuple(constraint.column_keys),
            tuple(element.target_fullname for element in constraint.elements),
            constraint.ondelete,
        )
        for constraint in table.foreign_key_constraints
    }


def signature_unique(table):
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }


def test_upgrade_matches_orm_and_preserves_legacy_rows_then_downgrades(monkeypatch):
    migration = load_migration()
    assert migration.down_revision == "122_ml_families"
    engine = sa.create_engine("sqlite://")
    with engine.begin() as bind:
        predecessor_schema(bind)
        original_tables = set(sa.inspect(bind).get_table_names())
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(bind)))
        migration.upgrade()
        reflected = sa.MetaData()
        reflected.reflect(bind=bind)
        assert set(reflected.tables) == original_tables | HUB_TABLES
        for name in HUB_TABLES:
            actual, expected = reflected.tables[name], Base.metadata.tables[name]
            assert signature_columns(actual) == signature_columns(expected), name
            assert signature_foreign_keys(actual) == signature_foreign_keys(expected), name
            assert signature_unique(actual) == signature_unique(expected), name
            assert {
                (index.name, tuple(column.name for column in index.columns), bool(index.unique))
                for index in actual.indexes
            } == {
                (index.name, tuple(column.name for column in index.columns), bool(index.unique))
                for index in expected.indexes
            }, name
            assert {
                str(c.sqltext) for c in actual.constraints if isinstance(c, sa.CheckConstraint)
            } == {
                str(c.sqltext) for c in expected.constraints if isinstance(c, sa.CheckConstraint)
            }, name
        actual_columns = signature_columns(reflected.tables["knowledge_collections"])
        expected_columns = signature_columns(KnowledgeCollection.__table__)
        assert {key: actual_columns[key] for key in GENERATION_COLUMNS} == {
            key: expected_columns[key] for key in GENERATION_COLUMNS
        }
        assert bind.execute(
            sa.text(
                "SELECT embedding_model, vector_collection_name, active_generation FROM knowledge_collections"
            )
        ).one() == ("legacy-model", "ws__manuals", None)
        assert bind.execute(
            sa.text("SELECT connection, policy, limits FROM hf_platform_config WHERE id='default'")
        ).one() == ("{}", "{}", "{}")
        bind.execute(
            sa.text(
                "INSERT INTO worker_jobs (id, kind, status) VALUES ('probe', 'rag_reranker_activate', 'queued')"
            )
        )
        with pytest.raises(RuntimeError, match="reranker jobs"):
            migration.downgrade()
        bind.execute(sa.text("DELETE FROM worker_jobs WHERE id='probe'"))
        migration.downgrade()
        assert set(sa.inspect(bind).get_table_names()) == original_tables
        assert not GENERATION_COLUMNS.intersection(
            column["name"] for column in sa.inspect(bind).get_columns("knowledge_collections")
        )
        assert bind.execute(
            sa.text("SELECT embedding_model, vector_collection_name FROM knowledge_collections")
        ).one() == ("legacy-model", "ws__manuals")
        assert bind.execute(sa.text("SELECT kind, status FROM worker_jobs")).one() == (
            "document_ingest_index",
            "completed",
        )
        with pytest.raises(sa.exc.IntegrityError):
            bind.execute(
                sa.text(
                    "INSERT INTO worker_jobs (id, kind, status) VALUES ('invalid', 'rag_reranker_activate', 'queued')"
                )
            )


def test_database_rejects_negative_import_sizes_and_duplicate_grants(monkeypatch):
    migration = load_migration()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as bind:
        predecessor_schema(bind)
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(bind)))
        migration.upgrade()
        artifacts = sa.Table("hub_artifacts", sa.MetaData(), autoload_with=bind)
        defaults = {
            "id": "model",
            "identity_hash": "a" * 64,
            "hub_endpoint": "https://huggingface.co",
            "kind": "model",
            "repo_id": "test/model",
            "revision": "b" * 40,
            "requested_ref": "main",
            "format": "safetensors",
            "selection_digest": "c" * 64,
            "files_json": {},
            "selection_json": {},
            "metadata_json": {},
            "manifest_json": {},
            "total_bytes": -1,
            "status": "pending",
            "created_at": datetime.now(),
        }
        with pytest.raises(sa.exc.IntegrityError):
            bind.execute(artifacts.insert().values(**defaults))
        defaults["total_bytes"] = 0
        bind.execute(artifacts.insert().values(**defaults))
        grants = sa.Table("hub_artifact_grants", sa.MetaData(), autoload_with=bind)
        grant = {
            "workspace_id": "ws",
            "artifact_id": "model",
            "granted_by": "admin",
            "granted_at": defaults["created_at"],
            "license_digest": "d" * 64,
            "policy_version": "v1",
        }
        bind.execute(grants.insert().values(**grant))
        with pytest.raises(sa.exc.IntegrityError):
            bind.execute(grants.insert().values(**grant))


def test_postgresql_offline_upgrade_compiles_seed_and_alter_constraints(monkeypatch):
    migration = load_migration()
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    monkeypatch.setattr(migration, "op", Operations(context))
    migration.upgrade()
    sql = output.getvalue()
    assert "CREATE TABLE hub_artifacts" in sql
    assert "INSERT INTO hf_platform_config" in sql
    assert "CURRENT_TIMESTAMP" in sql
    assert "ADD CONSTRAINT fk_knowledge_collections_embedding_artifact_id" in sql
    assert "rag_reranker_activate" in sql
