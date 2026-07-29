"""Contract and SQLite semantics for relational-integrity migration 074."""

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
        Path(__file__).resolve().parents[3] / "alembic" / "versions" / "074_relational_integrity.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace()
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_074", path)
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


def _schema(*, hardened: bool) -> tuple[sa.MetaData, dict[str, sa.Table]]:
    """Build the relevant 073 schema, optionally with 074 constraints."""

    metadata = sa.MetaData()
    tables: dict[str, sa.Table] = {}

    def table(name: str, *elements: Any) -> sa.Table:
        result = sa.Table(name, metadata, *elements)
        tables[name] = result
        return result

    table("workspaces", sa.Column("id", sa.String(36), primary_key=True))
    systems = table(
        "systems",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=True),
        sa.Column("blueprint_key", sa.String(120), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.UniqueConstraint(
            "workspace_id",
            "blueprint_key",
            name="uq_systems_workspace_blueprint_key",
        ),
    )
    contexts = table(
        "contexts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=True),
        sa.Column("blueprint_key", sa.String(120), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "blueprint_key",
            name="uq_contexts_workspace_blueprint_key",
        ),
    )
    table(
        "runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=True),
        sa.Column("system_id", sa.String(36), nullable=True),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"]),
    )
    table(
        "control_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=True),
        sa.Column("target_id", sa.String(36), nullable=True),
    )
    system_versions = table(
        "system_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("system_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "system_id",
            "version_number",
            name="uq_system_versions_system_version_number",
        ),
    )
    decisions = table(
        "decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scenario_id", sa.String(36), nullable=True),
        sa.UniqueConstraint("scenario_id", name="uq_decisions_scenario_id"),
    )
    table(
        "value_loop_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
    )
    table(
        "value_scenarios",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("system_id", sa.String(36), nullable=False),
        sa.Column("source_run_id", sa.String(36), nullable=False),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.Column("approval_operation_id", sa.String(36), nullable=True),
        sa.Column("approved_simulation_id", sa.String(36), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"]),
        sa.ForeignKeyConstraint(["source_run_id"], ["runs.id"]),
        sa.ForeignKeyConstraint(["operation_id"], ["value_loop_operations.id"]),
        sa.ForeignKeyConstraint(
            ["approval_operation_id"],
            ["value_loop_operations.id"],
        ),
    )
    table(
        "value_simulations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("system_id", sa.String(36), nullable=False),
        sa.Column("scenario_id", sa.String(36), nullable=False),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"]),
        sa.ForeignKeyConstraint(["scenario_id"], ["value_scenarios.id"]),
        sa.ForeignKeyConstraint(["operation_id"], ["value_loop_operations.id"]),
    )
    table(
        "value_action_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("system_id", sa.String(36), nullable=False),
        sa.Column("scenario_id", sa.String(36), nullable=False),
        sa.Column("simulation_id", sa.String(36), nullable=False),
        sa.Column("control_policy_id", sa.String(36), nullable=False),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"]),
        sa.ForeignKeyConstraint(["scenario_id"], ["value_scenarios.id"]),
        sa.ForeignKeyConstraint(["simulation_id"], ["value_simulations.id"]),
        sa.ForeignKeyConstraint(["control_policy_id"], ["control_policies.id"]),
        sa.ForeignKeyConstraint(["operation_id"], ["value_loop_operations.id"]),
    )
    table(
        "value_measurements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("system_id", sa.String(36), nullable=False),
        sa.Column("scenario_id", sa.String(36), nullable=False),
        sa.Column("simulation_id", sa.String(36), nullable=False),
        sa.Column("action_execution_id", sa.String(36), nullable=False),
        sa.Column("source_run_id", sa.String(36), nullable=True),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"]),
        sa.ForeignKeyConstraint(["scenario_id"], ["value_scenarios.id"]),
        sa.ForeignKeyConstraint(["simulation_id"], ["value_simulations.id"]),
        sa.ForeignKeyConstraint(
            ["action_execution_id"],
            ["value_action_executions.id"],
        ),
        sa.ForeignKeyConstraint(["source_run_id"], ["runs.id"]),
        sa.ForeignKeyConstraint(["operation_id"], ["value_loop_operations.id"]),
    )
    table(
        "workspace_app_installations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("app_id", sa.String(120), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.UniqueConstraint(
            "id",
            "workspace_id",
            name="uq_workspace_app_installations_id_workspace",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "app_id",
            name="uq_workspace_app_installations_workspace_app",
        ),
    )
    table(
        "workspace_app_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("installation_id", sa.String(36), nullable=False),
        sa.Column("app_id", sa.String(120), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(
            ["installation_id", "workspace_id"],
            [
                "workspace_app_installations.id",
                "workspace_app_installations.workspace_id",
            ],
            name="fk_workspace_app_operations_installation_tenant",
        ),
        sa.UniqueConstraint(
            "id",
            "workspace_id",
            name="uq_workspace_app_operations_id_workspace",
        ),
    )
    table(
        "workspace_app_lifecycle_step_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.Column("installation_id", sa.String(36), nullable=False),
        sa.Column("app_id", sa.String(120), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(
            ["operation_id", "workspace_id"],
            ["workspace_app_operations.id", "workspace_app_operations.workspace_id"],
            name="fk_workspace_app_step_receipts_operation_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["installation_id", "workspace_id"],
            [
                "workspace_app_installations.id",
                "workspace_app_installations.workspace_id",
            ],
            name="fk_workspace_app_step_receipts_installation_tenant",
        ),
    )

    if hardened:
        for table_name, name, columns in MIG.CANDIDATE_KEYS:
            tables[table_name].append_constraint(sa.UniqueConstraint(*columns, name=name))
        for (
            table_name,
            name,
            local_columns,
            remote_table,
            remote_columns,
            ondelete,
            deferrable,
            initially,
        ) in MIG.COMPOSITE_FOREIGN_KEYS:
            tables[table_name].append_constraint(
                sa.ForeignKeyConstraint(
                    local_columns,
                    [f"{remote_table}.{column}" for column in remote_columns],
                    name=name,
                    ondelete=ondelete,
                    deferrable=deferrable,
                    initially=initially,
                )
            )
        predicate = sa.text("workspace_id IS NULL")
        sa.Index(
            "uq_systems_global_blueprint_key",
            systems.c.blueprint_key,
            unique=True,
            sqlite_where=predicate,
            postgresql_where=predicate,
        )
        sa.Index(
            "uq_contexts_global_blueprint_key",
            contexts.c.blueprint_key,
            unique=True,
            sqlite_where=predicate,
            postgresql_where=predicate,
        )
    else:
        sa.Index(
            "ix_system_versions_system_version",
            system_versions.c.system_id,
            system_versions.c.version_number,
        )
        sa.Index("ix_decisions_scenario_id", decisions.c.scenario_id)

    return metadata, tables


def _engine(*, hardened: bool) -> tuple[sa.Engine, dict[str, sa.Table]]:
    engine = sa.create_engine("sqlite://")
    metadata, tables = _schema(hardened=hardened)
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        metadata.create_all(connection)
    return engine, tables


def _seed_valid_lineage(connection: sa.Connection, tables: dict[str, sa.Table]) -> None:
    connection.execute(
        tables["workspaces"].insert(),
        [{"id": "ws-a"}, {"id": "ws-b"}],
    )
    connection.execute(
        tables["systems"].insert(),
        [
            {"id": "sys-a", "workspace_id": "ws-a", "blueprint_key": "sys-a"},
            {"id": "sys-b", "workspace_id": "ws-b", "blueprint_key": "sys-b"},
            {"id": "global-a", "workspace_id": None, "blueprint_key": "global-a"},
        ],
    )
    connection.execute(
        tables["contexts"].insert(),
        [{"id": "ctx-global-a", "workspace_id": None, "blueprint_key": "ctx-a"}],
    )
    connection.execute(
        tables["runs"].insert(),
        [
            {"id": "run-a", "workspace_id": "ws-a", "system_id": "sys-a"},
            {"id": "run-b", "workspace_id": "ws-b", "system_id": "sys-b"},
        ],
    )
    connection.execute(
        tables["control_policies"].insert(),
        [
            {"id": "policy-a", "workspace_id": "ws-a", "target_id": "sys-a"},
            {"id": "policy-b", "workspace_id": "ws-b", "target_id": "sys-b"},
        ],
    )
    connection.execute(
        tables["value_loop_operations"].insert(),
        [
            {"id": name, "workspace_id": "ws-a"}
            for name in ("op-scenario", "op-approval", "op-sim", "op-act", "op-measure")
        ]
        + [{"id": "op-b", "workspace_id": "ws-b"}],
    )
    connection.execute(
        tables["value_scenarios"].insert(),
        {
            "id": "scenario-a",
            "workspace_id": "ws-a",
            "system_id": "sys-a",
            "source_run_id": "run-a",
            "operation_id": "op-scenario",
            "approval_operation_id": "op-approval",
            "approved_simulation_id": None,
        },
    )
    connection.execute(
        tables["value_simulations"].insert(),
        {
            "id": "simulation-a",
            "workspace_id": "ws-a",
            "system_id": "sys-a",
            "scenario_id": "scenario-a",
            "operation_id": "op-sim",
        },
    )
    connection.execute(
        tables["value_scenarios"]
        .update()
        .where(tables["value_scenarios"].c.id == "scenario-a")
        .values(approved_simulation_id="simulation-a")
    )
    connection.execute(
        tables["value_action_executions"].insert(),
        {
            "id": "action-a",
            "workspace_id": "ws-a",
            "system_id": "sys-a",
            "scenario_id": "scenario-a",
            "simulation_id": "simulation-a",
            "control_policy_id": "policy-a",
            "operation_id": "op-act",
        },
    )
    connection.execute(
        tables["value_measurements"].insert(),
        {
            "id": "measurement-a",
            "workspace_id": "ws-a",
            "system_id": "sys-a",
            "scenario_id": "scenario-a",
            "simulation_id": "simulation-a",
            "action_execution_id": "action-a",
            "source_run_id": "run-a",
            "operation_id": "op-measure",
        },
    )
    connection.execute(
        tables["workspace_app_installations"].insert(),
        [
            {"id": "install-a", "workspace_id": "ws-a", "app_id": "app-a"},
            {"id": "install-b", "workspace_id": "ws-a", "app_id": "app-b"},
        ],
    )
    connection.execute(
        tables["workspace_app_operations"].insert(),
        {
            "id": "app-operation-a",
            "workspace_id": "ws-a",
            "installation_id": "install-a",
            "app_id": "app-a",
        },
    )
    connection.execute(
        tables["workspace_app_lifecycle_step_receipts"].insert(),
        {
            "id": "receipt-a",
            "workspace_id": "ws-a",
            "operation_id": "app-operation-a",
            "installation_id": "install-a",
            "app_id": "app-a",
        },
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

    def drop_constraint(self, name: str, *, type_: str) -> None:
        self.operations.calls.append(("drop_constraint", self.table_name, name, type_))


class _OperationsRecorder:
    def __init__(self, connection: sa.Connection | None = None):
        self.connection = connection
        self.calls: list[tuple[Any, ...]] = []

    def get_bind(self) -> sa.Connection:
        assert self.connection is not None
        return self.connection

    def batch_alter_table(self, table_name: str) -> _BatchRecorder:
        return _BatchRecorder(self, table_name)

    def create_index(
        self,
        name: str,
        table_name: str,
        columns: list[str],
        *,
        unique: bool,
        **options: Any,
    ) -> None:
        self.calls.append(("create_index", name, table_name, tuple(columns), unique, options))

    def drop_index(self, name: str, *, table_name: str) -> None:
        self.calls.append(("drop_index", name, table_name))


def _expect_integrity_error(
    connection: sa.Connection,
    statement: Any,
    parameters: dict[str, Any] | None = None,
) -> None:
    savepoint = connection.begin_nested()
    try:
        with pytest.raises(IntegrityError):
            connection.execute(statement, parameters or {})
    finally:
        savepoint.rollback()


def _foreign_key_contract(inspector: sa.Inspector, table_name: str) -> dict[str, Any]:
    return {
        str(item["name"]): item
        for item in inspector.get_foreign_keys(table_name)
        if item.get("name")
    }


def test_revision_extends_the_exact_workspace_app_steps_head() -> None:
    assert MIG.revision == "074_relational_integrity"
    assert len(MIG.revision) <= 32
    assert MIG.down_revision == "073_workspace_app_steps"


def test_composite_foreign_keys_have_equal_cardinality_and_exact_action_lineage() -> None:
    """Prevent a silent column shift in the longest tenant-first relation."""

    for (
        _table_name,
        _name,
        local_columns,
        _remote_table,
        remote_columns,
        *_options,
    ) in MIG.COMPOSITE_FOREIGN_KEYS:
        assert len(local_columns) == len(remote_columns)

    measurement_action = next(
        item
        for item in MIG.COMPOSITE_FOREIGN_KEYS
        if item[1] == "fk_value_measurements_action_lineage"
    )
    assert measurement_action[2] == (
        "workspace_id",
        "system_id",
        "scenario_id",
        "simulation_id",
        "action_execution_id",
    )
    assert measurement_action[3] == "value_action_executions"
    assert measurement_action[4] == (
        "workspace_id",
        "system_id",
        "scenario_id",
        "simulation_id",
        "id",
    )


def test_preflight_aggregates_exact_drift_and_executes_no_ddl(monkeypatch) -> None:
    engine, tables = _engine(hardened=False)
    with engine.begin() as connection:
        # Keep SQLite enforcement disabled while manufacturing the historical
        # drift that 073's independent foreign keys could accept.
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        _seed_valid_lineage(connection, tables)
        connection.execute(
            tables["value_scenarios"]
            .update()
            .where(tables["value_scenarios"].c.id == "scenario-a")
            .values(source_run_id="run-b")
        )
        connection.execute(
            tables["value_action_executions"]
            .update()
            .where(tables["value_action_executions"].c.id == "action-a")
            .values(control_policy_id="policy-b")
        )
        connection.execute(
            tables["workspace_app_operations"]
            .update()
            .where(tables["workspace_app_operations"].c.id == "app-operation-a")
            .values(app_id="app-b")
        )
        connection.execute(
            tables["systems"].insert(),
            {"id": "global-b", "workspace_id": None, "blueprint_key": "global-a"},
        )
        connection.execute(
            tables["contexts"].insert(),
            {"id": "ctx-global-b", "workspace_id": None, "blueprint_key": "ctx-a"},
        )

        operations = _OperationsRecorder(connection)
        monkeypatch.setattr(MIG, "op", operations)
        with pytest.raises(
            RuntimeError,
            match="Relational integrity preflight failed",
        ) as caught:
            MIG.upgrade()

        assert operations.calls == []
        report = json.loads(str(caught.value).split(": ", 1)[1])
        assert report["structural_issues"] == []
        by_relation = {item["relation"]: item for item in report["data_drifts"]}
        assert by_relation["value_scenarios.source_run_lineage"] == {
            "relation": "value_scenarios.source_run_lineage",
            "violation_count": 1,
            "example_ids": ["scenario-a"],
        }
        assert by_relation["value_action_executions.control_policy_lineage"]["example_ids"] == [
            "action-a"
        ]
        assert by_relation["workspace_app_operations.installation_lineage"]["example_ids"] == [
            "app-operation-a"
        ]
        assert by_relation["workspace_app_step_receipts.operation_lineage"]["example_ids"] == [
            "receipt-a"
        ]
        assert by_relation["systems.global_blueprint_key_unique"]["violation_count"] == 1
        assert by_relation["contexts.global_blueprint_key_unique"]["violation_count"] == 1


def test_upgrade_emits_exact_candidate_keys_foreign_keys_and_indexes(monkeypatch) -> None:
    engine, _tables = _engine(hardened=False)
    with engine.begin() as connection:
        operations = _OperationsRecorder(connection)
        monkeypatch.setattr(MIG, "op", operations)
        MIG.upgrade()

    unique_calls = {
        (call[1], call[2], call[3]) for call in operations.calls if call[0] == "create_unique"
    }
    assert unique_calls == {
        (table_name, name, columns) for table_name, name, columns in MIG.CANDIDATE_KEYS
    }

    foreign_key_calls = {
        (call[1], call[2]): (
            call[3],
            call[4],
            call[5],
            call[6],
        )
        for call in operations.calls
        if call[0] == "create_fk"
    }
    assert set(foreign_key_calls) == {
        (table_name, name) for table_name, name, *_rest in MIG.COMPOSITE_FOREIGN_KEYS
    }
    approved = foreign_key_calls[
        ("value_scenarios", "fk_value_scenarios_approved_simulation_lineage")
    ]
    assert approved == (
        ("workspace_id", "system_id", "id", "approved_simulation_id"),
        "value_simulations",
        ("workspace_id", "system_id", "scenario_id", "id"),
        {"ondelete": "RESTRICT", "deferrable": True, "initially": "DEFERRED"},
    )

    partial_indexes = {
        (call[1], call[2]): (call[3], call[4], call[5])
        for call in operations.calls
        if call[0] == "create_index" and call[1].startswith("uq_")
    }
    assert set(partial_indexes) == {
        (index_name, table_name) for table_name, index_name in MIG.GLOBAL_BLUEPRINT_INDEXES
    }
    for columns, unique, options in partial_indexes.values():
        assert columns == ("blueprint_key",)
        assert unique is True
        assert str(options["sqlite_where"]) == "workspace_id IS NULL"
        assert str(options["postgresql_where"]) == "workspace_id IS NULL"

    assert {call for call in operations.calls if call[0] == "drop_index"} == {
        ("drop_index", index_name, table_name)
        for table_name, index_name, _columns in MIG.REDUNDANT_INDEXES
    }


def test_sqlite_schema_enforces_value_app_and_global_blueprint_lineage() -> None:
    engine, tables = _engine(hardened=True)
    with engine.begin() as connection:
        _seed_valid_lineage(connection, tables)

        # All referenced IDs exist; only their tenant/System lineage is wrong.
        _expect_integrity_error(
            connection,
            tables["value_scenarios"].insert(),
            {
                "id": "scenario-wrong-tenant",
                "workspace_id": "ws-a",
                "system_id": "sys-b",
                "source_run_id": "run-b",
                "operation_id": "op-scenario",
                "approval_operation_id": None,
                "approved_simulation_id": None,
            },
        )

        connection.execute(
            tables["value_loop_operations"].insert(),
            [
                {"id": "op-scenario-2", "workspace_id": "ws-a"},
                {"id": "op-sim-2", "workspace_id": "ws-a"},
            ],
        )
        connection.execute(
            tables["value_scenarios"].insert(),
            {
                "id": "scenario-2",
                "workspace_id": "ws-a",
                "system_id": "sys-a",
                "source_run_id": "run-a",
                "operation_id": "op-scenario-2",
                "approval_operation_id": None,
                "approved_simulation_id": None,
            },
        )
        connection.execute(
            tables["value_simulations"].insert(),
            {
                "id": "simulation-2",
                "workspace_id": "ws-a",
                "system_id": "sys-a",
                "scenario_id": "scenario-2",
                "operation_id": "op-sim-2",
            },
        )
        _expect_integrity_error(
            connection,
            tables["value_action_executions"].insert(),
            {
                "id": "action-cross-scenario",
                "workspace_id": "ws-a",
                "system_id": "sys-a",
                "scenario_id": "scenario-a",
                "simulation_id": "simulation-2",
                "control_policy_id": "policy-a",
                "operation_id": "op-act",
            },
        )
        # The 069 tenant-only FK accepts this shape; 074 also binds app_id.
        _expect_integrity_error(
            connection,
            tables["workspace_app_operations"].insert(),
            {
                "id": "app-operation-wrong-app",
                "workspace_id": "ws-a",
                "installation_id": "install-a",
                "app_id": "app-b",
            },
        )
        _expect_integrity_error(
            connection,
            tables["workspace_app_lifecycle_step_receipts"].insert(),
            {
                "id": "receipt-wrong-app",
                "workspace_id": "ws-a",
                "operation_id": "app-operation-a",
                "installation_id": "install-a",
                "app_id": "app-b",
            },
        )

        _expect_integrity_error(
            connection,
            tables["systems"].insert(),
            {
                "id": "global-duplicate",
                "workspace_id": None,
                "blueprint_key": "global-a",
            },
        )
        _expect_integrity_error(
            connection,
            tables["contexts"].insert(),
            {
                "id": "ctx-global-duplicate",
                "workspace_id": None,
                "blueprint_key": "ctx-a",
            },
        )
        # The same key remains legal in different tenant scopes.
        connection.execute(
            tables["systems"].insert(),
            [
                {"id": "tenant-key-a", "workspace_id": "ws-a", "blueprint_key": "shared"},
                {"id": "tenant-key-b", "workspace_id": "ws-b", "blueprint_key": "shared"},
            ],
        )

    # The cyclic edge is intentionally deferred, so the violation is raised
    # at the real transaction boundary rather than at the UPDATE statement.
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(
            tables["value_scenarios"]
            .update()
            .where(tables["value_scenarios"].c.id == "scenario-a")
            .values(approved_simulation_id="simulation-2")
        )
        with pytest.raises(IntegrityError):
            transaction.commit()
        if transaction.is_active:
            transaction.rollback()

    inspector = sa.inspect(engine)
    for table_name, name, columns in MIG.CANDIDATE_KEYS:
        uniques = {
            item["name"]: tuple(item["column_names"])
            for item in inspector.get_unique_constraints(table_name)
        }
        assert uniques[name] == columns

    for (
        table_name,
        name,
        local_columns,
        remote_table,
        remote_columns,
        *_rest,
    ) in MIG.COMPOSITE_FOREIGN_KEYS:
        foreign_key = _foreign_key_contract(inspector, table_name)[name]
        assert tuple(foreign_key["constrained_columns"]) == local_columns
        assert foreign_key["referred_table"] == remote_table
        assert tuple(foreign_key["referred_columns"]) == remote_columns

    indexes = {
        table_name: {item["name"]: item for item in inspector.get_indexes(table_name)}
        for table_name in ("systems", "contexts", "system_versions", "decisions")
    }
    assert "uq_systems_global_blueprint_key" in indexes["systems"]
    assert "uq_contexts_global_blueprint_key" in indexes["contexts"]
    assert "ix_system_versions_system_version" not in indexes["system_versions"]
    assert "ix_decisions_scenario_id" not in indexes["decisions"]

    with engine.connect() as connection:
        scenario_ddl = connection.execute(
            sa.text(
                "SELECT sql FROM sqlite_master " "WHERE type = 'table' AND name = 'value_scenarios'"
            )
        ).scalar_one()
    assert "DEFERRABLE INITIALLY DEFERRED" in scenario_ddl


def test_cyclic_approved_simulation_fk_is_really_deferred_on_sqlite() -> None:
    engine, tables = _engine(hardened=True)
    with engine.begin() as connection:
        connection.execute(tables["workspaces"].insert(), {"id": "ws-a"})
        connection.execute(
            tables["systems"].insert(),
            {"id": "sys-a", "workspace_id": "ws-a", "blueprint_key": "sys-a"},
        )
        connection.execute(
            tables["runs"].insert(),
            {"id": "run-a", "workspace_id": "ws-a", "system_id": "sys-a"},
        )
        connection.execute(
            tables["value_loop_operations"].insert(),
            [
                {"id": "scenario-op", "workspace_id": "ws-a"},
                {"id": "simulation-op", "workspace_id": "ws-a"},
            ],
        )
        # The forecast does not exist at the first insert.  The deferred cycle
        # is satisfied before commit and must therefore be accepted.
        connection.execute(
            tables["value_scenarios"].insert(),
            {
                "id": "scenario-a",
                "workspace_id": "ws-a",
                "system_id": "sys-a",
                "source_run_id": "run-a",
                "operation_id": "scenario-op",
                "approval_operation_id": None,
                "approved_simulation_id": "simulation-a",
            },
        )
        connection.execute(
            tables["value_simulations"].insert(),
            {
                "id": "simulation-a",
                "workspace_id": "ws-a",
                "system_id": "sys-a",
                "scenario_id": "scenario-a",
                "operation_id": "simulation-op",
            },
        )


def test_real_alembic_upgrade_and_downgrade_round_trip(monkeypatch) -> None:
    """Exercise the migration through Alembic, not only the call recorder."""

    migration_api = pytest.importorskip("alembic.migration")
    operations_api = pytest.importorskip("alembic.operations")
    engine, _tables = _engine(hardened=False)
    with engine.connect() as connection:
        # Alembic's SQLite batch mode must be allowed to rebuild tables that
        # already participate in foreign keys.  The rebuilt constraints are
        # inspected below and are enforceable once applications enable the
        # standard SQLite foreign-key pragma on their connection.
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
        assert sum(
            any(item.get("name") == name for item in inspector.get_unique_constraints(table_name))
            for table_name, name, _columns in MIG.CANDIDATE_KEYS
        ) == len(MIG.CANDIDATE_KEYS)
        assert sum(
            any(item.get("name") == name for item in inspector.get_foreign_keys(table_name))
            for table_name, name, *_rest in MIG.COMPOSITE_FOREIGN_KEYS
        ) == len(MIG.COMPOSITE_FOREIGN_KEYS)
        assert all(
            any(
                item.get("name") == index_name and bool(item.get("unique"))
                for item in inspector.get_indexes(table_name)
            )
            for table_name, index_name in MIG.GLOBAL_BLUEPRINT_INDEXES
        )
        assert all(
            not any(item.get("name") == index_name for item in inspector.get_indexes(table_name))
            for table_name, index_name, _columns in MIG.REDUNDANT_INDEXES
        )

        # Inspector queries open an implicit transaction under SQLAlchemy 2.
        connection.commit()
        with connection.begin():
            MIG.downgrade()
        inspector = sa.inspect(connection)
        assert all(
            not any(
                item.get("name") == name for item in inspector.get_unique_constraints(table_name)
            )
            for table_name, name, _columns in MIG.CANDIDATE_KEYS
        )
        assert all(
            not any(item.get("name") == name for item in inspector.get_foreign_keys(table_name))
            for table_name, name, *_rest in MIG.COMPOSITE_FOREIGN_KEYS
        )
        assert all(
            not any(item.get("name") == index_name for item in inspector.get_indexes(table_name))
            for table_name, index_name in MIG.GLOBAL_BLUEPRINT_INDEXES
        )
        assert all(
            any(item.get("name") == index_name for item in inspector.get_indexes(table_name))
            for table_name, index_name, _columns in MIG.REDUNDANT_INDEXES
        )


def test_downgrade_is_the_exact_inverse_and_restores_073_indexes(monkeypatch) -> None:
    operations = _OperationsRecorder()
    monkeypatch.setattr(MIG, "op", operations)
    MIG.downgrade()

    dropped_foreign_keys = {
        (call[1], call[2])
        for call in operations.calls
        if call[0] == "drop_constraint" and call[3] == "foreignkey"
    }
    assert dropped_foreign_keys == {
        (table_name, name) for table_name, name, *_rest in MIG.COMPOSITE_FOREIGN_KEYS
    }
    dropped_unique_keys = {
        (call[1], call[2])
        for call in operations.calls
        if call[0] == "drop_constraint" and call[3] == "unique"
    }
    assert dropped_unique_keys == {
        (table_name, name) for table_name, name, _columns in MIG.CANDIDATE_KEYS
    }
    assert {call for call in operations.calls if call[0] == "drop_index"} == {
        ("drop_index", index_name, table_name)
        for table_name, index_name in MIG.GLOBAL_BLUEPRINT_INDEXES
    }
    recreated = {
        (call[1], call[2], call[3], call[4])
        for call in operations.calls
        if call[0] == "create_index"
    }
    assert recreated == {
        (index_name, table_name, columns, False)
        for table_name, index_name, columns in MIG.REDUNDANT_INDEXES
    }
