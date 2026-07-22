"""Authoritative value-loop persistence.

The four public records deliberately keep simulations, actuations and measured
outcomes in different tables.  ``ValueLoopOperation`` is an internal command
receipt: its workspace-scoped unique key makes every transition idempotent
without conflating business evidence with transport retries.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)

from app.db.base import Base


def _enum_check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class ValueLoopOperation(Base):
    """Internal, content-addressed receipt for one value-loop command."""

    __tablename__ = "value_loop_operations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    idempotency_key = Column(String(160), nullable=False)
    request_sha256 = Column(String(64), nullable=False)
    operation = Column(String(40), nullable=False)
    result_type = Column(String(40), nullable=True)
    result_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_value_loop_operations_ws_id",
        ),
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_value_loop_operations_workspace_key",
        ),
        CheckConstraint(
            _enum_check(
                "operation",
                ("scenario.create", "simulate", "approve", "act", "measure"),
            ),
            name="ck_value_loop_operations_operation",
        ),
    )


class ValueScenario(Base):
    """System-scoped value hypothesis anchored to a real baseline Run."""

    __tablename__ = "value_scenarios"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    system_id = Column(
        String(36),
        ForeignKey("systems.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_run_id = Column(
        String(36),
        ForeignKey("runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    operation_id = Column(
        String(36),
        ForeignKey("value_loop_operations.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )

    status = Column(String(32), nullable=False, default="decision_proposed", index=True)
    objective = Column(Text, nullable=False)
    baseline_outcome = Column(JSON, nullable=False)

    approved_simulation_id = Column(String(36), nullable=True, index=True)
    # Approval pins the complete canonical simulation contract outside the
    # mutable ValueSimulation row.  These columns remain nullable only so
    # pre-migration approvals are represented honestly; actuation refuses an
    # approved scenario that has no pin.
    approved_simulation_content_sha256 = Column(String(64), nullable=True)
    approved_simulation_snapshot = Column(JSON, nullable=True)
    approval_operation_id = Column(
        String(36),
        ForeignKey("value_loop_operations.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    approved_by = Column(String(255), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    acted_at = Column(DateTime, nullable=True)
    measured_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "system_id",
            "id",
            name="uq_value_scenarios_ws_system_id",
        ),
        # Decision lineage uses the human-readable identity order
        # workspace -> scenario -> System.  Keep an exact candidate key for
        # that composite reference even though ``id`` is also the primary key.
        UniqueConstraint(
            "workspace_id",
            "id",
            "system_id",
            name="uq_value_scenarios_ws_id_system",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "system_id"],
            ["systems.workspace_id", "systems.id"],
            name="fk_value_scenarios_system_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "system_id", "source_run_id"],
            ["runs.workspace_id", "runs.system_id", "runs.id"],
            name="fk_value_scenarios_source_run_lineage",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "operation_id"],
            ["value_loop_operations.workspace_id", "value_loop_operations.id"],
            name="fk_value_scenarios_operation_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "approval_operation_id"],
            ["value_loop_operations.workspace_id", "value_loop_operations.id"],
            name="fk_value_scenarios_approval_operation_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "system_id", "id", "approved_simulation_id"],
            [
                "value_simulations.workspace_id",
                "value_simulations.system_id",
                "value_simulations.scenario_id",
                "value_simulations.id",
            ],
            name="fk_value_scenarios_approved_simulation_lineage",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            _enum_check(
                "status",
                ("decision_proposed", "simulated", "approved", "acted", "measured"),
            ),
            name="ck_value_scenarios_status",
        ),
    )


class ValueSimulation(Base):
    """Forecast artifact; it is never a measured outcome."""

    __tablename__ = "value_simulations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    system_id = Column(
        String(36),
        ForeignKey("systems.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scenario_id = Column(
        String(36),
        ForeignKey("value_scenarios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    operation_id = Column(
        String(36),
        ForeignKey("value_loop_operations.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )

    status = Column(String(20), nullable=False, default="available")
    model = Column(String(200), nullable=False)
    assumptions = Column(JSON, nullable=False)
    projected_outcome = Column(JSON, nullable=False)
    recommended_action = Column(JSON, nullable=False)
    provenance = Column(JSON, nullable=False)
    confidence = Column(Float, nullable=False)
    generated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "system_id",
            "scenario_id",
            "id",
            name="uq_value_simulations_lineage_id",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "system_id", "scenario_id"],
            [
                "value_scenarios.workspace_id",
                "value_scenarios.system_id",
                "value_scenarios.id",
            ],
            name="fk_value_simulations_scenario_lineage",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "operation_id"],
            ["value_loop_operations.workspace_id", "value_loop_operations.id"],
            name="fk_value_simulations_operation_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            _enum_check("status", ("available",)),
            name="ck_value_simulations_status",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_value_simulations_confidence",
        ),
    )


class ValueActionExecution(Base):
    """One real, idempotent actuator execution for an approved scenario."""

    __tablename__ = "value_action_executions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    system_id = Column(
        String(36),
        ForeignKey("systems.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scenario_id = Column(
        String(36),
        ForeignKey("value_scenarios.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    simulation_id = Column(
        String(36),
        ForeignKey("value_simulations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    control_policy_id = Column(
        String(36),
        ForeignKey("control_policies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    operation_id = Column(
        String(36),
        ForeignKey("value_loop_operations.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )

    actuator = Column(String(160), nullable=False)
    status = Column(String(20), nullable=False, default="succeeded")
    request_sha256 = Column(String(64), nullable=False)
    patch = Column(JSON, nullable=False)
    before_state = Column(JSON, nullable=False)
    after_state = Column(JSON, nullable=False)
    executed_by = Column(String(255), nullable=False)
    executed_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "system_id",
            "scenario_id",
            "simulation_id",
            "id",
            name="uq_value_actions_lineage_id",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "system_id", "scenario_id"],
            [
                "value_scenarios.workspace_id",
                "value_scenarios.system_id",
                "value_scenarios.id",
            ],
            name="fk_value_action_executions_scenario_lineage",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "system_id", "scenario_id", "simulation_id"],
            [
                "value_simulations.workspace_id",
                "value_simulations.system_id",
                "value_simulations.scenario_id",
                "value_simulations.id",
            ],
            name="fk_value_action_executions_simulation_lineage",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "system_id", "control_policy_id"],
            [
                "control_policies.workspace_id",
                "control_policies.target_id",
                "control_policies.id",
            ],
            name="fk_value_action_executions_control_policy_lineage",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "operation_id"],
            ["value_loop_operations.workspace_id", "value_loop_operations.id"],
            name="fk_value_action_executions_operation_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            _enum_check("status", ("succeeded",)),
            name="ck_value_action_executions_status",
        ),
    )


class ValueMeasurement(Base):
    """Observed post-action Outcome or an explicit absence of evidence."""

    __tablename__ = "value_measurements"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    system_id = Column(
        String(36),
        ForeignKey("systems.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scenario_id = Column(
        String(36),
        ForeignKey("value_scenarios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_execution_id = Column(
        String(36),
        ForeignKey("value_action_executions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    simulation_id = Column(
        String(36),
        ForeignKey("value_simulations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_run_id = Column(
        String(36),
        ForeignKey("runs.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    operation_id = Column(
        String(36),
        ForeignKey("value_loop_operations.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )

    status = Column(String(24), nullable=False)
    reason = Column(String(100), nullable=True)
    baseline_outcome = Column(JSON, nullable=False)
    observed_outcome = Column(JSON, nullable=True)
    delta = Column(JSON, nullable=True)
    forecast_delta = Column(JSON, nullable=True)
    assumption_verdict = Column(String(32), nullable=False)
    assumption_evaluation = Column(JSON, nullable=False)
    measured_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "system_id", "scenario_id"],
            [
                "value_scenarios.workspace_id",
                "value_scenarios.system_id",
                "value_scenarios.id",
            ],
            name="fk_value_measurements_scenario_lineage",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "system_id", "scenario_id", "simulation_id"],
            [
                "value_simulations.workspace_id",
                "value_simulations.system_id",
                "value_simulations.scenario_id",
                "value_simulations.id",
            ],
            name="fk_value_measurements_simulation_lineage",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "workspace_id",
                "system_id",
                "scenario_id",
                "simulation_id",
                "action_execution_id",
            ],
            [
                "value_action_executions.workspace_id",
                "value_action_executions.system_id",
                "value_action_executions.scenario_id",
                "value_action_executions.simulation_id",
                "value_action_executions.id",
            ],
            name="fk_value_measurements_action_lineage",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "system_id", "source_run_id"],
            ["runs.workspace_id", "runs.system_id", "runs.id"],
            name="fk_value_measurements_source_run_lineage",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "operation_id"],
            ["value_loop_operations.workspace_id", "value_loop_operations.id"],
            name="fk_value_measurements_operation_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            _enum_check("status", ("measured", "not_measured")),
            name="ck_value_measurements_status",
        ),
        CheckConstraint(
            _enum_check(
                "assumption_verdict",
                (
                    "confirmed",
                    "partially_confirmed",
                    "not_confirmed",
                    "not_evaluable",
                ),
            ),
            name="ck_value_measurements_assumption_verdict",
        ),
    )
