"""Contract for the honest ValueSimulation approval pin migration 075."""

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
        / "075_simulation_approval_pin.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace()
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_075", path)
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


class _Operations:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []
        self.bind = object()

    def get_bind(self) -> object:
        return self.bind

    def add_column(self, table: str, column: sa.Column) -> None:
        self.calls.append(("add", table, column))

    def drop_column(self, table: str, column: str) -> None:
        self.calls.append(("drop", table, column))


def test_revision_extends_relational_integrity_head() -> None:
    assert MIG.revision == "075_simulation_approval_pin"
    assert len(MIG.revision) <= 32
    assert MIG.down_revision == "074_relational_integrity"


def test_upgrade_adds_nullable_pin_without_inventing_legacy_evidence(
    monkeypatch,
) -> None:
    operations = _Operations()
    monkeypatch.setattr(MIG, "op", operations)

    MIG.upgrade()

    columns = {
        call[2].name: call[2]
        for call in operations.calls
        if call[0] == "add" and call[1] == "value_scenarios"
    }
    assert set(columns) == {
        "approved_simulation_content_sha256",
        "approved_simulation_snapshot",
    }
    assert isinstance(columns["approved_simulation_content_sha256"].type, sa.String)
    assert columns["approved_simulation_content_sha256"].type.length == 64
    assert isinstance(columns["approved_simulation_snapshot"].type, sa.JSON)
    assert all(column.nullable for column in columns.values())
    assert all(call[0] == "add" for call in operations.calls)


def test_downgrade_removes_only_the_approval_pin(monkeypatch) -> None:
    operations = _Operations()
    monkeypatch.setattr(MIG, "op", operations)
    monkeypatch.setattr(MIG, "_active_pin_count", lambda _bind: 0)

    MIG.downgrade()

    assert operations.calls == [
        ("drop", "value_scenarios", "approved_simulation_snapshot"),
        ("drop", "value_scenarios", "approved_simulation_content_sha256"),
    ]


def test_downgrade_refuses_to_erase_active_approval_authority(monkeypatch) -> None:
    operations = _Operations()
    monkeypatch.setattr(MIG, "op", operations)
    monkeypatch.setattr(MIG, "_active_pin_count", lambda _bind: 2)

    with pytest.raises(RuntimeError, match="retain approval authority"):
        MIG.downgrade()

    assert operations.calls == []


def test_active_pin_preflight_uses_real_rows_and_fails_closed_on_schema_drift() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE value_scenarios ("
                "id TEXT PRIMARY KEY, "
                "approved_simulation_content_sha256 TEXT, "
                "approved_simulation_snapshot JSON)"
            )
        )
        assert MIG._active_pin_count(connection) == 0
        connection.execute(
            sa.text(
                "INSERT INTO value_scenarios "
                "(id, approved_simulation_content_sha256, approved_simulation_snapshot) "
                "VALUES ('scenario-1', :digest, NULL)"
            ),
            {"digest": "a" * 64},
        )
        assert MIG._active_pin_count(connection) == 1

    drifted = sa.create_engine("sqlite:///:memory:")
    with drifted.begin() as connection:
        connection.execute(sa.text("CREATE TABLE value_scenarios (id TEXT PRIMARY KEY)"))
        with pytest.raises(RuntimeError, match="missing columns"):
            MIG._active_pin_count(connection)
