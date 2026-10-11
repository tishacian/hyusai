"""Contract for the additive Lot-8 measurement evaluation migration."""
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
        / "072_value_measurement_evaluation.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace()
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_072", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            sys.modules.pop("alembic", None)
    return module


MIG = _load_migration()


class _Result:
    def scalar_one(self):
        return 0


class _Connection:
    def __init__(self, calls):
        self.calls = calls

    def execute(self, statement):
        compiled = statement.compile()
        self.calls.append(("execute", str(statement), compiled.params))
        return _Result()


class _Batch:
    def __init__(self, calls):
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def alter_column(self, name, **kwargs):
        self.calls.append(("alter_column", name, kwargs))

    def create_foreign_key(self, name, table, local, remote, **kwargs):
        self.calls.append(("create_foreign_key", name, table, local, remote, kwargs))

    def create_check_constraint(self, name, expression):
        self.calls.append(("create_check_constraint", name, expression))


class _Operations:
    def __init__(self):
        self.calls = []
        self.connection = _Connection(self.calls)

    def add_column(self, table, column):
        self.calls.append(("add_column", table, column.name, column.nullable))

    def get_bind(self):
        return self.connection

    def batch_alter_table(self, table):
        self.calls.append(("batch_alter_table", table))
        return _Batch(self.calls)

    def create_index(self, name, table, columns, *, unique):
        self.calls.append(("create_index", name, table, columns, unique))


def test_revision_extends_blueprint_object_key_head() -> None:
    assert MIG.revision == "072_value_measurement_eval"
    assert len(MIG.revision) <= 32
    assert MIG.down_revision == "071_blueprint_object_keys"


def test_upgrade_backfills_then_constrains_the_measurement_contract(monkeypatch) -> None:
    operations = _Operations()
    monkeypatch.setattr(MIG, "op", operations)

    MIG.upgrade()

    added = {
        call[2]
        for call in operations.calls
        if call[0] == "add_column" and call[1] == "value_measurements"
    }
    assert added == {
        "simulation_id",
        "forecast_delta",
        "assumption_verdict",
        "assumption_evaluation",
    }
    execute_calls = [call[1] for call in operations.calls if call[0] == "execute"]
    assert len(execute_calls) == 2
    assert "value_action_executions" in execute_calls[0]
    assert next(
        call[2]
        for call in operations.calls
        if call[0] == "execute"
    )["assumption_verdict"] == "not_evaluable"
    assert any(
        call[:3]
        == (
            "create_foreign_key",
            "fk_value_measurements_simulation_id_value_simulations",
            "value_simulations",
        )
        for call in operations.calls
    )
    assert any(
        call[:2]
        == (
            "create_check_constraint",
            "ck_value_measurements_assumption_verdict",
        )
        for call in operations.calls
    )
    assert (
        "create_index",
        "ix_value_measurements_simulation_id",
        "value_measurements",
        ["simulation_id"],
        False,
    ) in operations.calls


def _legacy_engine():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    simulations = sa.Table(
        "value_simulations",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
    )
    actions = sa.Table(
        "value_action_executions",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "simulation_id",
            sa.String(36),
            sa.ForeignKey("value_simulations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
    )
    measurements = sa.Table(
        "value_measurements",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "action_execution_id",
            sa.String(36),
            sa.ForeignKey("value_action_executions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("legacy_note", sa.String(80), nullable=False),
    )
    metadata.create_all(engine)
    return engine, simulations, actions, measurements


class _RealSQLiteBatch:
    """Apply this migration's batch contract by rebuilding the real table."""

    def __init__(self, operations, table_name: str):
        assert table_name == "value_measurements"
        self.operations = operations
        self.drop_columns: set[str] = set()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is not None:
            return False
        bind = self.operations.bind
        bind.exec_driver_sql(
            'ALTER TABLE "value_measurements" RENAME TO "_value_measurements_072_old"'
        )
        if self.drop_columns:
            bind.exec_driver_sql(
                """
                CREATE TABLE value_measurements (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    action_execution_id VARCHAR(36) NOT NULL,
                    legacy_note VARCHAR(80) NOT NULL,
                    FOREIGN KEY(action_execution_id)
                        REFERENCES value_action_executions (id) ON DELETE RESTRICT
                )
                """
            )
            columns = "id, action_execution_id, legacy_note"
        else:
            bind.exec_driver_sql(
                """
                CREATE TABLE value_measurements (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    action_execution_id VARCHAR(36) NOT NULL,
                    legacy_note VARCHAR(80) NOT NULL,
                    simulation_id VARCHAR(36) NOT NULL,
                    forecast_delta JSON,
                    assumption_verdict VARCHAR(32) NOT NULL,
                    assumption_evaluation JSON NOT NULL,
                    FOREIGN KEY(action_execution_id)
                        REFERENCES value_action_executions (id) ON DELETE RESTRICT,
                    CONSTRAINT fk_value_measurements_simulation_id_value_simulations
                        FOREIGN KEY(simulation_id)
                        REFERENCES value_simulations (id) ON DELETE RESTRICT,
                    CONSTRAINT ck_value_measurements_assumption_verdict CHECK (
                        assumption_verdict IN (
                            'confirmed', 'partially_confirmed',
                            'not_confirmed', 'not_evaluable'
                        )
                    )
                )
                """
            )
            columns = (
                "id, action_execution_id, legacy_note, simulation_id, "
                "forecast_delta, assumption_verdict, assumption_evaluation"
            )
        bind.exec_driver_sql(
            f"INSERT INTO value_measurements ({columns}) "
            f"SELECT {columns} FROM _value_measurements_072_old"
        )
        bind.exec_driver_sql("DROP TABLE _value_measurements_072_old")
        return False

    def alter_column(self, _name, **_kwargs):
        return None

    def create_foreign_key(self, *_args, **_kwargs):
        return None

    def create_check_constraint(self, *_args, **_kwargs):
        return None

    def drop_constraint(self, *_args, **_kwargs):
        return None

    def drop_column(self, name):
        self.drop_columns.add(name)


class _RealSQLiteOperations:
    def __init__(self, bind):
        self.bind = bind

    def get_bind(self):
        return self.bind

    def add_column(self, table_name: str, column: sa.Column) -> None:
        assert table_name == "value_measurements"
        type_sql = column.type.compile(dialect=self.bind.dialect)
        self.bind.exec_driver_sql(
            f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" {type_sql}'
        )

    def batch_alter_table(self, table_name: str):
        return _RealSQLiteBatch(self, table_name)

    def create_index(self, name, table_name, columns, *, unique):
        unique_sql = "UNIQUE " if unique else ""
        column_sql = ", ".join(f'"{column}"' for column in columns)
        self.bind.exec_driver_sql(
            f'CREATE {unique_sql}INDEX "{name}" ON "{table_name}" ({column_sql})'
        )

    def drop_index(self, name, *, table_name):
        assert table_name == "value_measurements"
        self.bind.exec_driver_sql(f'DROP INDEX "{name}"')


def _expect_integrity_error(connection, statement) -> None:
    savepoint = connection.begin_nested()
    try:
        with pytest.raises(IntegrityError):
            connection.execute(statement)
    finally:
        savepoint.rollback()


def test_real_sqlite_upgrade_backfills_enforces_and_downgrades(monkeypatch) -> None:
    """Exercise the DDL and legacy-row path, not only mocked Alembic calls."""

    engine, simulations, actions, measurements = _legacy_engine()
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.execute(simulations.insert().values(id="simulation-legacy"))
        connection.execute(
            actions.insert().values(
                id="action-legacy",
                simulation_id="simulation-legacy",
            )
        )
        connection.execute(
            measurements.insert().values(
                id="measurement-legacy",
                action_execution_id="action-legacy",
                legacy_note="preserve me",
            )
        )
        operations = _RealSQLiteOperations(connection)
        monkeypatch.setattr(MIG, "op", operations)

        MIG.upgrade()

        upgraded = sa.Table(
            "value_measurements",
            sa.MetaData(),
            autoload_with=connection,
        )
        legacy = connection.execute(
            sa.select(upgraded).where(upgraded.c.id == "measurement-legacy")
        ).mappings().one()
        assert legacy["legacy_note"] == "preserve me"
        assert legacy["simulation_id"] == "simulation-legacy"
        assert legacy["forecast_delta"] is None
        assert legacy["assumption_verdict"] == "not_evaluable"
        assert legacy["assumption_evaluation"] == {
            "schema_version": 1,
            "method": "legacy_backfill",
            "verdict": "not_evaluable",
            "causality": "not_established",
            "declared_assumptions": {},
            "criteria": [],
            "reason": "forecast_comparison_not_persisted_at_measurement_time",
        }

        inspector = sa.inspect(connection)
        assert any(
            row["name"] == "ix_value_measurements_simulation_id"
            and row["column_names"] == ["simulation_id"]
            for row in inspector.get_indexes("value_measurements")
        )
        assert any(
            row["constrained_columns"] == ["simulation_id"]
            and row["referred_table"] == "value_simulations"
            for row in inspector.get_foreign_keys("value_measurements")
        )
        sql = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master "
            "WHERE type='table' AND name='value_measurements'"
        ).scalar_one()
        assert "fk_value_measurements_simulation_id_value_simulations" in sql
        assert "ck_value_measurements_assumption_verdict" in sql

        base_values = {
            "action_execution_id": "action-legacy",
            "legacy_note": "constraint probe",
            "forecast_delta": None,
            "assumption_evaluation": {},
        }
        _expect_integrity_error(
            connection,
            upgraded.insert().values(
                id="measurement-null-simulation",
                simulation_id=None,
                assumption_verdict="not_evaluable",
                **base_values,
            ),
        )
        _expect_integrity_error(
            connection,
            upgraded.insert().values(
                id="measurement-bad-foreign-key",
                simulation_id="simulation-missing",
                assumption_verdict="not_evaluable",
                **base_values,
            ),
        )
        _expect_integrity_error(
            connection,
            upgraded.insert().values(
                id="measurement-bad-verdict",
                simulation_id="simulation-legacy",
                assumption_verdict="invented",
                **base_values,
            ),
        )

        MIG.downgrade()

        downgraded = sa.Table(
            "value_measurements",
            sa.MetaData(),
            autoload_with=connection,
        )
        assert set(downgraded.c.keys()) == {
            "id",
            "action_execution_id",
            "legacy_note",
        }
        assert dict(connection.execute(sa.select(downgraded)).mappings().one()) == {
            "id": "measurement-legacy",
            "action_execution_id": "action-legacy",
            "legacy_note": "preserve me",
        }


def test_downgrade_refuses_post_migration_measurement_evidence_before_any_ddl(
    monkeypatch,
) -> None:
    engine, simulations, actions, measurements = _legacy_engine()
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.execute(simulations.insert().values(id="simulation-live"))
        connection.execute(
            actions.insert().values(
                id="action-live",
                simulation_id="simulation-live",
            )
        )
        connection.execute(
            measurements.insert().values(
                id="measurement-live",
                action_execution_id="action-live",
                legacy_note="keep directional evidence",
            )
        )
        operations = _RealSQLiteOperations(connection)
        monkeypatch.setattr(MIG, "op", operations)
        MIG.upgrade()
        upgraded = sa.Table(
            "value_measurements",
            sa.MetaData(),
            autoload_with=connection,
        )
        connection.execute(
            upgraded.update()
            .where(upgraded.c.id == "measurement-live")
            .values(
                forecast_delta={"value": 5.0},
                assumption_verdict="confirmed",
                assumption_evaluation={
                    "schema_version": 1,
                    "method": "directional_forecast_v1",
                    "verdict": "confirmed",
                    "causality": "not_established",
                    "declared_assumptions": {"window_days": 30},
                    "criteria": [],
                },
            )
        )

        with pytest.raises(RuntimeError, match="not a reconstructible legacy backfill"):
            MIG.downgrade()

        inspector = sa.inspect(connection)
        assert {
            "simulation_id",
            "forecast_delta",
            "assumption_verdict",
            "assumption_evaluation",
        }.issubset(
            {column["name"] for column in inspector.get_columns("value_measurements")}
        )
        assert "ix_value_measurements_simulation_id" in {
            index["name"] for index in inspector.get_indexes("value_measurements")
        }
