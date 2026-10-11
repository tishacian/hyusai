"""Bind measurements to forecasts and persist assumption evaluation.

Revision ID: 072_value_measurement_eval
Revises: 071_blueprint_object_keys

The migration is additive. Existing measurements are linked through their
immutable action execution. They remain honest legacy evidence: no forecast
comparison is reconstructed after the fact, so their verdict is explicitly
``not_evaluable``.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "072_value_measurement_eval"
down_revision = "071_blueprint_object_keys"
branch_labels = None
depends_on = None

LEGACY_ASSUMPTION_EVALUATION = {
    "schema_version": 1,
    "method": "legacy_backfill",
    "verdict": "not_evaluable",
    "causality": "not_established",
    "declared_assumptions": {},
    "criteria": [],
    "reason": "forecast_comparison_not_persisted_at_measurement_time",
}


def _enum_check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _assert_downgrade_safe() -> None:
    """Preserve every post-migration forecast comparison and verdict."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "value_measurements" not in inspector.get_table_names():
        return
    required = {
        "id",
        "action_execution_id",
        "simulation_id",
        "forecast_delta",
        "assumption_verdict",
        "assumption_evaluation",
    }
    if not required.issubset(
        {column["name"] for column in inspector.get_columns("value_measurements")}
    ):
        return

    measurements = sa.table(
        "value_measurements",
        sa.column("id", sa.String(length=36)),
        sa.column("action_execution_id", sa.String(length=36)),
        sa.column("simulation_id", sa.String(length=36)),
        sa.column("forecast_delta", sa.JSON()),
        sa.column("assumption_verdict", sa.String(length=32)),
        sa.column("assumption_evaluation", sa.JSON()),
    )
    actions = sa.table(
        "value_action_executions",
        sa.column("id", sa.String(length=36)),
        sa.column("simulation_id", sa.String(length=36)),
    )
    rows = bind.execute(
        sa.select(
            measurements.c.id,
            measurements.c.simulation_id,
            measurements.c.forecast_delta,
            measurements.c.assumption_verdict,
            measurements.c.assumption_evaluation,
            actions.c.simulation_id.label("action_simulation_id"),
        ).select_from(
            measurements.outerjoin(
                actions,
                actions.c.id == measurements.c.action_execution_id,
            )
        )
    ).mappings()
    unsafe = [
        str(row["id"])
        for row in rows
        if row["simulation_id"] != row["action_simulation_id"]
        or row["forecast_delta"] is not None
        or row["assumption_verdict"] != "not_evaluable"
        or row["assumption_evaluation"] != LEGACY_ASSUMPTION_EVALUATION
    ]
    if unsafe:
        raise RuntimeError(
            "refusing downgrade because value measurement evaluation evidence "
            f"is not a reconstructible legacy backfill (rows={len(unsafe)})"
        )


def upgrade() -> None:
    op.add_column(
        "value_measurements",
        sa.Column("simulation_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "value_measurements",
        sa.Column("forecast_delta", sa.JSON(), nullable=True),
    )
    op.add_column(
        "value_measurements",
        sa.Column("assumption_verdict", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "value_measurements",
        sa.Column("assumption_evaluation", sa.JSON(), nullable=True),
    )

    measurements = sa.table(
        "value_measurements",
        sa.column("id", sa.String(length=36)),
        sa.column("action_execution_id", sa.String(length=36)),
        sa.column("simulation_id", sa.String(length=36)),
        sa.column("assumption_verdict", sa.String(length=32)),
        sa.column("assumption_evaluation", sa.JSON()),
    )
    actions = sa.table(
        "value_action_executions",
        sa.column("id", sa.String(length=36)),
        sa.column("simulation_id", sa.String(length=36)),
    )
    connection = op.get_bind()
    simulation_id = (
        sa.select(actions.c.simulation_id)
        .where(actions.c.id == measurements.c.action_execution_id)
        .scalar_subquery()
    )
    connection.execute(
        measurements.update().values(
            simulation_id=simulation_id,
            assumption_verdict="not_evaluable",
            assumption_evaluation=LEGACY_ASSUMPTION_EVALUATION,
        )
    )
    missing = connection.execute(
        sa.select(sa.func.count())
        .select_from(measurements)
        .where(measurements.c.simulation_id.is_(None))
    ).scalar_one()
    if missing:
        raise RuntimeError(
            "cannot bind legacy value measurements to their action simulation"
        )

    with op.batch_alter_table("value_measurements") as batch:
        batch.alter_column(
            "simulation_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
        batch.alter_column(
            "assumption_verdict",
            existing_type=sa.String(length=32),
            nullable=False,
        )
        batch.alter_column(
            "assumption_evaluation",
            existing_type=sa.JSON(),
            nullable=False,
        )
        batch.create_foreign_key(
            "fk_value_measurements_simulation_id_value_simulations",
            "value_simulations",
            ["simulation_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint(
            "ck_value_measurements_assumption_verdict",
            _enum_check(
                "assumption_verdict",
                (
                    "confirmed",
                    "partially_confirmed",
                    "not_confirmed",
                    "not_evaluable",
                ),
            ),
        )
    op.create_index(
        "ix_value_measurements_simulation_id",
        "value_measurements",
        ["simulation_id"],
        unique=False,
    )


def downgrade() -> None:
    _assert_downgrade_safe()

    op.drop_index(
        "ix_value_measurements_simulation_id",
        table_name="value_measurements",
    )
    with op.batch_alter_table("value_measurements") as batch:
        batch.drop_constraint(
            "ck_value_measurements_assumption_verdict",
            type_="check",
        )
        batch.drop_constraint(
            "fk_value_measurements_simulation_id_value_simulations",
            type_="foreignkey",
        )
        batch.drop_column("assumption_evaluation")
        batch.drop_column("assumption_verdict")
        batch.drop_column("forecast_delta")
        batch.drop_column("simulation_id")
