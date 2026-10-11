"""Schema contracts for additive Workspace App lifecycle migration 069."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest
import sqlalchemy as sa


def _load_migration():
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "069_workspace_app_lifecycle.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace()
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_069", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            sys.modules.pop("alembic", None)
    return module


MIG = _load_migration()


class _SQLiteOps:
    def __init__(self, connection):
        self.connection = connection
        self.metadata = sa.MetaData()
        self.metadata.reflect(connection)

    def get_bind(self):
        return self.connection

    def create_table(self, name, *elements):
        table = sa.Table(name, self.metadata, *elements)
        table.create(self.connection)
        return table

    def create_index(self, name, table_name, columns, *, unique):
        table = self.metadata.tables[table_name]
        sa.Index(name, *(table.c[column] for column in columns), unique=unique).create(
            self.connection
        )

    def drop_table(self, name):
        table = sa.Table(name, sa.MetaData(), autoload_with=self.connection)
        table.drop(self.connection)


def _legacy_schema(engine):
    metadata = sa.MetaData()
    workspaces = sa.Table(
        "workspaces",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("settings", sa.JSON(), nullable=False),
    )
    metadata.create_all(engine)
    return workspaces


def test_revision_follows_value_loop_core():
    assert MIG.revision == "069_workspace_app_lifecycle"
    assert MIG.down_revision == "068_value_loop_core"


def test_upgrade_is_additive_and_enforces_tenant_and_idempotency_keys(monkeypatch):
    engine = sa.create_engine("sqlite://")
    workspaces = _legacy_schema(engine)
    with engine.begin() as connection:
        connection.execute(
            workspaces.insert().values(
                id="legacy-workspace",
                slug="legacy",
                settings={"apps": {"enabled": ["legacy-card"]}},
            )
        )
        monkeypatch.setattr(MIG, "op", _SQLiteOps(connection))
        MIG.upgrade()

        inspector = sa.inspect(connection)
        assert {
            "workspace_app_installations",
            "workspace_app_operations",
        }.issubset(inspector.get_table_names())
        legacy = connection.execute(
            sa.select(workspaces.c.slug, workspaces.c.settings)
        ).mappings().one()
        assert dict(legacy) == {
            "slug": "legacy",
            "settings": {"apps": {"enabled": ["legacy-card"]}},
        }
        install_uniques = inspector.get_unique_constraints("workspace_app_installations")
        assert any(
            item["name"] == "uq_workspace_app_installations_workspace_app"
            and item["column_names"] == ["workspace_id", "app_id"]
            for item in install_uniques
        )
        assert any(
            item["name"] == "uq_workspace_app_installations_id_workspace"
            and item["column_names"] == ["id", "workspace_id"]
            for item in install_uniques
        )
        operation_uniques = inspector.get_unique_constraints("workspace_app_operations")
        assert any(
            item["name"] == "uq_workspace_app_operations_workspace_key"
            and item["column_names"] == ["workspace_id", "idempotency_key"]
            for item in operation_uniques
        )
        operation_fks = inspector.get_foreign_keys("workspace_app_operations")
        assert any(
            item["name"] == "fk_workspace_app_operations_installation_tenant"
            and item["constrained_columns"] == ["installation_id", "workspace_id"]
            and item["referred_columns"] == ["id", "workspace_id"]
            for item in operation_fks
        )


def test_empty_upgrade_and_downgrade_round_trip(monkeypatch):
    engine = sa.create_engine("sqlite://")
    _legacy_schema(engine)
    with engine.begin() as connection:
        monkeypatch.setattr(MIG, "op", _SQLiteOps(connection))
        MIG.upgrade()
        MIG.downgrade()
        assert not any(
            table.startswith("workspace_app_")
            for table in sa.inspect(connection).get_table_names()
        )
        assert "workspaces" in sa.inspect(connection).get_table_names()


def test_downgrade_refuses_to_destroy_lifecycle_state(monkeypatch):
    engine = sa.create_engine("sqlite://")
    workspaces = _legacy_schema(engine)
    with engine.begin() as connection:
        monkeypatch.setattr(MIG, "op", _SQLiteOps(connection))
        MIG.upgrade()
        connection.execute(
            workspaces.insert().values(
                id="workspace-with-app",
                slug="with-app",
                settings={},
            )
        )
        installations = sa.Table(
            "workspace_app_installations",
            sa.MetaData(),
            autoload_with=connection,
        )
        connection.execute(
            installations.insert().values(
                id="installation-1",
                workspace_id="workspace-with-app",
                app_id="mission-room.extension",
                version="1.0.0",
                manifest_digest="a" * 64,
                state="installed",
                configuration={},
                revision=1,
                installed_at=sa.func.now(),
                updated_at=sa.func.now(),
                updated_by="migration-test",
            )
        )
        with pytest.raises(RuntimeError, match="Refusing to downgrade"):
            MIG.downgrade()
        assert "workspace_app_installations" in sa.inspect(connection).get_table_names()
