"""Schema contract for manifest-defined Workspace App entitlement keys."""

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
        / "070_workspace_app_entitlement_registry.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace()
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_070", path)
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


def _legacy_table(bind) -> sa.Table:
    metadata = sa.MetaData()
    table = sa.Table(
        MIG.TABLE,
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_member_id", sa.Integer(), nullable=False),
        sa.Column("app_key", sa.String(80), nullable=False),
        sa.CheckConstraint(MIG._enum_check(), name=MIG.CONSTRAINT),
        sa.UniqueConstraint(
            "workspace_member_id",
            "app_key",
            name="uq_workspace_member_app_entitlement",
        ),
    )
    metadata.create_all(bind)
    return table


class _SQLiteBatch:
    def __init__(self, operations, table_name: str):
        self.operations = operations
        self.table_name = table_name
        self.created_checks: list[tuple[str, str]] = []
        self.dropped_checks: set[str] = set()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _exc, _traceback):
        if exc_type is None:
            self._recreate_table()
        return False

    def create_check_constraint(self, name: str, condition: str) -> None:
        self.created_checks.append((name, condition))

    def drop_constraint(self, name: str, *, type_: str) -> None:
        assert type_ == "check"
        self.dropped_checks.add(name)

    def _recreate_table(self) -> None:
        bind = self.operations.bind
        inspector = sa.inspect(bind)
        old = sa.Table(self.table_name, sa.MetaData(), autoload_with=bind)
        checks = [
            (item["name"], item["sqltext"])
            for item in inspector.get_check_constraints(self.table_name)
            if item["name"] not in self.dropped_checks
        ]
        checks.extend(self.created_checks)
        uniques = inspector.get_unique_constraints(self.table_name)
        metadata = sa.MetaData()
        temporary = sa.Table(
            f"_alembic_tmp_{self.table_name}",
            metadata,
            *[
                sa.Column(
                    column.name,
                    column.type,
                    primary_key=column.primary_key,
                    autoincrement=column.autoincrement,
                    nullable=column.nullable,
                )
                for column in old.columns
            ],
            *[
                sa.UniqueConstraint(*item["column_names"], name=item["name"])
                for item in uniques
                if item["column_names"]
            ],
            *[
                sa.CheckConstraint(condition, name=name)
                for name, condition in checks
            ],
        )
        temporary.create(bind)
        columns = [column.name for column in old.columns]
        bind.execute(
            temporary.insert().from_select(
                columns,
                sa.select(*(old.c[name] for name in columns)),
            )
        )
        old.drop(bind)
        bind.exec_driver_sql(
            f'ALTER TABLE "{temporary.name}" RENAME TO "{self.table_name}"'
        )


class _SQLiteOps:
    def __init__(self, bind):
        self.bind = bind

    def get_bind(self):
        return self.bind

    def batch_alter_table(self, table_name: str) -> _SQLiteBatch:
        return _SQLiteBatch(self, table_name)


def test_revision_extends_workspace_app_lifecycle_head() -> None:
    assert MIG.revision == "070_app_entitlement_registry"
    assert len(MIG.revision) <= 32
    assert MIG.down_revision == "069_workspace_app_lifecycle"


def test_upgrade_preserves_legacy_grants_and_accepts_canonical_manifest_keys(
    monkeypatch,
) -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as bind:
        table = _legacy_table(bind)
        bind.execute(
            table.insert().values(workspace_member_id=1, app_key="chat")
        )
        monkeypatch.setattr(MIG, "op", _SQLiteOps(bind))

        MIG.upgrade()

        assert bind.execute(sa.select(table.c.app_key)).scalars().all() == ["chat"]
        bind.execute(
            table.insert().values(
                workspace_member_id=1,
                app_key="future-surface.v2",
            )
        )
        savepoint = bind.begin_nested()
        try:
            with pytest.raises(IntegrityError):
                bind.execute(
                    table.insert().values(
                        workspace_member_id=2,
                        app_key="Future Surface",
                    )
                )
        finally:
            savepoint.rollback()


def test_downgrade_refuses_manifest_defined_grants_then_restores_legacy_enum(
    monkeypatch,
) -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as bind:
        table = _legacy_table(bind)
        monkeypatch.setattr(MIG, "op", _SQLiteOps(bind))
        MIG.upgrade()
        bind.execute(
            table.insert(),
            [
                {"workspace_member_id": 1, "app_key": "chat"},
                {"workspace_member_id": 1, "app_key": "future-surface"},
            ],
        )

        with pytest.raises(RuntimeError, match="manifest-defined grants exist"):
            MIG.downgrade()

        bind.execute(table.delete().where(table.c.app_key == "future-surface"))
        MIG.downgrade()

        savepoint = bind.begin_nested()
        try:
            with pytest.raises(IntegrityError):
                bind.execute(
                    table.insert().values(
                        workspace_member_id=2,
                        app_key="future-surface",
                    )
                )
        finally:
            savepoint.rollback()
