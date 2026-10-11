"""Pin the exact ValueSimulation contract accepted at approval.

Revision ID: 075_simulation_approval_pin
Revises: 074_relational_integrity

The columns are deliberately nullable for historical rows.  There is no
honest way to reconstruct what an approver saw from a mutable legacy
ValueSimulation after the fact, so this migration performs no backfill.  The
authoritative actuator fails closed for every approved scenario without a
server-written pin.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "075_simulation_approval_pin"
down_revision = "074_relational_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "value_scenarios",
        sa.Column(
            "approved_simulation_content_sha256",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.add_column(
        "value_scenarios",
        sa.Column("approved_simulation_snapshot", sa.JSON(), nullable=True),
    )


def _active_pin_count(bind: object) -> int:
    """Refuse to erase approval authority or guess how to preserve it."""

    inspector = sa.inspect(bind)
    if "value_scenarios" not in set(inspector.get_table_names()):
        raise RuntimeError(
            "Refusing to downgrade simulation approval pins: value_scenarios is missing"
        )
    columns = {str(column["name"]) for column in inspector.get_columns("value_scenarios")}
    required = {
        "approved_simulation_content_sha256",
        "approved_simulation_snapshot",
    }
    missing = sorted(required - columns)
    if missing:
        raise RuntimeError(
            "Refusing to downgrade simulation approval pins: missing columns " + ", ".join(missing)
        )
    count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM value_scenarios "
            "WHERE approved_simulation_content_sha256 IS NOT NULL "
            "OR approved_simulation_snapshot IS NOT NULL"
        )
    ).scalar_one()
    return int(count)


def downgrade() -> None:
    active = _active_pin_count(op.get_bind())
    if active:
        raise RuntimeError(
            "Refusing to downgrade simulation approval pins while "
            f"{active} scenario(s) retain approval authority"
        )
    op.drop_column("value_scenarios", "approved_simulation_snapshot")
    op.drop_column("value_scenarios", "approved_simulation_content_sha256")
