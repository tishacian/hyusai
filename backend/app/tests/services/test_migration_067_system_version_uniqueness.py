"""Migration contract for serialized, unique SystemVersion allocation."""
from __future__ import annotations

import importlib.util
import json
import logging
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
        / "067_system_version_uniqueness.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace()
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_067", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            sys.modules.pop("alembic", None)
    return module


MIG = _load_migration()


class _SQLiteBatch:
    def __init__(self, operations):
        self.operations = operations

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def create_unique_constraint(self, name, columns):
        assert name == MIG.CONSTRAINT_NAME
        assert columns == ["system_id", "version_number"]
        self.operations.calls.append(("create", name, tuple(columns)))
        self.operations.bind.execute(
            sa.text(
                f'CREATE UNIQUE INDEX "{name}" '
                'ON "system_versions" ("system_id", "version_number")'
            )
        )

    def drop_constraint(self, name, *, type_):
        assert name == MIG.CONSTRAINT_NAME
        assert type_ == "unique"
        self.operations.calls.append(("drop", name))
        self.operations.bind.execute(sa.text(f'DROP INDEX "{name}"'))


class _SQLiteOps:
    def __init__(self, bind):
        self.bind = bind
        self.calls: list[tuple] = []

    def get_bind(self):
        return self.bind

    def batch_alter_table(self, table_name):
        assert table_name == "system_versions"
        return _SQLiteBatch(self)


def _engine_with_versions(rows: list[dict] | None = None):
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    versions = sa.Table(
        "system_versions",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("system_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
    )
    metadata.create_all(engine)
    if rows:
        with engine.begin() as bind:
            bind.execute(versions.insert(), rows)
    return engine, versions


def test_revision_extends_skill_invocation_snapshot_head():
    assert MIG.revision == "067_system_version_uniqueness"
    assert MIG.down_revision == "066_skill_invocation_snapshot"


def test_upgrade_preserves_rows_and_enforces_uniqueness_then_downgrades(monkeypatch):
    engine, versions = _engine_with_versions(
        [
            {"id": "v1", "system_id": "system-a", "version_number": 1},
            {"id": "v2", "system_id": "system-a", "version_number": 2},
            {"id": "other-v1", "system_id": "system-b", "version_number": 1},
        ]
    )

    with engine.begin() as bind:
        operations = _SQLiteOps(bind)
        monkeypatch.setattr(MIG, "op", operations)
        MIG.upgrade()
        assert operations.calls == [
            (
                "create",
                "uq_system_versions_system_version_number",
                ("system_id", "version_number"),
            )
        ]
        assert bind.execute(sa.select(sa.func.count()).select_from(versions)).scalar_one() == 3

    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as bind:
            bind.execute(
                versions.insert().values(
                    id="duplicate",
                    system_id="system-a",
                    version_number=2,
                )
            )

    with engine.begin() as bind:
        operations = _SQLiteOps(bind)
        monkeypatch.setattr(MIG, "op", operations)
        MIG.downgrade()
        assert operations.calls == [
            ("drop", "uq_system_versions_system_version_number")
        ]

    with engine.begin() as bind:
        bind.execute(
            versions.insert().values(
                id="duplicate-after-downgrade",
                system_id="system-a",
                version_number=2,
            )
        )


def test_upgrade_fails_closed_with_structured_duplicate_audit(monkeypatch, caplog):
    engine, _versions = _engine_with_versions(
        [
            {"id": "a1", "system_id": "system-a", "version_number": 1},
            {"id": "a1-copy", "system_id": "system-a", "version_number": 1},
            {"id": "b4", "system_id": "system-b", "version_number": 4},
            {"id": "b4-copy", "system_id": "system-b", "version_number": 4},
            {"id": "b4-copy-2", "system_id": "system-b", "version_number": 4},
        ]
    )

    with engine.begin() as bind:
        operations = _SQLiteOps(bind)
        monkeypatch.setattr(MIG, "op", operations)
        with caplog.at_level(logging.ERROR, logger="alembic.runtime.migration"):
            with pytest.raises(
                RuntimeError,
                match="SystemVersion uniqueness preflight failed",
            ) as caught:
                MIG.upgrade()

        assert operations.calls == []
        payload = json.loads(str(caught.value).split(": ", 1)[1])
        assert payload == {
            "constraint": "uq_system_versions_system_version_number",
            "duplicate_group_count": 2,
            "duplicate_row_count": 5,
            "event": "system_versions.uniqueness_preflight_failed",
            "groups": [
                {
                    "duplicate_count": 2,
                    "system_id": "system-a",
                    "version_number": 1,
                },
                {
                    "duplicate_count": 3,
                    "system_id": "system-b",
                    "version_number": 4,
                },
            ],
            "resolution": "resolve collisions explicitly, then rerun the migration",
        }
        assert json.dumps(payload, sort_keys=True, separators=(",", ":")) in caplog.text
