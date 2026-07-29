"""Enforce one version number per System history.

Revision ID: 067_system_version_uniqueness
Revises: 066_skill_invocation_snapshot

Runtime allocation is serialized by locking the parent ``systems`` row.  This
constraint is the final invariant for imports and any writer that does not use
the shared version service.

The migration never guesses how to repair historical collisions.  It first
audits every duplicate group and fails with a structured, log-visible report;
operators must investigate and resolve those rows explicitly before retrying.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "067_system_version_uniqueness"
down_revision = "066_skill_invocation_snapshot"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "uq_system_versions_system_version_number"
logger = logging.getLogger("alembic.runtime.migration")


def _duplicate_version_groups(bind: Any) -> list[dict[str, Any]]:
    """Return a deterministic, non-secret preflight report."""

    rows = bind.execute(
        sa.text(
            """
            SELECT system_id, version_number, COUNT(*) AS duplicate_count
            FROM system_versions
            GROUP BY system_id, version_number
            HAVING COUNT(*) > 1
            ORDER BY system_id ASC, version_number ASC
            """
        )
    ).mappings()
    return [
        {
            "system_id": str(row["system_id"]),
            "version_number": int(row["version_number"]),
            "duplicate_count": int(row["duplicate_count"]),
        }
        for row in rows
    ]


def _duplicate_audit(groups: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "event": "system_versions.uniqueness_preflight_failed",
        "constraint": CONSTRAINT_NAME,
        "duplicate_group_count": len(groups),
        "duplicate_row_count": sum(group["duplicate_count"] for group in groups),
        "groups": groups,
        "resolution": "resolve collisions explicitly, then rerun the migration",
    }


def upgrade() -> None:
    bind = op.get_bind()
    duplicates = _duplicate_version_groups(bind)
    if duplicates:
        audit = _duplicate_audit(duplicates)
        report = json.dumps(audit, sort_keys=True, separators=(",", ":"))
        logger.error("SystemVersion uniqueness preflight failed: %s", report)
        raise RuntimeError(f"SystemVersion uniqueness preflight failed: {report}")

    with op.batch_alter_table("system_versions") as batch:
        batch.create_unique_constraint(
            CONSTRAINT_NAME,
            ["system_id", "version_number"],
        )


def downgrade() -> None:
    with op.batch_alter_table("system_versions") as batch:
        batch.drop_constraint(CONSTRAINT_NAME, type_="unique")
