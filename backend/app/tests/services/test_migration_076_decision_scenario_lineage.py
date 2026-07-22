"""Migration 076 contract, drift preflight and destructive downgrade guard."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError


def _load_migration():
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "076_decision_scenario_lineage.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace()
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_076", path)
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


def _schema(*, hardened: bool) -> tuple[sa.MetaData, dict[str, sa.Table]]:
    metadata = sa.MetaData()
    scenarios = sa.Table(
        "value_scenarios",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("system_id", sa.String(36), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "system_id",
            "id",
            name="uq_value_scenarios_ws_system_id",
        ),
        *(
            (
                sa.UniqueConstraint(
                    *MIG.REMOTE_LINEAGE_COLUMNS,
                    name=MIG.LINEAGE_CANDIDATE_KEY,
                ),
            )
            if hardened
            else ()
        ),
    )
    decision_elements: list[Any] = [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=True),
        sa.Column("scenario_id", sa.String(36), nullable=True),
        sa.Column("target_id", sa.String(36), nullable=True),
        sa.UniqueConstraint("scenario_id", name="uq_decisions_scenario_id"),
    ]
    if hardened:
        decision_elements.extend(
            [
                sa.ForeignKeyConstraint(
                    MIG.LOCAL_LINEAGE_COLUMNS,
                    [f"value_scenarios.{column}" for column in MIG.REMOTE_LINEAGE_COLUMNS],
                    name=MIG.LINEAGE_FOREIGN_KEY,
                    ondelete="RESTRICT",
                ),
                sa.CheckConstraint(
                    "scenario_id IS NULL OR "
                    "(workspace_id IS NOT NULL AND target_id IS NOT NULL)",
                    name=MIG.LINEAGE_CHECK,
                ),
            ]
        )
    else:
        decision_elements.append(
            sa.ForeignKeyConstraint(
                ["scenario_id"],
                ["value_scenarios.id"],
                name=MIG.LEGACY_FOREIGN_KEY,
                ondelete="SET NULL",
            )
        )
    decisions = sa.Table("decisions", metadata, *decision_elements)
    return metadata, {"value_scenarios": scenarios, "decisions": decisions}


def _engine(*, hardened: bool) -> tuple[sa.Engine, dict[str, sa.Table]]:
    engine = sa.create_engine("sqlite:///:memory:")

    @sa.event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    metadata, tables = _schema(hardened=hardened)
    metadata.create_all(engine)
    return engine, tables


def _seed_scenarios(connection: sa.Connection, tables: dict[str, sa.Table]) -> None:
    connection.execute(
        tables["value_scenarios"].insert(),
        [
            {"id": "scenario-1", "workspace_id": "w1", "system_id": "sys-1"},
            {"id": "scenario-2", "workspace_id": "w1", "system_id": "sys-2"},
            {"id": "scenario-3", "workspace_id": "w2", "system_id": "sys-3"},
            {"id": "scenario-4", "workspace_id": "w2", "system_id": "sys-3"},
        ],
    )


class _BatchRecorder:
    def __init__(self, operations: _OperationsRecorder, table_name: str):
        self.operations = operations
        self.table_name = table_name

    def __enter__(self) -> _BatchRecorder:
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> bool:
        return False

    def create_unique_constraint(self, name: str, columns: list[str]) -> None:
        self.operations.calls.append(("create_unique", self.table_name, name, tuple(columns)))

    def drop_constraint(self, name: str, *, type_: str) -> None:
        self.operations.calls.append(("drop", self.table_name, name, type_))

    def create_check_constraint(self, name: str, condition: str) -> None:
        self.operations.calls.append(("create_check", self.table_name, name, condition))

    def create_foreign_key(
        self,
        name: str,
        remote_table: str,
        local_columns: list[str],
        remote_columns: list[str],
        **options: Any,
    ) -> None:
        self.operations.calls.append(
            (
                "create_fk",
                self.table_name,
                name,
                tuple(local_columns),
                remote_table,
                tuple(remote_columns),
                options,
            )
        )


class _OperationsRecorder:
    def __init__(self, connection: sa.Connection):
        self.connection = connection
        self.calls: list[tuple[Any, ...]] = []

    def get_bind(self) -> sa.Connection:
        return self.connection

    def batch_alter_table(self, table_name: str) -> _BatchRecorder:
        return _BatchRecorder(self, table_name)


def _expect_integrity_error(
    connection: sa.Connection,
    statement: Any,
    parameters: dict[str, Any],
) -> None:
    savepoint = connection.begin_nested()
    try:
        with pytest.raises(IntegrityError):
            connection.execute(statement, parameters)
    finally:
        savepoint.rollback()


def test_revision_extends_simulation_approval_pin_head() -> None:
    assert MIG.revision == "076_decision_scenario_lineage"
    assert len(MIG.revision) <= 32
    assert MIG.down_revision == "075_simulation_approval_pin"


def test_preflight_reports_all_lineage_drift_and_executes_no_ddl(monkeypatch) -> None:
    engine, tables = _engine(hardened=False)
    with engine.begin() as connection:
        _seed_scenarios(connection, tables)
        # Every scenario id is valid under 075.  The unbound tenant/System
        # components are the attacks that 076 must detect before any DDL.
        connection.execute(
            tables["decisions"].insert(),
            [
                {
                    "id": "decision-cross-tenant",
                    "workspace_id": "w2",
                    "scenario_id": "scenario-1",
                    "target_id": "sys-1",
                },
                {
                    "id": "decision-cross-system",
                    "workspace_id": "w1",
                    "scenario_id": "scenario-2",
                    "target_id": "sys-1",
                },
                {
                    "id": "decision-null-target",
                    "workspace_id": "w2",
                    "scenario_id": "scenario-3",
                    "target_id": None,
                },
                {
                    "id": "decision-null-workspace",
                    "workspace_id": None,
                    "scenario_id": "scenario-4",
                    "target_id": "sys-3",
                },
            ],
        )
        operations = _OperationsRecorder(connection)
        monkeypatch.setattr(MIG, "op", operations)

        with pytest.raises(
            RuntimeError,
            match="Decision scenario lineage preflight failed",
        ) as caught:
            MIG.upgrade()

        assert operations.calls == []
        report = json.loads(str(caught.value).split(": ", 1)[1])
        assert report["structural_issues"] == []
        assert report["data_drifts"] == [
            {
                "relation": "decisions.scenario_lineage",
                "violation_count": 4,
                "example_ids": [
                    "decision-cross-system",
                    "decision-cross-tenant",
                    "decision-null-target",
                    "decision-null-workspace",
                ],
            }
        ]


def test_preflight_fails_closed_on_unexpected_075_structure(monkeypatch) -> None:
    metadata = sa.MetaData()
    sa.Table(
        "value_scenarios",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("system_id", sa.String(36), nullable=False),
    )
    sa.Table(
        "decisions",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36)),
        sa.Column("scenario_id", sa.String(36)),
        # target_id and the exact legacy FK are both deliberately absent.
    )
    engine = sa.create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    with engine.begin() as connection:
        operations = _OperationsRecorder(connection)
        monkeypatch.setattr(MIG, "op", operations)
        with pytest.raises(RuntimeError, match="preflight failed") as caught:
            MIG.upgrade()

        assert operations.calls == []
        report = json.loads(str(caught.value).split(": ", 1)[1])
        assert report["data_drifts"] == []
        assert report["structural_issues"]


def test_upgrade_emits_exact_composite_authority(monkeypatch) -> None:
    engine, _tables = _engine(hardened=False)
    with engine.begin() as connection:
        operations = _OperationsRecorder(connection)
        monkeypatch.setattr(MIG, "op", operations)
        MIG.upgrade()

    assert operations.calls == [
        (
            "create_unique",
            "value_scenarios",
            MIG.LINEAGE_CANDIDATE_KEY,
            MIG.REMOTE_LINEAGE_COLUMNS,
        ),
        ("drop", "decisions", MIG.LEGACY_FOREIGN_KEY, "foreignkey"),
        (
            "create_check",
            "decisions",
            MIG.LINEAGE_CHECK,
            MIG.LINEAGE_CHECK_SQL,
        ),
        (
            "create_fk",
            "decisions",
            MIG.LINEAGE_FOREIGN_KEY,
            MIG.LOCAL_LINEAGE_COLUMNS,
            "value_scenarios",
            MIG.REMOTE_LINEAGE_COLUMNS,
            {"ondelete": "RESTRICT"},
        ),
    ]


@pytest.mark.parametrize(
    ("workspace_id", "target_id"),
    [
        ("w2", "sys-1"),
        ("w1", "sys-2"),
        (None, "sys-1"),
        ("w1", None),
    ],
    ids=("cross-tenant", "cross-system", "null-tenant", "null-system"),
)
def test_hardened_schema_rejects_decision_lineage_attacks(
    workspace_id: str | None,
    target_id: str | None,
) -> None:
    engine, tables = _engine(hardened=True)
    with engine.begin() as connection:
        _seed_scenarios(connection, tables)
        _expect_integrity_error(
            connection,
            tables["decisions"].insert(),
            {
                "id": "decision-attack",
                "workspace_id": workspace_id,
                "scenario_id": "scenario-1",
                "target_id": target_id,
            },
        )


def test_downgrade_refuses_to_remove_authority_from_linked_decisions(monkeypatch) -> None:
    engine, tables = _engine(hardened=True)
    with engine.begin() as connection:
        _seed_scenarios(connection, tables)
        connection.execute(
            tables["decisions"].insert(),
            {
                "id": "decision-1",
                "workspace_id": "w1",
                "scenario_id": "scenario-1",
                "target_id": "sys-1",
            },
        )
        operations = _OperationsRecorder(connection)
        monkeypatch.setattr(MIG, "op", operations)

        with pytest.raises(RuntimeError, match="refusing destructive downgrade"):
            MIG.downgrade()
        assert operations.calls == []


def test_downgrade_fails_closed_when_active_authority_cannot_be_verified(
    monkeypatch,
) -> None:
    engine, _tables = _engine(hardened=False)
    with engine.begin() as connection:
        operations = _OperationsRecorder(connection)
        monkeypatch.setattr(MIG, "op", operations)

        with pytest.raises(RuntimeError, match="active authority cannot be verified"):
            MIG.downgrade()
        assert operations.calls == []


def test_downgrade_restores_075_only_when_no_linked_decision_exists(monkeypatch) -> None:
    engine, _tables = _engine(hardened=True)
    with engine.begin() as connection:
        operations = _OperationsRecorder(connection)
        monkeypatch.setattr(MIG, "op", operations)
        MIG.downgrade()

    assert operations.calls == [
        ("drop", "decisions", MIG.LINEAGE_FOREIGN_KEY, "foreignkey"),
        ("drop", "decisions", MIG.LINEAGE_CHECK, "check"),
        (
            "create_fk",
            "decisions",
            MIG.LEGACY_FOREIGN_KEY,
            ("scenario_id",),
            "value_scenarios",
            ("id",),
            {"ondelete": "SET NULL"},
        ),
        ("drop", "value_scenarios", MIG.LINEAGE_CANDIDATE_KEY, "unique"),
    ]


def test_real_alembic_upgrade_and_empty_downgrade_round_trip(monkeypatch) -> None:
    migration_api = pytest.importorskip("alembic.migration")
    operations_api = pytest.importorskip("alembic.operations")
    engine, _tables = _engine(hardened=False)

    with engine.connect() as connection:
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        context = migration_api.MigrationContext.configure(
            connection,
            opts={"render_as_batch": True},
        )
        monkeypatch.setattr(MIG, "op", operations_api.Operations(context))

        with connection.begin():
            MIG.upgrade()

        inspector = sa.inspect(connection)
        lineage = {
            item["name"]: item for item in inspector.get_foreign_keys("decisions")
        }[MIG.LINEAGE_FOREIGN_KEY]
        assert tuple(lineage["constrained_columns"]) == MIG.LOCAL_LINEAGE_COLUMNS
        assert tuple(lineage["referred_columns"]) == MIG.REMOTE_LINEAGE_COLUMNS
        assert MIG.LINEAGE_CHECK in {
            item["name"] for item in inspector.get_check_constraints("decisions")
        }
        assert MIG.LINEAGE_CANDIDATE_KEY in {
            item["name"] for item in inspector.get_unique_constraints("value_scenarios")
        }

        connection.commit()
        with connection.begin():
            MIG.downgrade()

        inspector = sa.inspect(connection)
        foreign_keys = {
            item["name"]: item for item in inspector.get_foreign_keys("decisions")
        }
        assert MIG.LINEAGE_FOREIGN_KEY not in foreign_keys
        assert MIG.LEGACY_FOREIGN_KEY in foreign_keys
        assert MIG.LINEAGE_CHECK not in {
            item["name"] for item in inspector.get_check_constraints("decisions")
        }
        assert MIG.LINEAGE_CANDIDATE_KEY not in {
            item["name"] for item in inspector.get_unique_constraints("value_scenarios")
        }
