"""Unify trigger delivery claims and add durable trigger Run dispatch.

Revision ID: 080_trigger_event_claims
Revises: 079_trigger_run_dedup
"""

from __future__ import annotations

import logging

import sqlalchemy as sa

from alembic import op

revision = "080_trigger_event_claims"
down_revision = "079_trigger_run_dedup"
branch_labels = None
depends_on = None

OUTBOX_CHECK = "ck_run_dispatch_outbox_event_type"
logger = logging.getLogger("alembic.runtime.migration")


def _backfill_claims(bind: object) -> None:
    runs = sa.table(
        "runs",
        sa.column("id", sa.String()),
        sa.column("workspace_id", sa.String()),
        sa.column("system_id", sa.String()),
        sa.column("status", sa.String()),
        sa.column("trigger_dedup_key", sa.String()),
        sa.column("started_at", sa.DateTime()),
    )
    claims = sa.table(
        "trigger_event_claims",
        sa.column("id", sa.String()),
        sa.column("workspace_id", sa.String()),
        sa.column("system_id", sa.String()),
        sa.column("dedup_key", sa.String()),
        sa.column("outcome", sa.String()),
        sa.column("run_id", sa.String()),
        sa.column("created_at", sa.DateTime()),
    )
    rows = bind.execute(
        sa.select(
            runs.c.id,
            runs.c.workspace_id,
            runs.c.system_id,
            runs.c.status,
            runs.c.trigger_dedup_key,
            runs.c.started_at,
        ).where(runs.c.trigger_dedup_key.is_not(None))
    ).mappings()
    for row in rows:
        if not row["system_id"] or not row["trigger_dedup_key"]:
            continue
        bind.execute(
            claims.insert().values(
                id=str(row["id"]),
                workspace_id=row["workspace_id"],
                system_id=row["system_id"],
                dedup_key=row["trigger_dedup_key"],
                outcome="simulated" if row["status"] == "simulated" else "run",
                run_id=row["id"],
                created_at=row["started_at"],
            )
        )


def upgrade() -> None:
    op.create_table(
        "trigger_event_claims",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=True),
        sa.Column("system_id", sa.String(length=36), nullable=False),
        sa.Column("dedup_key", sa.String(length=255), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("inbox_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('run', 'simulated', 'inbox')",
            name="ck_trigger_event_claim_outcome",
        ),
        sa.CheckConstraint(
            "(outcome IN ('run', 'simulated') AND run_id IS NOT NULL AND inbox_id IS NULL) "
            "OR (outcome = 'inbox' AND run_id IS NULL AND inbox_id IS NOT NULL)",
            name="ck_trigger_event_claim_target",
        ),
        sa.ForeignKeyConstraint(["inbox_id"], ["run_inbox.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "system_id",
            "dedup_key",
            name="uq_trigger_event_claim_system_key",
        ),
    )

    _backfill_claims(op.get_bind())

    with op.batch_alter_table("run_dispatch_outbox") as batch:
        batch.drop_constraint(OUTBOX_CHECK, type_="check")
        batch.create_check_constraint(
            OUTBOX_CHECK,
            "event_type IN ('trigger_run', 'subflow_run', 'subflow_parent_resume', "
            "'subflow_hitl_resume', 'run_hitl_resume')",
        )


def downgrade() -> None:
    bind = op.get_bind()
    outbox = sa.table(
        "run_dispatch_outbox",
        sa.column("event_type", sa.String()),
    )
    deleted = bind.execute(outbox.delete().where(outbox.c.event_type == "trigger_run"))
    if deleted.rowcount:
        logger.warning(
            "Dropping queued trigger dispatches during migration 080 downgrade",
            extra={"deleted_trigger_dispatches": deleted.rowcount},
        )
    with op.batch_alter_table("run_dispatch_outbox") as batch:
        batch.drop_constraint(OUTBOX_CHECK, type_="check")
        batch.create_check_constraint(
            OUTBOX_CHECK,
            "event_type IN ('subflow_run', 'subflow_parent_resume', "
            "'subflow_hitl_resume', 'run_hitl_resume')",
        )
    op.drop_table("trigger_event_claims")
