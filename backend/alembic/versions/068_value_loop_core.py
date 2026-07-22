"""Add the authoritative Outcome -> Decision -> Act -> Measure ledger.

Revision ID: 068_value_loop_core
Revises: 067_system_version_uniqueness

All changes are additive.  Existing Decisions remain valid because their
scenario link is nullable; no historical Run or Decision is reinterpreted.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "068_value_loop_core"
down_revision = "067_system_version_uniqueness"
branch_labels = None
depends_on = None

VALUE_LOOP_TABLES = (
    "value_measurements",
    "value_action_executions",
    "value_simulations",
    "value_scenarios",
    "value_loop_operations",
)


def _enum_check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _assert_downgrade_safe() -> None:
    """Refuse to erase any authoritative Lot-8 evidence."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    populated: dict[str, int] = {}
    for table_name in VALUE_LOOP_TABLES:
        if table_name not in tables:
            continue
        count = int(
            bind.execute(
                sa.text(f'SELECT COUNT(*) FROM "{table_name}"')
            ).scalar_one()
        )
        if count:
            populated[table_name] = count

    if "decisions" in tables and "scenario_id" in {
        column["name"] for column in inspector.get_columns("decisions")
    }:
        linked = int(
            bind.execute(
                sa.text(
                    'SELECT COUNT(*) FROM "decisions" '
                    'WHERE "scenario_id" IS NOT NULL'
                )
            ).scalar_one()
        )
        if linked:
            populated["decisions.scenario_id"] = linked

    if populated:
        details = ", ".join(
            f"{name}={count}" for name, count in sorted(populated.items())
        )
        raise RuntimeError(
            "refusing destructive downgrade of authoritative value-loop "
            f"evidence ({details})"
        )


def upgrade() -> None:
    op.create_table(
        "value_loop_operations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=40), nullable=False),
        sa.Column("result_type", sa.String(length=40), nullable=True),
        sa.Column("result_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            _enum_check(
                "operation",
                ("scenario.create", "simulate", "approve", "act", "measure"),
            ),
            name="ck_value_loop_operations_operation",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_value_loop_operations_workspace_key",
        ),
    )
    op.create_index(
        "ix_value_loop_operations_workspace_id",
        "value_loop_operations",
        ["workspace_id"],
        unique=False,
    )

    op.create_table(
        "value_scenarios",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("system_id", sa.String(length=36), nullable=False),
        sa.Column("source_run_id", sa.String(length=36), nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("baseline_outcome", sa.JSON(), nullable=False),
        sa.Column("approved_simulation_id", sa.String(length=36), nullable=True),
        sa.Column("approval_operation_id", sa.String(length=36), nullable=True),
        sa.Column("approved_by", sa.String(length=255), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("acted_at", sa.DateTime(), nullable=True),
        sa.Column("measured_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            _enum_check(
                "status",
                ("decision_proposed", "simulated", "approved", "acted", "measured"),
            ),
            name="ck_value_scenarios_status",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"], ["value_loop_operations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["approval_operation_id"],
            ["value_loop_operations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["source_run_id"], ["runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operation_id"),
        sa.UniqueConstraint("approval_operation_id"),
    )
    for column in (
        "workspace_id",
        "system_id",
        "source_run_id",
        "status",
        "approved_simulation_id",
    ):
        op.create_index(
            f"ix_value_scenarios_{column}",
            "value_scenarios",
            [column],
            unique=False,
        )

    op.create_table(
        "value_simulations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("system_id", sa.String(length=36), nullable=False),
        sa.Column("scenario_id", sa.String(length=36), nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("assumptions", sa.JSON(), nullable=False),
        sa.Column("projected_outcome", sa.JSON(), nullable=False),
        sa.Column("recommended_action", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            _enum_check("status", ("available",)),
            name="ck_value_simulations_status",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_value_simulations_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"], ["value_loop_operations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["scenario_id"], ["value_scenarios.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operation_id"),
    )
    for column in ("workspace_id", "system_id", "scenario_id"):
        op.create_index(
            f"ix_value_simulations_{column}",
            "value_simulations",
            [column],
            unique=False,
        )

    op.create_table(
        "value_action_executions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("system_id", sa.String(length=36), nullable=False),
        sa.Column("scenario_id", sa.String(length=36), nullable=False),
        sa.Column("simulation_id", sa.String(length=36), nullable=False),
        sa.Column("control_policy_id", sa.String(length=36), nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("actuator", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("patch", sa.JSON(), nullable=False),
        sa.Column("before_state", sa.JSON(), nullable=False),
        sa.Column("after_state", sa.JSON(), nullable=False),
        sa.Column("executed_by", sa.String(length=255), nullable=False),
        sa.Column("executed_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            _enum_check("status", ("succeeded",)),
            name="ck_value_action_executions_status",
        ),
        sa.ForeignKeyConstraint(
            ["control_policy_id"], ["control_policies.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"], ["value_loop_operations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["scenario_id"], ["value_scenarios.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["simulation_id"], ["value_simulations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operation_id"),
        sa.UniqueConstraint("scenario_id"),
    )
    for column in (
        "workspace_id",
        "system_id",
        "simulation_id",
        "control_policy_id",
        "executed_at",
    ):
        op.create_index(
            f"ix_value_action_executions_{column}",
            "value_action_executions",
            [column],
            unique=False,
        )

    op.create_table(
        "value_measurements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("system_id", sa.String(length=36), nullable=False),
        sa.Column("scenario_id", sa.String(length=36), nullable=False),
        sa.Column("action_execution_id", sa.String(length=36), nullable=False),
        sa.Column("source_run_id", sa.String(length=36), nullable=True),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.String(length=100), nullable=True),
        sa.Column("baseline_outcome", sa.JSON(), nullable=False),
        sa.Column("observed_outcome", sa.JSON(), nullable=True),
        sa.Column("delta", sa.JSON(), nullable=True),
        sa.Column("measured_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            _enum_check("status", ("measured", "not_measured")),
            name="ck_value_measurements_status",
        ),
        sa.ForeignKeyConstraint(
            ["action_execution_id"],
            ["value_action_executions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"], ["value_loop_operations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["scenario_id"], ["value_scenarios.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_run_id"], ["runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operation_id"),
    )
    for column in (
        "workspace_id",
        "system_id",
        "scenario_id",
        "action_execution_id",
        "source_run_id",
    ):
        op.create_index(
            f"ix_value_measurements_{column}",
            "value_measurements",
            [column],
            unique=False,
        )

    with op.batch_alter_table("decisions") as batch:
        batch.add_column(sa.Column("scenario_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_decisions_scenario_id_value_scenarios",
            "value_scenarios",
            ["scenario_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_unique_constraint(
            "uq_decisions_scenario_id",
            ["scenario_id"],
        )
        batch.create_index("ix_decisions_scenario_id", ["scenario_id"], unique=False)


def downgrade() -> None:
    _assert_downgrade_safe()

    with op.batch_alter_table("decisions") as batch:
        batch.drop_index("ix_decisions_scenario_id")
        batch.drop_constraint("uq_decisions_scenario_id", type_="unique")
        batch.drop_constraint(
            "fk_decisions_scenario_id_value_scenarios",
            type_="foreignkey",
        )
        batch.drop_column("scenario_id")

    for table in VALUE_LOOP_TABLES:
        op.drop_table(table)
