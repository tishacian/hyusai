"""Round-trip contract for migration 065's additive configuration evidence."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import sqlalchemy as sa


def _load_migration():
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "065_system_version_config.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace()
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_065", path)
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
    """Minimal adapter that applies this additive migration to real SQLite."""

    def __init__(self, bind):
        self.bind = bind

    def add_column(self, table_name, column):
        assert table_name == "system_versions"
        assert column.name == "configuration_snapshot"
        assert column.nullable is True
        type_sql = column.type.compile(dialect=self.bind.dialect)
        self.bind.execute(
            sa.text(
                f'ALTER TABLE "{table_name}" '
                f'ADD COLUMN "{column.name}" {type_sql}'
            )
        )

    def drop_column(self, table_name, column_name):
        assert table_name == "system_versions"
        assert column_name == "configuration_snapshot"
        self.bind.execute(
            sa.text(f'ALTER TABLE "{table_name}" DROP COLUMN "{column_name}"')
        )


def _column_names(bind) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns("system_versions")}


def test_revision_extends_the_p4_head():
    assert MIG.revision == "065_system_version_config"
    # Re-parented during the Release B landing: production lineage already
    # carries ``065_nawa_itsd``, so this revision follows it.
    assert MIG.down_revision == "065_nawa_itsd"


def test_upgrade_and_downgrade_are_additive_and_preserve_historical_rows(monkeypatch):
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    versions = sa.Table(
        "system_versions",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("flow_definition", sa.JSON(), nullable=False),
    )
    metadata.create_all(engine)

    with engine.begin() as bind:
        bind.execute(
            versions.insert().values(
                id="historical-version",
                flow_definition={"schema_version": 3, "nodes": [], "edges": []},
            )
        )
        monkeypatch.setattr(MIG, "op", _SQLiteOps(bind))

        MIG.upgrade()

        assert "configuration_snapshot" in _column_names(bind)
        upgraded_versions = sa.Table(
            "system_versions",
            sa.MetaData(),
            autoload_with=bind,
        )
        historical = bind.execute(
            sa.select(upgraded_versions).where(
                upgraded_versions.c.id == "historical-version"
            )
        ).mappings().one()
        assert historical["configuration_snapshot"] is None

        MIG.downgrade()

        assert "configuration_snapshot" not in _column_names(bind)
        remaining = bind.execute(
            sa.text("SELECT id FROM system_versions WHERE id = :id"),
            {"id": "historical-version"},
        ).scalar_one()
        assert remaining == "historical-version"
