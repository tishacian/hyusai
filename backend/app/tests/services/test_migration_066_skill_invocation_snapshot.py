"""Round-trip contract for migration 066's additive invocation evidence."""
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
        / "066_skill_invocation_snapshot.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace()
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_066", path)
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
    def __init__(self, bind):
        self.bind = bind

    def add_column(self, table_name, column):
        assert table_name == "skill_invocations"
        assert column.name in {"execution_snapshot", "cost_measured"}
        assert column.nullable is True
        type_sql = column.type.compile(dialect=self.bind.dialect)
        self.bind.execute(
            sa.text(
                f'ALTER TABLE "{table_name}" '
                f'ADD COLUMN "{column.name}" {type_sql}'
            )
        )

    def drop_column(self, table_name, column_name):
        assert table_name == "skill_invocations"
        assert column_name in {"execution_snapshot", "cost_measured"}
        self.bind.execute(
            sa.text(f'ALTER TABLE "{table_name}" DROP COLUMN "{column_name}"')
        )


def _column_names(bind) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(bind).get_columns("skill_invocations")
    }


def test_revision_extends_configuration_snapshot_head():
    assert MIG.revision == "066_skill_invocation_snapshot"
    assert MIG.down_revision == "065_system_version_config"


def test_upgrade_and_downgrade_preserve_historical_unknowns(monkeypatch):
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    invocations = sa.Table(
        "skill_invocations",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("cost", sa.Float(), nullable=True),
    )
    metadata.create_all(engine)

    with engine.begin() as bind:
        bind.execute(invocations.insert().values(id="historical", cost=0.0))
        monkeypatch.setattr(MIG, "op", _SQLiteOps(bind))

        MIG.upgrade()

        assert {"execution_snapshot", "cost_measured"}.issubset(_column_names(bind))
        upgraded = sa.Table(
            "skill_invocations",
            sa.MetaData(),
            autoload_with=bind,
        )
        historical = bind.execute(
            sa.select(upgraded).where(upgraded.c.id == "historical")
        ).mappings().one()
        assert historical["execution_snapshot"] is None
        assert historical["cost"] == 0.0
        assert historical["cost_measured"] is None

        MIG.downgrade()

        names = _column_names(bind)
        assert "execution_snapshot" not in names
        assert "cost_measured" not in names
        assert bind.execute(
            sa.text("SELECT cost FROM skill_invocations WHERE id = 'historical'")
        ).scalar_one() == 0.0
