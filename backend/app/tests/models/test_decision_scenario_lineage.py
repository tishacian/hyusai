"""Database attacks against the authoritative Decision -> scenario edge."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

import app.models  # noqa: F401 -- register the complete canonical metadata
from app.db.base import Base
from app.models.decision import Decision
from app.models.value_loop import ValueScenario


@pytest.fixture()
def lineage_engine() -> Iterator[sa.Engine]:
    engine = sa.create_engine("sqlite:///:memory:")

    @sa.event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _table(name: str) -> sa.Table:
    return Base.metadata.tables[name]


def _seed_scenarios(connection: sa.Connection) -> None:
    connection.execute(
        _table("workspaces").insert(),
        [
            {"id": "w1", "name": "Workspace 1", "slug": "workspace-1"},
            {"id": "w2", "name": "Workspace 2", "slug": "workspace-2"},
        ],
    )
    connection.execute(
        _table("systems").insert(),
        [
            {
                "id": "sys-1",
                "workspace_id": "w1",
                "blueprint_key": "sys-1",
                "name": "System 1",
            },
            {
                "id": "sys-2",
                "workspace_id": "w1",
                "blueprint_key": "sys-2",
                "name": "System 2",
            },
            {
                "id": "sys-3",
                "workspace_id": "w2",
                "blueprint_key": "sys-3",
                "name": "System 3",
            },
        ],
    )
    connection.execute(
        _table("runs").insert(),
        [
            {"id": "run-1", "workspace_id": "w1", "system_id": "sys-1"},
            {"id": "run-2", "workspace_id": "w1", "system_id": "sys-2"},
            {"id": "run-3", "workspace_id": "w2", "system_id": "sys-3"},
        ],
    )
    operation_rows = (
        ("op-1", "w1"),
        ("op-2", "w1"),
        ("op-3", "w2"),
    )
    connection.execute(
        _table("value_loop_operations").insert(),
        [
            {
                "id": operation_id,
                "workspace_id": workspace_id,
                "idempotency_key": operation_id,
                "request_sha256": "0" * 64,
                "operation": "scenario.create",
            }
            for operation_id, workspace_id in operation_rows
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
                "operation_id": "op-1",
                "objective": "Scenario 1",
                "baseline_outcome": {},
            },
            {
                "id": "scenario-2",
                "workspace_id": "w1",
                "system_id": "sys-2",
                "source_run_id": "run-2",
                "operation_id": "op-2",
                "objective": "Scenario 2",
                "baseline_outcome": {},
            },
            {
                "id": "scenario-3",
                "workspace_id": "w2",
                "system_id": "sys-3",
                "source_run_id": "run-3",
                "operation_id": "op-3",
                "objective": "Scenario 3",
                "baseline_outcome": {},
            },
        ],
    )


def _decision_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "id": "decision-1",
        "workspace_id": "w1",
        "scenario_id": "scenario-1",
        "scope": "system",
        "target_id": "sys-1",
        "kind": "value_loop",
        "title": "Authoritative decision",
    }
    values.update(overrides)
    return values


def _constraint_columns(constraint: sa.Constraint) -> tuple[str, ...]:
    return tuple(column.name for column in constraint.columns)


def test_orm_declares_exact_decision_scenario_lineage_contract() -> None:
    foreign_key = next(
        constraint
        for constraint in Decision.__table__.constraints
        if isinstance(constraint, sa.ForeignKeyConstraint)
        and constraint.name == "fk_decisions_scenario_lineage"
    )
    assert _constraint_columns(foreign_key) == (
        "workspace_id",
        "scenario_id",
        "target_id",
    )
    assert tuple(element.target_fullname for element in foreign_key.elements) == (
        "value_scenarios.workspace_id",
        "value_scenarios.id",
        "value_scenarios.system_id",
    )
    assert foreign_key.ondelete == "RESTRICT"
    assert not any(
        isinstance(constraint, sa.ForeignKeyConstraint)
        and _constraint_columns(constraint) == ("scenario_id",)
        for constraint in Decision.__table__.constraints
    )

    check_names = {
        constraint.name
        for constraint in Decision.__table__.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }
    assert "ck_decisions_scenario_lineage_complete" in check_names

    candidate = next(
        constraint
        for constraint in ValueScenario.__table__.constraints
        if isinstance(constraint, sa.UniqueConstraint)
        and constraint.name == "uq_value_scenarios_ws_id_system"
    )
    assert _constraint_columns(candidate) == ("workspace_id", "id", "system_id")


def test_coherent_and_legacy_decisions_remain_valid(lineage_engine: sa.Engine) -> None:
    with lineage_engine.begin() as connection:
        _seed_scenarios(connection)
        connection.execute(_table("decisions").insert(), _decision_values())
        connection.execute(
            _table("decisions").insert(),
            _decision_values(
                id="legacy-decision",
                scenario_id=None,
                target_id="unbound-target",
                kind="legacy",
            ),
        )


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
def test_scenario_decision_transplant_attacks_are_rejected(
    lineage_engine: sa.Engine,
    workspace_id: str | None,
    target_id: str | None,
) -> None:
    with pytest.raises(IntegrityError), lineage_engine.begin() as connection:
        _seed_scenarios(connection)
        connection.execute(
            _table("decisions").insert(),
            _decision_values(workspace_id=workspace_id, target_id=target_id),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("workspace_id", "w2"), ("target_id", "sys-2")],
    ids=("tenant", "system"),
)
def test_existing_scenario_decision_cannot_be_transplanted(
    lineage_engine: sa.Engine,
    field: str,
    value: str,
) -> None:
    with pytest.raises(IntegrityError), lineage_engine.begin() as connection:
        _seed_scenarios(connection)
        connection.execute(_table("decisions").insert(), _decision_values())
        connection.execute(
            _table("decisions")
            .update()
            .where(_table("decisions").c.id == "decision-1")
            .values(**{field: value})
        )


def test_scenario_with_authoritative_decision_cannot_be_deleted(
    lineage_engine: sa.Engine,
) -> None:
    with pytest.raises(IntegrityError), lineage_engine.begin() as connection:
        _seed_scenarios(connection)
        connection.execute(_table("decisions").insert(), _decision_values())
        connection.execute(
            _table("value_scenarios")
            .delete()
            .where(_table("value_scenarios").c.id == "scenario-1")
        )
