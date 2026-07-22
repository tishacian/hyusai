"""Migration contract for opaque Workspace Blueprint object identities."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError


def _load_migration():
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "071_blueprint_object_keys.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace()
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_071", path)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            sys.modules.pop("alembic", None)
    return module


MIG = _load_migration()


class _SQLiteBatch:
    def __init__(self, operations, table_name: str):
        self.operations = operations
        self.table_name = table_name

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False

    def alter_column(self, column_name: str, **kwargs) -> None:
        self.operations.calls.append(
            ("alter", self.table_name, column_name, kwargs.get("nullable"))
        )

    def create_unique_constraint(self, name: str, columns: list[str]) -> None:
        self.operations.calls.append(("unique", self.table_name, name, tuple(columns)))
        column_sql = ", ".join(f'"{column}"' for column in columns)
        self.operations.bind.exec_driver_sql(
            f'CREATE UNIQUE INDEX "{name}" ON "{self.table_name}" ({column_sql})'
        )

    def drop_constraint(self, name: str, *, type_: str) -> None:
        assert type_ == "unique"
        self.operations.bind.exec_driver_sql(f'DROP INDEX "{name}"')

    def drop_column(self, column_name: str) -> None:
        self.operations.bind.exec_driver_sql(
            f'ALTER TABLE "{self.table_name}" DROP COLUMN "{column_name}"'
        )


class _SQLiteOps:
    def __init__(self, bind):
        self.bind = bind
        self.calls: list[tuple] = []

    def get_bind(self):
        return self.bind

    def add_column(self, table_name: str, column: sa.Column) -> None:
        assert column.name == MIG.KEY_COLUMN
        self.bind.exec_driver_sql(
            f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" VARCHAR(120)'
        )

    def batch_alter_table(self, table_name: str) -> _SQLiteBatch:
        return _SQLiteBatch(self, table_name)


def _legacy_engine():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    for table_name in MIG.TABLE_CONSTRAINTS:
        sa.Table(
            table_name,
            metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("workspace_id", sa.String(36), nullable=True),
            sa.Column("name", sa.String(200), nullable=False),
        )
    metadata.create_all(engine)
    return engine


def test_revision_extends_shortened_workspace_app_head() -> None:
    assert MIG.revision == "071_blueprint_object_keys"
    assert len(MIG.revision) <= 32
    assert MIG.down_revision == "070_app_entitlement_registry"


def test_upgrade_backfills_ids_and_enforces_workspace_scoped_key_uniqueness(
    monkeypatch,
) -> None:
    engine = _legacy_engine()
    with engine.begin() as bind:
        for table_name in MIG.TABLE_CONSTRAINTS:
            bind.execute(
                sa.text(
                    f'INSERT INTO "{table_name}" (id, workspace_id, name) '
                    "VALUES (:id, :workspace_id, :name)"
                ),
                [
                    {"id": f"{table_name}-1", "workspace_id": "ws-a", "name": "Same"},
                    {"id": f"{table_name}-2", "workspace_id": "ws-a", "name": "Same"},
                ],
            )
        operations = _SQLiteOps(bind)
        monkeypatch.setattr(MIG, "op", operations)

        MIG.upgrade()

        for table_name, constraint_name in MIG.TABLE_CONSTRAINTS.items():
            rows = bind.execute(
                sa.text(
                    f'SELECT id, blueprint_key FROM "{table_name}" ORDER BY id'
                )
            ).all()
            assert rows == [
                (f"{table_name}-1", f"{table_name}-1"),
                (f"{table_name}-2", f"{table_name}-2"),
            ]
            assert (
                "alter",
                table_name,
                "blueprint_key",
                False,
            ) in operations.calls
            assert (
                "unique",
                table_name,
                constraint_name,
                ("workspace_id", "blueprint_key"),
            ) in operations.calls

            savepoint = bind.begin_nested()
            try:
                with pytest.raises(IntegrityError):
                    bind.execute(
                        sa.text(
                            f'INSERT INTO "{table_name}" '
                            "(id, workspace_id, name, blueprint_key) "
                            "VALUES (:id, :workspace_id, :name, :blueprint_key)"
                        ),
                        {
                            "id": f"{table_name}-duplicate",
                            "workspace_id": "ws-a",
                            "name": "Different",
                            "blueprint_key": f"{table_name}-1",
                        },
                    )
            finally:
                savepoint.rollback()

            bind.execute(
                sa.text(
                    f'INSERT INTO "{table_name}" '
                    "(id, workspace_id, name, blueprint_key) "
                    "VALUES (:id, :workspace_id, :name, :blueprint_key)"
                ),
                {
                    "id": f"{table_name}-other-workspace",
                    "workspace_id": "ws-b",
                    "name": "Same",
                    "blueprint_key": f"{table_name}-1",
                },
            )
