"""Schema contract for the additive Lot-8 value-loop migration."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest
import sqlalchemy as sa


def _load_migration():
    path = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "068_value_loop_core.py"
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace()
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_068", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            sys.modules.pop("alembic", None)
    return module


MIG = _load_migration()


def _legacy_schema(engine) -> None:
    metadata = sa.MetaData()
    sa.Table(
        "workspaces",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
    )
    sa.Table(
        "control_policies",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
    )
    sa.Table(
        "systems",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
    )
    sa.Table(
        "runs",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
    )
    sa.Table(
        "decisions",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
    )
    metadata.create_all(engine)


class _SQLiteBatch:
    def __init__(self, operations, table_name):
        self.operations = operations
        self.table_name = table_name

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def add_column(self, column):
        assert self.table_name == "decisions"
        self.operations.connection.execute(
            sa.text(f'ALTER TABLE "decisions" ADD COLUMN "{column.name}" VARCHAR(36)')
        )
        self.operations.calls.append(("add_column", column.name))

    def create_foreign_key(
        self,
        name,
        referred_table,
        local_columns,
        remote_columns,
        **kwargs,
    ):
        self.operations.calls.append(
            (
                "create_fk",
                name,
                referred_table,
                tuple(local_columns),
                tuple(remote_columns),
                kwargs,
            )
        )

    def create_unique_constraint(self, name, columns):
        quoted = ", ".join(f'"{column}"' for column in columns)
        self.operations.connection.execute(
            sa.text(f'CREATE UNIQUE INDEX "{name}" ON "decisions" ({quoted})')
        )
        self.operations.calls.append(("create_unique", name, tuple(columns)))

    def create_index(self, name, columns, *, unique):
        quoted = ", ".join(f'"{column}"' for column in columns)
        unique_sql = "UNIQUE " if unique else ""
        self.operations.connection.execute(
            sa.text(f'CREATE {unique_sql}INDEX "{name}" ON "decisions" ({quoted})')
        )
        self.operations.calls.append(("create_index", name, tuple(columns), unique))

    def drop_index(self, name):
        self.operations.connection.execute(sa.text(f'DROP INDEX "{name}"'))
        self.operations.calls.append(("drop_index", name))

    def drop_constraint(self, name, *, type_):
        self.operations.calls.append(("drop_constraint", name, type_))
        if type_ == "unique":
            self.operations.connection.execute(sa.text(f'DROP INDEX "{name}"'))

    def drop_column(self, name):
        self.operations.connection.execute(sa.text(f'ALTER TABLE "decisions" DROP COLUMN "{name}"'))
        self.operations.calls.append(("drop_column", name))


class _SQLiteOps:
    def __init__(self, connection):
        self.connection = connection
        self.metadata = sa.MetaData()
        self.metadata.reflect(connection)
        self.calls = []

    def get_bind(self):
        return self.connection

    def create_table(self, name, *elements):
        table = sa.Table(name, self.metadata, *elements)
        table.create(self.connection)
        self.calls.append(("create_table", name))
        return table

    def create_index(self, name, table_name, columns, *, unique):
        table = self.metadata.tables[table_name]
        sa.Index(name, *(table.c[column] for column in columns), unique=unique).create(
            self.connection
        )
        self.calls.append(("create_index", name, table_name, tuple(columns), unique))

    def batch_alter_table(self, table_name):
        return _SQLiteBatch(self, table_name)

    def drop_table(self, name):
        table = sa.Table(name, sa.MetaData(), autoload_with=self.connection)
        table.drop(self.connection)
        self.calls.append(("drop_table", name))


def test_revision_extends_system_version_uniqueness_head():
    assert MIG.revision == "068_value_loop_core"
    assert MIG.down_revision == "067_system_version_uniqueness"


def test_upgrade_is_additive_and_preserves_legacy_decisions(monkeypatch):
    engine = sa.create_engine("sqlite://")
    _legacy_schema(engine)
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO decisions (id, workspace_id, title) "
                "VALUES ('legacy-decision', NULL, 'Legacy')"
            )
        )
        operations = _SQLiteOps(connection)
        monkeypatch.setattr(MIG, "op", operations)
        MIG.upgrade()

        inspector = sa.inspect(connection)
        assert {
            "value_loop_operations",
            "value_scenarios",
            "value_simulations",
            "value_action_executions",
            "value_measurements",
        }.issubset(set(inspector.get_table_names()))
        decision_columns = {column["name"] for column in inspector.get_columns("decisions")}
        assert "scenario_id" in decision_columns
        legacy = (
            connection.execute(
                sa.text(
                    "SELECT id, title, scenario_id FROM decisions " "WHERE id = 'legacy-decision'"
                )
            )
            .mappings()
            .one()
        )
        assert dict(legacy) == {
            "id": "legacy-decision",
            "title": "Legacy",
            "scenario_id": None,
        }

        operation_uniques = inspector.get_unique_constraints("value_loop_operations")
        assert any(
            item["name"] == "uq_value_loop_operations_workspace_key"
            and item["column_names"] == ["workspace_id", "idempotency_key"]
            for item in operation_uniques
        )
        decision_uniques = inspector.get_indexes("decisions")
        assert any(
            item["name"] == "uq_decisions_scenario_id"
            and item["unique"]
            and item["column_names"] == ["scenario_id"]
            for item in decision_uniques
        )
        assert any(
            call[:5]
            == (
                "create_fk",
                "fk_decisions_scenario_id_value_scenarios",
                "value_scenarios",
                ("scenario_id",),
                ("id",),
            )
            and call[5] == {"ondelete": "SET NULL"}
            for call in operations.calls
        )


def test_upgrade_and_downgrade_round_trip(monkeypatch):
    engine = sa.create_engine("sqlite://")
    _legacy_schema(engine)
    with engine.begin() as connection:
        monkeypatch.setattr(MIG, "op", _SQLiteOps(connection))
        MIG.upgrade()
        MIG.downgrade()

        inspector = sa.inspect(connection)
        assert not any(table.startswith("value_") for table in inspector.get_table_names())
        assert "scenario_id" not in {
            column["name"] for column in inspector.get_columns("decisions")
        }


def test_downgrade_refuses_to_erase_nonempty_value_ledger_before_any_ddl(
    monkeypatch,
):
    engine = sa.create_engine("sqlite://")
    _legacy_schema(engine)
    with engine.begin() as connection:
        operations = _SQLiteOps(connection)
        monkeypatch.setattr(MIG, "op", operations)
        MIG.upgrade()
        connection.execute(
            sa.text("INSERT INTO workspaces (id) VALUES ('workspace-1')")
        )
        connection.execute(
            sa.text(
                "INSERT INTO value_loop_operations "
                "(id, workspace_id, idempotency_key, request_sha256, operation, created_at) "
                "VALUES ('operation-1', 'workspace-1', 'key-1', :digest, "
                "'scenario.create', CURRENT_TIMESTAMP)"
            ),
            {"digest": "a" * 64},
        )

        with pytest.raises(RuntimeError, match="refusing destructive downgrade"):
            MIG.downgrade()

        inspector = sa.inspect(connection)
        assert set(MIG.VALUE_LOOP_TABLES).issubset(inspector.get_table_names())
        assert "scenario_id" in {
            column["name"] for column in inspector.get_columns("decisions")
        }
        assert not any(call[0].startswith("drop") for call in operations.calls)
