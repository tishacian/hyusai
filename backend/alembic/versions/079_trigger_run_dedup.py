"""Add an atomic idempotency claim for event-triggered Runs.

Revision ID: 079_trigger_run_dedup
Revises: 078_andritz_decision_contract

Historical trigger keys lived only inside ``runs.input_ref`` and were found by
an application-side scan.  That check was not atomic under concurrent event
deliveries.  This migration promotes one deterministic claimant per historical
key into a nullable unique column.  Historical duplicate audit rows are kept
unchanged with a NULL claim; no Run is deleted or rewritten beyond the new
projection.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "079_trigger_run_dedup"
down_revision = "078_andritz_decision_contract"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "uq_runs_trigger_dedup_key"
MAX_KEY_LENGTH = 255
_TRIGGER_META_KEY = "_event_trigger"
logger = logging.getLogger("alembic.runtime.migration")


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _historical_key(value: Any) -> str | None:
    metadata = _json_object(_json_object(value).get(_TRIGGER_META_KEY))
    key = metadata.get("dedup_key")
    if not isinstance(key, str) or not key or len(key) > MAX_KEY_LENGTH:
        return None
    return key


def _backfill(bind: Any) -> None:
    runs = sa.table(
        "runs",
        sa.column("id", sa.String()),
        sa.column("system_id", sa.String()),
        sa.column("trigger", sa.String()),
        sa.column("input_ref", sa.JSON()),
        sa.column("trigger_dedup_key", sa.String()),
    )
    claimed: dict[tuple[str | None, str], str] = {}
    rows = bind.execute(
        sa.select(
            runs.c.id,
            runs.c.system_id,
            runs.c.input_ref,
            runs.c.trigger_dedup_key,
        )
        .where(runs.c.trigger == "webhook")
        .order_by(runs.c.id.asc())
    ).mappings()
    for row in rows:
        key = row["trigger_dedup_key"] or _historical_key(row["input_ref"])
        if not isinstance(key, str) or not key or len(key) > MAX_KEY_LENGTH:
            continue
        identity = (row["system_id"], key)
        canonical_id = claimed.get(identity)
        if canonical_id is not None:
            logger.warning(
                "Migration 079 retained a historical duplicate without a claim",
                extra={
                    "trigger_dedup_key": key,
                    "canonical_run_id": canonical_id,
                    "duplicate_run_id": str(row["id"]),
                },
            )
            continue
        claimed[identity] = str(row["id"])
        if row["trigger_dedup_key"] != key:
            bind.execute(runs.update().where(runs.c.id == row["id"]).values(trigger_dedup_key=key))


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("trigger_dedup_key", sa.String(length=MAX_KEY_LENGTH), nullable=True),
    )
    _backfill(op.get_bind())
    with op.batch_alter_table("runs") as batch:
        batch.create_unique_constraint(
            CONSTRAINT_NAME,
            ["system_id", "trigger_dedup_key"],
        )


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.drop_constraint(CONSTRAINT_NAME, type_="unique")
    op.drop_column("runs", "trigger_dedup_key")
