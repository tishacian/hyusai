"""Backfill the publication baseline Systems created after 077 never received.

Revision ID: 081_flow_publication_baseline
Revises: 080_trigger_event_claims

Migration 077 expanded the schema and gave every System of the day a published
pointer plus a 1:1 server draft, but it did not enable the feature. Systems
created while the workspace flag was off went down the legacy path, which writes
``systems.flow_definition`` and appends SystemVersion rows without ever setting
``published_flow_version_id`` or inserting a ``system_flow_drafts`` row. Turning
``flow_publication_v1`` on by default makes the publication authority read those
missing rows, so they are backfilled here first.

Data-only and idempotent: no schema change, ``systems.flow_definition`` is never
touched, and every System already holding a baseline is skipped. Like 077 the
appended baseline carries ``execution_contract = NULL``; contracts are compiled
from immutable Skills, which Alembic cannot reach. Closing that second gap is
``scripts/backfill_flow_publication_contracts.py`` and it must run before the
Systems touched here are expected to execute.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "081_flow_publication_baseline"
down_revision = "080_trigger_event_claims"
branch_labels = None
depends_on = None

ACTOR = "migration-081"


def _canonical_flow(value: Any, *, system_id: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RuntimeError(
            f"Migration 081 refuses non-object flow_definition for System {system_id}"
        )
    return deepcopy(value)


def _encoded(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha256(flow: Mapping[str, Any]) -> str:
    return hashlib.sha256(_encoded(flow).encode("utf-8")).hexdigest()


def _tables() -> tuple[Any, Any, Any]:
    systems = sa.table(
        "systems",
        sa.column("id", sa.String()),
        sa.column("workspace_id", sa.String()),
        sa.column("flow_definition", sa.JSON()),
        sa.column("published_flow_version_id", sa.String()),
        sa.column("published_by", sa.String()),
        sa.column("published_at", sa.DateTime()),
    )
    versions = sa.table(
        "system_versions",
        sa.column("id", sa.String()),
        sa.column("system_id", sa.String()),
        sa.column("workspace_id", sa.String()),
        sa.column("version_number", sa.Integer()),
        sa.column("flow_definition", sa.JSON()),
        sa.column("configuration_snapshot", sa.JSON()),
        sa.column("message", sa.Text()),
        sa.column("rolled_back_from_id", sa.String()),
        sa.column("created_at", sa.DateTime()),
        sa.column("created_by", sa.String()),
        sa.column("flow_sha256", sa.String()),
        sa.column("release_kind", sa.String()),
        sa.column("draft_revision", sa.Integer()),
        sa.column("execution_contract", sa.JSON()),
    )
    drafts = sa.table(
        "system_flow_drafts",
        sa.column("system_id", sa.String()),
        sa.column("workspace_id", sa.String()),
        sa.column("flow_definition", sa.JSON()),
        sa.column("revision", sa.Integer()),
        sa.column("flow_sha256", sa.String()),
        sa.column("base_published_version_id", sa.String()),
        sa.column("updated_by", sa.String()),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    return systems, versions, drafts


def _published_version_id(
    bind: Any,
    versions: Any,
    *,
    system_id: str,
    workspace_id: Any,
    flow: dict[str, Any],
    digest: str,
    now: datetime,
) -> str:
    """Reuse the exact historical snapshot when one exists, else append one."""
    candidates = list(
        bind.execute(
            sa.select(versions)
            .where(versions.c.system_id == system_id)
            .order_by(versions.c.version_number.desc())
        ).mappings()
    )
    exact = next(
        (
            row
            for row in candidates
            if isinstance(row["flow_definition"], dict)
            and _encoded(row["flow_definition"]) == _encoded(flow)
        ),
        None,
    )
    if exact is not None:
        if not exact["flow_sha256"]:
            bind.execute(
                versions.update()
                .where(versions.c.id == exact["id"])
                .values(flow_sha256=digest)
            )
        return str(exact["id"])

    version_id = str(uuid4())
    next_number = int(candidates[0]["version_number"] if candidates else 0) + 1
    bind.execute(
        versions.insert().values(
            id=version_id,
            system_id=system_id,
            workspace_id=workspace_id,
            version_number=next_number,
            flow_definition=flow,
            configuration_snapshot=None,
            message="Migration 081 publication baseline",
            rolled_back_from_id=None,
            created_at=now,
            created_by=ACTOR,
            flow_sha256=digest,
            release_kind="migration",
            draft_revision=1,
            execution_contract=None,
        )
    )
    return version_id


def upgrade() -> None:
    bind = op.get_bind()
    systems, versions, drafts = _tables()
    now = datetime.utcnow()

    existing_drafts = {
        str(row[0]) for row in bind.execute(sa.select(drafts.c.system_id))
    }
    # Materialized: the loop writes to ``systems``, which must not happen while
    # a cursor over the same table is still open.
    system_rows = list(bind.execute(sa.select(systems)).mappings().all())
    for system_row in system_rows:
        system_id = str(system_row["id"])
        pointer = system_row["published_flow_version_id"]
        has_draft = system_id in existing_drafts
        if pointer and has_draft:
            continue

        flow = _canonical_flow(system_row["flow_definition"], system_id=system_id)
        digest = _sha256(flow)
        version_id = (
            str(pointer)
            if pointer
            else _published_version_id(
                bind,
                versions,
                system_id=system_id,
                workspace_id=system_row["workspace_id"],
                flow=flow,
                digest=digest,
                now=now,
            )
        )

        if not pointer:
            bind.execute(
                systems.update()
                .where(systems.c.id == system_id)
                .values(
                    published_flow_version_id=version_id,
                    published_by=ACTOR,
                    published_at=now,
                )
            )
        if not has_draft:
            bind.execute(
                drafts.insert().values(
                    system_id=system_id,
                    workspace_id=system_row["workspace_id"],
                    flow_definition=flow,
                    revision=1,
                    flow_sha256=digest,
                    base_published_version_id=version_id,
                    updated_by=ACTOR,
                    created_at=now,
                    updated_at=now,
                )
            )


def downgrade() -> None:
    """Drop only the rows this migration authored, leaving edited drafts alone.

    A draft advanced past revision 1 holds editor work saved after the
    backfill, so it survives. Appended baseline versions also survive:
    SystemVersion is append-only and 077 owns the teardown of the table.
    """
    bind = op.get_bind()
    systems, _versions, drafts = _tables()

    bind.execute(
        drafts.delete().where(
            sa.and_(drafts.c.updated_by == ACTOR, drafts.c.revision == 1)
        )
    )
    bind.execute(
        systems.update()
        .where(systems.c.published_by == ACTOR)
        .values(
            published_flow_version_id=None,
            published_by=None,
            published_at=None,
        )
    )
