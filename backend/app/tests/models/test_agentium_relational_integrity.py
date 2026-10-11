"""Database-level tenant and lineage invariants for Lots 8 and 9."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

import app.models  # noqa: F401 -- register the complete canonical metadata
from app.db.base import Base
from app.models.context import Context
from app.models.decision import Decision
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.workspace import WorkspaceMemberAppEntitlement


@pytest.fixture()
def integrity_engine() -> Iterator[sa.Engine]:
    engine = sa.create_engine("sqlite:///:memory:")

    @sa.event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
    yield engine
    engine.dispose()


def _table(name: str) -> sa.Table:
    return Base.metadata.tables[name]


def _seed_workspaces(connection: sa.Connection) -> None:
    connection.execute(
        _table("workspaces").insert(),
        [
            {"id": "w1", "name": "Workspace 1", "slug": "workspace-1"},
            {"id": "w2", "name": "Workspace 2", "slug": "workspace-2"},
        ],
    )


def _seed_value_lineage(connection: sa.Connection) -> None:
    _seed_workspaces(connection)
    connection.execute(
        _table("systems").insert(),
        [
            {"id": "sys-1", "workspace_id": "w1", "blueprint_key": "sys-1", "name": "S1"},
            {"id": "sys-2", "workspace_id": "w1", "blueprint_key": "sys-2", "name": "S2"},
            {"id": "sys-3", "workspace_id": "w2", "blueprint_key": "sys-3", "name": "S3"},
        ],
    )
    connection.execute(
        _table("runs").insert(),
        [
            {"id": "run-1", "workspace_id": "w1", "system_id": "sys-1"},
            {"id": "run-2", "workspace_id": "w1", "system_id": "sys-2"},
            {"id": "run-3", "workspace_id": "w2", "system_id": "sys-3"},
            # Legacy Run rows are not tenant-bound to System at the database
            # layer. This row isolates the stronger ValueScenario System FK.
            {"id": "run-cross", "workspace_id": "w2", "system_id": "sys-1"},
        ],
    )
    connection.execute(
        _table("control_policies").insert(),
        [
            {"id": "policy-1", "workspace_id": "w1", "scope": "system", "target_id": "sys-1"},
            {"id": "policy-2", "workspace_id": "w1", "scope": "system", "target_id": "sys-2"},
            {"id": "policy-3", "workspace_id": "w2", "scope": "system", "target_id": "sys-3"},
        ],
    )
    operation_rows = [
        ("op-scenario-1", "w1", "scenario.create"),
        ("op-scenario-2", "w1", "scenario.create"),
        ("op-simulation-1", "w1", "simulate"),
        ("op-simulation-1b", "w1", "simulate"),
        ("op-simulation-2", "w1", "simulate"),
        ("op-action-1", "w1", "act"),
        ("op-action-2", "w1", "act"),
        ("op-measure-1", "w1", "measure"),
        ("op-w2-scenario", "w2", "scenario.create"),
        ("op-w2-action", "w2", "act"),
        ("op-w2-measure", "w2", "measure"),
    ]
    connection.execute(
        _table("value_loop_operations").insert(),
        [
            {
                "id": operation_id,
                "workspace_id": workspace_id,
                "idempotency_key": operation_id,
                "request_sha256": "0" * 64,
                "operation": operation,
            }
            for operation_id, workspace_id, operation in operation_rows
        ],
    )
    connection.execute(
        _table("value_scenarios").insert(),
        [
            {
                "id": "scenario-1",
                "workspace_id": "w1",
                "system_id": "sys-1",
                "source_run_id": "run-1",
                "operation_id": "op-scenario-1",
                "status": "acted",
                "objective": "Objective 1",
                "baseline_outcome": {"value": 1},
            },
            {
                "id": "scenario-2",
                "workspace_id": "w1",
                "system_id": "sys-1",
                "source_run_id": "run-1",
                "operation_id": "op-scenario-2",
                "status": "simulated",
                "objective": "Objective 2",
                "baseline_outcome": {"value": 1},
            },
        ],
    )
    connection.execute(
        _table("value_simulations").insert(),
        [
            {
                "id": simulation_id,
                "workspace_id": "w1",
                "system_id": "sys-1",
                "scenario_id": scenario_id,
                "operation_id": operation_id,
                "model": "deterministic-v1",
                "assumptions": {},
                "projected_outcome": {"value": 2},
                "recommended_action": {"type": "policy_patch"},
                "provenance": {"source": "test"},
                "confidence": 0.8,
            }
            for simulation_id, scenario_id, operation_id in (
                ("simulation-1", "scenario-1", "op-simulation-1"),
                ("simulation-1b", "scenario-1", "op-simulation-1b"),
                ("simulation-2", "scenario-2", "op-simulation-2"),
            )
        ],
    )
    connection.execute(
        _table("value_scenarios")
        .update()
        .where(_table("value_scenarios").c.id == "scenario-1")
        .values(approved_simulation_id="simulation-1")
    )
    connection.execute(
        _table("value_action_executions")
        .insert()
        .values(
            id="action-1",
            workspace_id="w1",
            system_id="sys-1",
            scenario_id="scenario-1",
            simulation_id="simulation-1",
            control_policy_id="policy-1",
            operation_id="op-action-1",
            actuator="control_policy.patch",
            request_sha256="1" * 64,
            patch={},
            before_state={},
            after_state={},
            executed_by="integrity-test",
        )
    )


def test_coherent_value_lineage_commits_with_foreign_keys_enabled(
    integrity_engine: sa.Engine,
) -> None:
    with integrity_engine.begin() as connection:
        _seed_value_lineage(connection)

    with integrity_engine.connect() as connection:
        assert (
            connection.execute(
                sa.select(sa.func.count()).select_from(_table("value_action_executions"))
            ).scalar_one()
            == 1
        )


@pytest.mark.parametrize(
    ("workspace_id", "system_id", "source_run_id", "operation_id"),
    [
        ("w2", "sys-1", "run-cross", "op-w2-scenario"),
        ("w1", "sys-1", "run-2", "op-action-2"),
        ("w1", "sys-1", "run-1", "op-w2-scenario"),
    ],
    ids=("system-tenant", "source-run-system", "operation-tenant"),
)
def test_value_scenario_rejects_incoherent_lineage(
    integrity_engine: sa.Engine,
    workspace_id: str,
    system_id: str,
    source_run_id: str,
    operation_id: str,
) -> None:
    with pytest.raises(IntegrityError), integrity_engine.begin() as connection:
        _seed_value_lineage(connection)
        connection.execute(
            _table("value_scenarios")
            .insert()
            .values(
                id="scenario-invalid",
                workspace_id=workspace_id,
                system_id=system_id,
                source_run_id=source_run_id,
                operation_id=operation_id,
                objective="Must fail",
                baseline_outcome={},
            )
        )


def test_simulation_and_approved_simulation_are_scenario_bound(
    integrity_engine: sa.Engine,
) -> None:
    with pytest.raises(IntegrityError), integrity_engine.begin() as connection:
        _seed_value_lineage(connection)
        connection.execute(
            _table("value_scenarios")
            .update()
            .where(_table("value_scenarios").c.id == "scenario-2")
            .values(approved_simulation_id="simulation-1")
        )

    with pytest.raises(IntegrityError), integrity_engine.begin() as connection:
        _seed_value_lineage(connection)
        connection.execute(
            _table("value_simulations")
            .insert()
            .values(
                id="simulation-invalid",
                workspace_id="w1",
                system_id="sys-2",
                scenario_id="scenario-1",
                operation_id="op-action-2",
                model="deterministic-v1",
                assumptions={},
                projected_outcome={},
                recommended_action={},
                provenance={},
                confidence=0.5,
            )
        )


@pytest.mark.parametrize(
    ("simulation_id", "control_policy_id", "operation_id"),
    [
        ("simulation-1", "policy-1", "op-action-2"),
        ("simulation-2", "policy-2", "op-action-2"),
        ("simulation-2", "policy-1", "op-w2-action"),
    ],
    ids=("simulation-scenario", "control-policy-system", "operation-tenant"),
)
def test_action_rejects_incoherent_lineage(
    integrity_engine: sa.Engine,
    simulation_id: str,
    control_policy_id: str,
    operation_id: str,
) -> None:
    with pytest.raises(IntegrityError), integrity_engine.begin() as connection:
        _seed_value_lineage(connection)
        connection.execute(
            _table("value_action_executions")
            .insert()
            .values(
                id="action-invalid",
                workspace_id="w1",
                system_id="sys-1",
                scenario_id="scenario-2",
                simulation_id=simulation_id,
                control_policy_id=control_policy_id,
                operation_id=operation_id,
                actuator="control_policy.patch",
                request_sha256="2" * 64,
                patch={},
                before_state={},
                after_state={},
                executed_by="integrity-test",
            )
        )


@pytest.mark.parametrize(
    ("simulation_id", "source_run_id", "operation_id"),
    [
        ("simulation-1b", "run-1", "op-measure-1"),
        ("simulation-1", "run-2", "op-measure-1"),
        ("simulation-1", "run-1", "op-w2-measure"),
    ],
    ids=("action-simulation", "source-run-system", "operation-tenant"),
)
def test_measurement_rejects_incoherent_lineage(
    integrity_engine: sa.Engine,
    simulation_id: str,
    source_run_id: str,
    operation_id: str,
) -> None:
    with pytest.raises(IntegrityError), integrity_engine.begin() as connection:
        _seed_value_lineage(connection)
        connection.execute(
            _table("value_measurements")
            .insert()
            .values(
                id="measurement-invalid",
                workspace_id="w1",
                system_id="sys-1",
                scenario_id="scenario-1",
                action_execution_id="action-1",
                simulation_id=simulation_id,
                source_run_id=source_run_id,
                operation_id=operation_id,
                status="measured",
                baseline_outcome={},
                observed_outcome={},
                assumption_verdict="not_evaluable",
                assumption_evaluation={},
            )
        )


def _seed_workspace_apps(connection: sa.Connection) -> None:
    _seed_workspaces(connection)
    connection.execute(
        _table("workspace_app_installations").insert(),
        [
            {"id": "install-a", "workspace_id": "w1", "app_id": "app-a", "updated_by": "test"},
            {"id": "install-b", "workspace_id": "w1", "app_id": "app-b", "updated_by": "test"},
        ],
    )
    connection.execute(
        _table("workspace_app_operations")
        .insert()
        .values(
            id="app-operation-a",
            workspace_id="w1",
            installation_id="install-a",
            app_id="app-a",
            idempotency_key="app-operation-a",
            request_sha256="3" * 64,
            operation="install",
            manifest_digest="4" * 64,
            plan_sha256="5" * 64,
            steps_sha256="6" * 64,
            before_state={},
            after_state={},
            actor="integrity-test",
        )
    )


def test_coherent_workspace_app_lineage_commits_with_foreign_keys_enabled(
    integrity_engine: sa.Engine,
) -> None:
    with integrity_engine.begin() as connection:
        _seed_workspace_apps(connection)

    with integrity_engine.connect() as connection:
        assert (
            connection.execute(
                sa.select(sa.func.count()).select_from(_table("workspace_app_operations"))
            ).scalar_one()
            == 1
        )


def test_workspace_app_operation_is_bound_to_installation_app(
    integrity_engine: sa.Engine,
) -> None:
    with pytest.raises(IntegrityError), integrity_engine.begin() as connection:
        _seed_workspace_apps(connection)
        connection.execute(
            _table("workspace_app_operations")
            .insert()
            .values(
                id="app-operation-invalid",
                workspace_id="w1",
                installation_id="install-a",
                app_id="app-b",
                idempotency_key="app-operation-invalid",
                request_sha256="7" * 64,
                operation="install",
                manifest_digest="8" * 64,
                plan_sha256="9" * 64,
                steps_sha256="a" * 64,
                before_state={},
                after_state={},
                actor="integrity-test",
            )
        )


def test_workspace_app_receipt_is_bound_to_exact_operation_lineage(
    integrity_engine: sa.Engine,
) -> None:
    with pytest.raises(IntegrityError), integrity_engine.begin() as connection:
        _seed_workspace_apps(connection)
        connection.execute(
            _table("workspace_app_lifecycle_step_receipts")
            .insert()
            .values(
                id="receipt-invalid",
                workspace_id="w1",
                operation_id="app-operation-a",
                installation_id="install-b",
                app_id="app-b",
                position=0,
                manifest_role="target",
                manifest_digest="b" * 64,
                step_id="step-1",
                step_sha256="c" * 64,
                phase="install",
                executor="database",
                outcome="executed",
                reversibility="transactional",
            )
        )


@pytest.mark.parametrize("app_key", ("bad_key", "-leading", "bad/key", "bad@app"))
def test_sqlite_app_key_constraint_rejects_non_registry_charset(
    integrity_engine: sa.Engine,
    app_key: str,
) -> None:
    with pytest.raises(IntegrityError), integrity_engine.begin() as connection:
        _seed_workspaces(connection)
        connection.execute(_table("users").insert().values(id="user-1", username="user-1"))
        member_id = connection.execute(
            _table("workspace_members")
            .insert()
            .values(user_id="user-1", workspace_id="w1")
            .returning(_table("workspace_members").c.id)
        ).scalar_one()
        connection.execute(
            _table("workspace_member_app_entitlements")
            .insert()
            .values(
                workspace_member_id=member_id,
                app_key=app_key,
            )
        )


@pytest.mark.parametrize("table_name", ("systems", "contexts"))
def test_global_blueprint_key_is_unique_when_workspace_is_null(
    integrity_engine: sa.Engine,
    table_name: str,
) -> None:
    with pytest.raises(IntegrityError), integrity_engine.begin() as connection:
        table = _table(table_name)
        connection.execute(
            table.insert().values(id=f"{table_name}-1", blueprint_key="global-key", name="First")
        )
        connection.execute(
            table.insert().values(id=f"{table_name}-2", blueprint_key="global-key", name="Second")
        )


def test_app_key_check_compiles_as_one_dialect_specific_constraint() -> None:
    table = WorkspaceMemberAppEntitlement.__table__
    check_constraints = [
        constraint
        for constraint in table.constraints
        if constraint.name == "ck_workspace_member_app_entitlements_app_key"
    ]
    assert len(check_constraints) == 1

    sqlite_ddl = str(CreateTable(table).compile(dialect=sqlite.dialect()))
    postgresql_ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))

    assert sqlite_ddl.count("ck_workspace_member_app_entitlements_app_key") == 1
    assert "NOT GLOB '*[^a-z0-9.-]*'" in sqlite_ddl
    assert " GLOB '[a-z0-9]'" in sqlite_ddl
    assert postgresql_ddl.count("ck_workspace_member_app_entitlements_app_key") == 1
    assert "app_key ~ '^[a-z0-9][a-z0-9.-]{0,79}$'" in postgresql_ddl
    assert "GLOB" not in postgresql_ddl

    # No bare '%' in DDL that psycopg2 will be handed. It interpolates the
    # statement it is given, so one LIKE wildcard in a CHECK constraint fails
    # `create_all` against Postgres with "immutabledict is not a sequence" — an
    # error that names neither this table nor this column, and which takes the
    # entire schema bootstrap down with it.
    assert "%" not in postgresql_ddl


def _constraint_columns(constraint: sa.Constraint) -> tuple[str, ...]:
    return tuple(column.name for column in constraint.columns)


def test_candidate_keys_and_composite_foreign_keys_match_schema_contract() -> None:
    expected_unique_keys = {
        "systems": ("uq_systems_workspace_id", ("workspace_id", "id")),
        "runs": ("uq_runs_workspace_system_id", ("workspace_id", "system_id", "id")),
        "control_policies": (
            "uq_control_policies_ws_target_id",
            ("workspace_id", "target_id", "id"),
        ),
        "value_loop_operations": (
            "uq_value_loop_operations_ws_id",
            ("workspace_id", "id"),
        ),
        "value_scenarios": (
            "uq_value_scenarios_ws_system_id",
            ("workspace_id", "system_id", "id"),
        ),
        "value_simulations": (
            "uq_value_simulations_lineage_id",
            ("workspace_id", "system_id", "scenario_id", "id"),
        ),
        "value_action_executions": (
            "uq_value_actions_lineage_id",
            ("workspace_id", "system_id", "scenario_id", "simulation_id", "id"),
        ),
        "workspace_app_installations": (
            "uq_workspace_app_installations_lineage",
            ("workspace_id", "app_id", "id"),
        ),
        "workspace_app_operations": (
            "uq_workspace_app_operations_lineage",
            ("workspace_id", "app_id", "installation_id", "id"),
        ),
    }
    for table_name, (constraint_name, columns) in expected_unique_keys.items():
        constraint = next(
            item
            for item in _table(table_name).constraints
            if isinstance(item, sa.UniqueConstraint) and item.name == constraint_name
        )
        assert _constraint_columns(constraint) == columns

    expected_foreign_keys = {
        "fk_value_scenarios_system_tenant": ("workspace_id", "system_id"),
        "fk_value_scenarios_source_run_lineage": (
            "workspace_id",
            "system_id",
            "source_run_id",
        ),
        "fk_value_scenarios_operation_tenant": ("workspace_id", "operation_id"),
        "fk_value_scenarios_approval_operation_tenant": (
            "workspace_id",
            "approval_operation_id",
        ),
        "fk_value_scenarios_approved_simulation_lineage": (
            "workspace_id",
            "system_id",
            "id",
            "approved_simulation_id",
        ),
        "fk_value_simulations_scenario_lineage": (
            "workspace_id",
            "system_id",
            "scenario_id",
        ),
        "fk_value_simulations_operation_tenant": ("workspace_id", "operation_id"),
        "fk_value_action_executions_scenario_lineage": (
            "workspace_id",
            "system_id",
            "scenario_id",
        ),
        "fk_value_action_executions_simulation_lineage": (
            "workspace_id",
            "system_id",
            "scenario_id",
            "simulation_id",
        ),
        "fk_value_action_executions_control_policy_lineage": (
            "workspace_id",
            "system_id",
            "control_policy_id",
        ),
        "fk_value_action_executions_operation_tenant": (
            "workspace_id",
            "operation_id",
        ),
        "fk_value_measurements_scenario_lineage": (
            "workspace_id",
            "system_id",
            "scenario_id",
        ),
        "fk_value_measurements_simulation_lineage": (
            "workspace_id",
            "system_id",
            "scenario_id",
            "simulation_id",
        ),
        "fk_value_measurements_action_lineage": (
            "workspace_id",
            "system_id",
            "scenario_id",
            "simulation_id",
            "action_execution_id",
        ),
        "fk_value_measurements_source_run_lineage": (
            "workspace_id",
            "system_id",
            "source_run_id",
        ),
        "fk_value_measurements_operation_tenant": ("workspace_id", "operation_id"),
        "fk_workspace_app_operations_installation_lineage": (
            "workspace_id",
            "app_id",
            "installation_id",
        ),
        "fk_workspace_app_step_receipts_operation_lineage": (
            "workspace_id",
            "app_id",
            "installation_id",
            "operation_id",
        ),
    }
    foreign_keys = {
        constraint.name: constraint
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, sa.ForeignKeyConstraint)
    }
    for constraint_name, columns in expected_foreign_keys.items():
        assert _constraint_columns(foreign_keys[constraint_name]) == columns

    approved_fk = foreign_keys["fk_value_scenarios_approved_simulation_lineage"]
    assert approved_fk.deferrable is True
    assert approved_fk.initially == "DEFERRED"
    assert approved_fk.use_alter is False


def test_redundant_indexes_are_not_in_orm_metadata() -> None:
    assert "ix_system_versions_system_version" not in {
        index.name for index in SystemVersion.__table__.indexes
    }
    assert "ix_decisions_scenario_id" not in {index.name for index in Decision.__table__.indexes}
    assert Decision.__table__.c.scenario_id.index is not True
    assert {index.name for index in System.__table__.indexes} >= {"uq_systems_global_blueprint_key"}
    assert {index.name for index in Context.__table__.indexes} >= {
        "uq_contexts_global_blueprint_key"
    }
