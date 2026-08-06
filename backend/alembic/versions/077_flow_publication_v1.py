"""Separate mutable Flow drafts from the immutable published pointer.

Revision ID: 077_flow_publication_v1
Revises: 076_decision_scenario_lineage

The migration is expand-and-backfill only. It does not enable the workspace
feature and never changes ``systems.flow_definition``. Every System receives a
published baseline that is byte-equivalent to that legacy mirror plus a 1:1
server draft. Existing SystemVersion rows are left immutable; a migration
version is appended only when no exact historical snapshot exists.
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

revision = "077_flow_publication_v1"
down_revision = "076_decision_scenario_lineage"
branch_labels = None
depends_on = None

FEATURE_KEY = "flow_publication_v1"


def _canonical_flow(value: Any, *, system_id: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RuntimeError(
            f"Migration 077 refuses non-object flow_definition for System {system_id}"
        )
    return deepcopy(value)


def _encoded(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha256(flow: Mapping[str, Any]) -> str:
    return hashlib.sha256(_encoded(flow).encode("utf-8")).hexdigest()


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _expand() -> None:
    op.add_column(
        "systems",
        sa.Column("published_flow_version_id", sa.String(length=36), nullable=True),
    )
    op.add_column("systems", sa.Column("published_by", sa.String(length=255), nullable=True))
    op.add_column("systems", sa.Column("published_at", sa.DateTime(), nullable=True))
    op.create_index(
        "ix_systems_published_flow_version_id",
        "systems",
        ["published_flow_version_id"],
        unique=False,
    )

    op.add_column(
        "system_versions",
        sa.Column("flow_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "system_versions",
        sa.Column("release_kind", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "system_versions",
        sa.Column("draft_revision", sa.Integer(), nullable=True),
    )
    op.add_column(
        "system_versions",
        sa.Column("execution_contract", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ix_system_versions_flow_sha256",
        "system_versions",
        ["flow_sha256"],
        unique=False,
    )
    with op.batch_alter_table("system_versions") as batch:
        batch.create_check_constraint(
            "ck_system_versions_release_kind",
            "release_kind IS NULL OR release_kind IN "
            "('legacy_snapshot', 'publish', 'rollback', 'migration')",
        )
        batch.create_check_constraint(
            "ck_system_versions_draft_revision_positive",
            "draft_revision IS NULL OR draft_revision >= 1",
        )

    op.add_column(
        "runs",
        sa.Column("published_flow_version_id", sa.String(length=36), nullable=True),
    )
    op.add_column("runs", sa.Column("flow_sha256", sa.String(length=64), nullable=True))
    op.add_column("runs", sa.Column("execution_contract", sa.JSON(), nullable=True))
    op.add_column("runs", sa.Column("execution_surface", sa.String(length=32), nullable=True))
    op.add_column("runs", sa.Column("runner_session_id", sa.String(length=36), nullable=True))
    for name, columns in (
        ("ix_runs_published_flow_version_id", ["published_flow_version_id"]),
        ("ix_runs_flow_sha256", ["flow_sha256"]),
        ("ix_runs_execution_surface", ["execution_surface"]),
        ("ix_runs_runner_session_id", ["runner_session_id"]),
    ):
        op.create_index(name, "runs", columns, unique=False)

    op.create_table(
        "system_flow_drafts",
        sa.Column("system_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=True),
        sa.Column("flow_definition", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("flow_sha256", sa.String(length=64), nullable=False),
        sa.Column("base_published_version_id", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_system_flow_drafts_revision_positive",
        ),
        sa.ForeignKeyConstraint(
            ["system_id"],
            ["systems.id"],
            name="fk_system_flow_drafts_system_id_systems",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_system_flow_drafts_workspace_id_workspaces",
        ),
        sa.ForeignKeyConstraint(
            ["base_published_version_id"],
            ["system_versions.id"],
            name="fk_system_flow_drafts_base_version",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("system_id", name="pk_system_flow_drafts"),
    )
    op.create_index(
        "ix_system_flow_drafts_workspace_id",
        "system_flow_drafts",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_system_flow_drafts_base_published_version_id",
        "system_flow_drafts",
        ["base_published_version_id"],
        unique=False,
    )


def _backfill(bind: Any) -> None:
    systems = sa.table(
        "systems",
        sa.column("id", sa.String()),
        sa.column("workspace_id", sa.String()),
        sa.column("flow_definition", sa.JSON()),
        sa.column("created_by", sa.String()),
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
    now = datetime.utcnow()
    for system_row in bind.execute(sa.select(systems)).mappings():
        system_id = str(system_row["id"])
        flow = _canonical_flow(system_row["flow_definition"], system_id=system_id)
        digest = _sha256(flow)
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
        if exact is None:
            version_id = str(uuid4())
            next_number = int(candidates[0]["version_number"] if candidates else 0) + 1
            bind.execute(
                versions.insert().values(
                    id=version_id,
                    system_id=system_id,
                    workspace_id=system_row["workspace_id"],
                    version_number=next_number,
                    flow_definition=flow,
                    configuration_snapshot=None,
                    message="Migration 077 publication baseline",
                    rolled_back_from_id=None,
                    created_at=now,
                    created_by="migration-077",
                    flow_sha256=digest,
                    release_kind="migration",
                    draft_revision=1,
                    # Migration baselines are compatibility snapshots. Full
                    # executable contracts are compiled from immutable Skills
                    # by the first explicit Publish, never guessed in Alembic.
                    execution_contract=None,
                )
            )
        else:
            version_id = str(exact["id"])

        bind.execute(
            systems.update()
            .where(systems.c.id == system_id)
            .values(
                published_flow_version_id=version_id,
                published_by="migration-077",
                published_at=now,
            )
        )
        bind.execute(
            drafts.insert().values(
                system_id=system_id,
                workspace_id=system_row["workspace_id"],
                flow_definition=flow,
                revision=1,
                flow_sha256=digest,
                base_published_version_id=version_id,
                updated_by="migration-077",
                created_at=now,
                updated_at=now,
            )
        )


def _constraints() -> None:
    with op.batch_alter_table("systems") as batch:
        batch.create_foreign_key(
            "fk_systems_published_flow_version_id_system_versions",
            "system_versions",
            ["published_flow_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
    with op.batch_alter_table("runs") as batch:
        batch.create_foreign_key(
            "fk_runs_published_flow_version_id_system_versions",
            "system_versions",
            ["published_flow_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_runs_runner_session_id_sessions",
            "sessions",
            ["runner_session_id"],
            ["id"],
            ondelete="SET NULL",
        )


def upgrade() -> None:
    _expand()
    _backfill(op.get_bind())
    _constraints()


def _feature_enabled_count(bind: Any) -> int:
    workspaces = sa.table(
        "workspaces",
        sa.column("id", sa.String()),
        sa.column("settings", sa.JSON()),
    )
    return sum(
        1
        for row in bind.execute(sa.select(workspaces.c.settings))
        if (_json_object(row.settings).get("features") or {}).get(FEATURE_KEY) is True
    )


def _assert_downgrade_safe(bind: Any) -> None:
    if _feature_enabled_count(bind):
        raise RuntimeError(
            "Refusing to downgrade Flow publication while a workspace feature is enabled"
        )
    published = int(
        bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM system_versions "
                "WHERE release_kind IN ('publish', 'rollback')"
            )
        ).scalar_one()
    )
    draft_changes = int(
        bind.execute(
            sa.text("SELECT COUNT(*) FROM system_flow_drafts WHERE revision > 1")
        ).scalar_one()
    )
    pinned_runs = int(
        bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM runs WHERE published_flow_version_id IS NOT NULL "
                "OR flow_sha256 IS NOT NULL OR execution_contract IS NOT NULL "
                "OR execution_surface IS NOT NULL OR runner_session_id IS NOT NULL"
            )
        ).scalar_one()
    )
    if published or draft_changes or pinned_runs:
        raise RuntimeError(
            "Refusing to downgrade Flow publication with product data: "
            f"published_versions={published}, changed_drafts={draft_changes}, "
            f"pinned_runs={pinned_runs}"
        )


def downgrade() -> None:
    bind = op.get_bind()
    _assert_downgrade_safe(bind)

    with op.batch_alter_table("runs") as batch:
        batch.drop_constraint(
            "fk_runs_runner_session_id_sessions", type_="foreignkey"
        )
        batch.drop_constraint(
            "fk_runs_published_flow_version_id_system_versions",
            type_="foreignkey",
        )
    with op.batch_alter_table("systems") as batch:
        batch.drop_constraint(
            "fk_systems_published_flow_version_id_system_versions",
            type_="foreignkey",
        )
    op.drop_table("system_flow_drafts")

    for name in (
        "ix_runs_runner_session_id",
        "ix_runs_execution_surface",
        "ix_runs_flow_sha256",
        "ix_runs_published_flow_version_id",
    ):
        op.drop_index(name, table_name="runs")
    for column in (
        "runner_session_id",
        "execution_surface",
        "execution_contract",
        "flow_sha256",
        "published_flow_version_id",
    ):
        op.drop_column("runs", column)

    with op.batch_alter_table("system_versions") as batch:
        batch.drop_constraint(
            "ck_system_versions_draft_revision_positive",
            type_="check",
        )
        batch.drop_constraint(
            "ck_system_versions_release_kind", type_="check"
        )
    op.drop_index("ix_system_versions_flow_sha256", table_name="system_versions")
    for column in (
        "execution_contract",
        "draft_revision",
        "release_kind",
        "flow_sha256",
    ):
        op.drop_column("system_versions", column)

    op.drop_index("ix_systems_published_flow_version_id", table_name="systems")
    for column in ("published_at", "published_by", "published_flow_version_id"):
        op.drop_column("systems", column)
