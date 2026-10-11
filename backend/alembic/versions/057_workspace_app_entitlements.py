"""Add explicit workspace-member application entitlements.

The Andritz backfill is data-driven: every membership present when this
migration runs receives the three applications that membership already grants
today.  Flags are enabled only after the migration verifies the full cartesian
backfill, so the new enforcement cannot observe a partially granted cohort.

Revision ID: 057_app_entitlements
Revises: 056_andritz_chat_asset_binding
Create Date: 2026-07-15
"""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "057_app_entitlements"
down_revision = "056_andritz_chat_asset_binding"
branch_labels = None
depends_on = None


ANDRITZ_SLUG = "andritz"
APP_KEYS = ("chat", "client360-pdr", "knowledge-capture")
APP_ENTITLEMENTS_FEATURE = "app_entitlements_v1"
WORKSPACE_EXPERIENCE_FEATURE = "workspace_experience_v2"
BACKFILL_SOURCE = "057_andritz_backfill"
MIGRATION_MARKER_KEY = "_migration_057_app_entitlements_state"
MIGRATION_MARKER_REVISION = revision
MIGRATION_MARKER_SCHEMA = 1


def _as_settings(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return deepcopy(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _workspace_tables():
    workspaces = sa.table(
        "workspaces",
        sa.column("id", sa.String(length=36)),
        sa.column("slug", sa.String(length=100)),
        sa.column("settings", sa.JSON()),
    )
    members = sa.table(
        "workspace_members",
        sa.column("id", sa.Integer()),
        sa.column("workspace_id", sa.String(length=36)),
    )
    entitlements = sa.table(
        "workspace_member_app_entitlements",
        sa.column("id", sa.Integer()),
        sa.column("workspace_member_id", sa.Integer()),
        sa.column("app_key", sa.String(length=80)),
        sa.column("granted_at", sa.DateTime()),
        sa.column("granted_by_user_id", sa.String(length=36)),
        sa.column("grant_source", sa.String(length=80)),
    )
    return workspaces, members, entitlements


def _flag_snapshot(features: dict[str, Any], key: str) -> dict[str, Any]:
    if key not in features:
        return {"state": "absent"}
    return {"state": "present", "value": deepcopy(features[key])}


def _migration_marker(settings: dict[str, Any]) -> dict[str, Any]:
    """Capture the two owned flags without snapshotting unrelated settings."""

    raw_features = settings.get("features")
    features = raw_features if isinstance(raw_features, dict) else {}
    if "features" not in settings:
        container = "absent"
    elif isinstance(raw_features, dict):
        container = "mapping"
    else:
        container = "other"

    marker: dict[str, Any] = {
        "revision": MIGRATION_MARKER_REVISION,
        "schema": MIGRATION_MARKER_SCHEMA,
        "features_container": container,
        "flags": {
            APP_ENTITLEMENTS_FEATURE: _flag_snapshot(features, APP_ENTITLEMENTS_FEATURE),
            WORKSPACE_EXPERIENCE_FEATURE: _flag_snapshot(features, WORKSPACE_EXPERIENCE_FEATURE),
        },
    }
    if container == "other":
        marker["features_value"] = deepcopy(raw_features)
    return marker


def _restore_flags_from_marker(settings: dict[str, Any], marker: dict[str, Any]) -> dict[str, Any]:
    """Restore migration-owned flags while preserving every unrelated key."""

    if (
        marker.get("revision") != MIGRATION_MARKER_REVISION
        or marker.get("schema") != MIGRATION_MARKER_SCHEMA
        or marker.get("features_container") not in {"absent", "mapping", "other"}
        or not isinstance(marker.get("flags"), dict)
    ):
        raise RuntimeError("Ambiguous 057 application entitlement migration marker")

    raw_features = settings.get("features")
    features = deepcopy(raw_features) if isinstance(raw_features, dict) else {}
    snapshots = marker["flags"]
    for key in (APP_ENTITLEMENTS_FEATURE, WORKSPACE_EXPERIENCE_FEATURE):
        snapshot = snapshots.get(key)
        if not isinstance(snapshot, dict) or snapshot.get("state") not in {
            "absent",
            "present",
        }:
            raise RuntimeError("Ambiguous 057 application entitlement flag snapshot")
        if snapshot["state"] == "present":
            if "value" not in snapshot:
                raise RuntimeError("Ambiguous 057 application entitlement flag snapshot")
            features[key] = deepcopy(snapshot["value"])
        else:
            features.pop(key, None)

    container = marker["features_container"]
    if container == "mapping":
        settings["features"] = features
    elif container == "absent" and not features:
        settings.pop("features", None)
    elif container == "other" and not features:
        settings["features"] = deepcopy(marker.get("features_value"))
    else:
        # Preserve unrelated feature keys added after the migration.
        settings["features"] = features

    settings.pop(MIGRATION_MARKER_KEY, None)
    return settings


def _backfill_andritz(bind) -> None:
    workspaces, members, entitlements = _workspace_tables()
    if bind.dialect.name == "postgresql":
        # Do not activate enforcement against a membership cohort that can
        # change mid-backfill. The deployment runbook also quiesces the API to
        # cover requests that began before this transaction acquired its lock.
        bind.execute(sa.text("SET LOCAL lock_timeout = '15s'"))
        bind.execute(sa.text("LOCK TABLE workspace_members IN SHARE MODE"))

    rows = bind.execute(
        sa.select(workspaces.c.id, workspaces.c.settings)
        .where(workspaces.c.slug == ANDRITZ_SLUG)
        .with_for_update()
    ).all()

    for row in rows:
        workspace_id = row._mapping["id"]
        member_count = int(
            bind.execute(
                sa.select(sa.func.count())
                .select_from(members)
                .where(members.c.workspace_id == workspace_id)
            ).scalar_one()
        )

        for app_key in APP_KEYS:
            bind.execute(
                sa.insert(entitlements).from_select(
                    [
                        "workspace_member_id",
                        "app_key",
                        "granted_at",
                        "granted_by_user_id",
                        "grant_source",
                    ],
                    sa.select(
                        members.c.id,
                        sa.literal(app_key),
                        sa.func.now(),
                        sa.null(),
                        sa.literal(BACKFILL_SOURCE),
                    ).where(members.c.workspace_id == workspace_id),
                )
            )

        grant_count = int(
            bind.execute(
                sa.select(sa.func.count())
                .select_from(
                    entitlements.join(
                        members,
                        entitlements.c.workspace_member_id == members.c.id,
                    )
                )
                .where(
                    members.c.workspace_id == workspace_id,
                    entitlements.c.app_key.in_(APP_KEYS),
                )
            ).scalar_one()
        )
        expected = member_count * len(APP_KEYS)
        if grant_count != expected:
            raise RuntimeError(
                "Andritz application entitlement backfill incomplete: "
                f"expected {expected}, found {grant_count}"
            )

        missing_grants = 0
        for app_key in APP_KEYS:
            missing_grants += int(
                bind.execute(
                    sa.select(sa.func.count())
                    .select_from(
                        members.outerjoin(
                            entitlements,
                            sa.and_(
                                entitlements.c.workspace_member_id == members.c.id,
                                entitlements.c.app_key == app_key,
                            ),
                        )
                    )
                    .where(
                        members.c.workspace_id == workspace_id,
                        entitlements.c.id.is_(None),
                    )
                ).scalar_one()
            )
        if missing_grants:
            raise RuntimeError(
                "Andritz application entitlement backfill incomplete: "
                f"missing {missing_grants} member/application grants"
            )

        settings = _as_settings(row._mapping["settings"])
        if MIGRATION_MARKER_KEY in settings:
            raise RuntimeError(
                "Refusing to overwrite an existing 057 application entitlement " "migration marker"
            )
        settings[MIGRATION_MARKER_KEY] = _migration_marker(settings)
        raw_features = settings.get("features")
        features = deepcopy(raw_features) if isinstance(raw_features, dict) else {}
        features[APP_ENTITLEMENTS_FEATURE] = True
        features[WORKSPACE_EXPERIENCE_FEATURE] = True
        settings["features"] = features
        bind.execute(
            sa.update(workspaces).where(workspaces.c.id == workspace_id).values(settings=settings)
        )


def upgrade() -> None:
    op.create_table(
        "workspace_member_app_entitlements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_member_id",
            sa.Integer(),
            sa.ForeignKey("workspace_members.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("app_key", sa.String(length=80), nullable=False),
        sa.Column("granted_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "granted_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "grant_source",
            sa.String(length=80),
            nullable=False,
            server_default="manual",
        ),
        sa.UniqueConstraint(
            "workspace_member_id",
            "app_key",
            name="uq_workspace_member_app_entitlement",
        ),
    )
    op.create_index(
        "ix_workspace_member_app_entitlements_workspace_member_id",
        "workspace_member_app_entitlements",
        ["workspace_member_id"],
    )
    op.create_index(
        "ix_workspace_member_app_entitlements_app_key",
        "workspace_member_app_entitlements",
        ["app_key"],
    )
    _backfill_andritz(op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    workspaces, members, entitlements = _workspace_tables()
    unsafe_grants = int(
        bind.execute(
            sa.select(sa.func.count())
            .select_from(
                entitlements.join(
                    members,
                    entitlements.c.workspace_member_id == members.c.id,
                ).join(workspaces, members.c.workspace_id == workspaces.c.id)
            )
            .where(
                sa.or_(
                    workspaces.c.slug != ANDRITZ_SLUG,
                    entitlements.c.grant_source != BACKFILL_SOURCE,
                )
            )
        ).scalar_one()
    )
    if unsafe_grants:
        raise RuntimeError(
            "Refusing to drop application entitlements containing "
            f"{unsafe_grants} post-migration or non-Andritz grants"
        )

    rows = bind.execute(
        sa.select(workspaces.c.id, workspaces.c.settings)
        .where(workspaces.c.slug == ANDRITZ_SLUG)
        .with_for_update()
    ).all()
    restored_rows: list[tuple[str, dict[str, Any]]] = []
    for row in rows:
        settings = _as_settings(row._mapping["settings"])
        marker = settings.get(MIGRATION_MARKER_KEY)
        if marker is None:
            raise RuntimeError("Refusing to downgrade 057: Andritz migration marker is missing")
        if not isinstance(marker, dict):
            raise RuntimeError("Ambiguous 057 application entitlement migration marker")
        settings = _restore_flags_from_marker(settings, marker)
        restored_rows.append((row._mapping["id"], settings))

    for workspace_id, settings in restored_rows:
        bind.execute(
            sa.update(workspaces).where(workspaces.c.id == workspace_id).values(settings=settings)
        )

    op.drop_index(
        "ix_workspace_member_app_entitlements_app_key",
        table_name="workspace_member_app_entitlements",
    )
    op.drop_index(
        "ix_workspace_member_app_entitlements_workspace_member_id",
        table_name="workspace_member_app_entitlements",
    )
    op.drop_table("workspace_member_app_entitlements")
