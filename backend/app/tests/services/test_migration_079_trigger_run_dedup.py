"""Migration 079 preserves history while electing one atomic claimant."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import sqlalchemy as sa


def _load_migration():
    path = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "079_trigger_run_dedup.py"
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace()
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_079", path)
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


def _runs(connection):
    metadata = sa.MetaData()
    table = sa.Table(
        "runs",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("system_id", sa.String(36)),
        sa.Column("trigger", sa.String(40)),
        sa.Column("input_ref", sa.JSON()),
        sa.Column("trigger_dedup_key", sa.String(255)),
    )
    metadata.create_all(connection)
    return table


def _input(key: str) -> dict:
    return {"_event_trigger": {"dedup_key": key, "simulated": False}}


def test_revision_extends_current_head() -> None:
    assert MIG.revision == "079_trigger_run_dedup"
    assert MIG.down_revision == "078_andritz_decision_contract"
    assert len(MIG.revision) <= 32


def test_backfill_elects_one_claimant_and_preserves_duplicate_rows() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        runs = _runs(connection)
        connection.execute(
            runs.insert(),
            [
                {
                    "id": "b-duplicate",
                    "system_id": "system-a",
                    "trigger": "webhook",
                    "input_ref": _input("same"),
                },
                {
                    "id": "a-canonical",
                    "system_id": "system-a",
                    "trigger": "webhook",
                    "input_ref": _input("same"),
                },
                {
                    "id": "c-unique",
                    "system_id": "system-a",
                    "trigger": "webhook",
                    "input_ref": _input("other"),
                },
                {
                    "id": "d-manual",
                    "system_id": "system-a",
                    "trigger": "manual",
                    "input_ref": _input("manual"),
                },
                {
                    "id": "e-other-system",
                    "system_id": "system-b",
                    "trigger": "webhook",
                    "input_ref": _input("same"),
                },
            ],
        )

        MIG._backfill(connection)

        rows = {row["id"]: row for row in connection.execute(sa.select(runs)).mappings()}
        assert rows["a-canonical"]["trigger_dedup_key"] == "same"
        assert rows["b-duplicate"]["trigger_dedup_key"] is None
        assert rows["c-unique"]["trigger_dedup_key"] == "other"
        assert rows["d-manual"]["trigger_dedup_key"] is None
        assert rows["e-other-system"]["trigger_dedup_key"] == "same"
        assert len(rows) == 5
