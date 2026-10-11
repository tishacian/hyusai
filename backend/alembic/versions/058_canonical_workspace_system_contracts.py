"""Constrain canonical workspace, System and application contracts.

Revision ID: 058_canonical_contracts
Revises: 057_app_entitlements
Create Date: 2026-07-15

The migration first stamps every workspace's historical implicit family and
materializes Andritz's historical implicit action pack, then audits every
persisted enum value before installing database checks.
Legacy ``systems.status='archived'`` is the only semantic alias rewritten; it
maps exactly to the canonical reversible archive state ``retired``.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "058_canonical_contracts"
down_revision = "057_app_entitlements"
branch_labels = None
depends_on = None


WORKSPACE_MODES = ("builder", "operator", "executive", "demo", "portfolio")
WORKSPACE_FAMILIES = ("andritz", "industrial", "sentinel_ci", "generic")
SYSTEM_STATUSES = ("draft", "active", "paused", "retired")
EXECUTION_MODES = (
    "real_time_decision",
    "batch_processing",
    "event_driven_automation",
    "continuous_monitoring",
    "human_augmented",
)
WORKSPACE_APPS = ("chat", "client360-pdr", "knowledge-capture")
ACTION_PACK_IDS = (
    "global_voice_v1",
    "andritz_industrial_v1",
    "sentinel_ci_aya_v1",
    "sentinel_ci_aya_security_v1",
    "octave_mission_room_v1",
    "octave_security_v1",
)

ANDRITZ_SLUG = "andritz"
ANDRITZ_ACTION_PACK = "andritz_industrial_v1"
MIGRATION_MARKER_KEY = "_migration_058_canonical_contracts_state"
MIGRATION_MARKER_SCHEMA = 2

CK_WORKSPACES_MODE = "ck_workspaces_mode"
CK_SYSTEMS_STATUS = "ck_systems_status"
CK_SYSTEMS_EXECUTION_MODE = "ck_systems_execution_mode"
CK_WORKSPACE_APPS = "ck_workspace_member_app_entitlements_app_key"


def _as_settings(value: Any, *, allow_none: bool = False) -> dict[str, Any]:
    if isinstance(value, dict):
        return deepcopy(value)
    if value is None and allow_none:
        return {}
    raise RuntimeError("Canonical contract JSON settings must be an object")


def _field_snapshot(container: dict[str, Any], key: str) -> dict[str, Any]:
    if key not in container:
        return {"state": "absent"}
    return {"state": "present", "value": deepcopy(container[key])}


def _legacy_workspace_family(slug: Any, name: Any) -> str:
    """Frozen one-shot snapshot of the pre-058 runtime heuristic."""

    normalized_slug = str(slug or "").strip().lower()
    normalized_name = str(name or "").strip().lower()
    if "andritz" in normalized_slug or "andritz" in normalized_name:
        return "andritz"
    if normalized_slug == "sentinel-ci" or "sentinel" in normalized_slug:
        return "sentinel_ci"
    return "generic"


def _new_workspace_marker(
    settings: dict[str, Any],
    *,
    applied_family: str,
    snapshot_actions: bool,
) -> dict[str, Any]:
    marker = {
        "revision": revision,
        "schema": MIGRATION_MARKER_SCHEMA,
        "family": _field_snapshot(settings, "family"),
        "applied_family": applied_family,
    }
    if not snapshot_actions:
        return marker

    raw_actions = settings.get("actions")
    if "actions" not in settings:
        container = "absent"
        actions: dict[str, Any] = {}
    elif isinstance(raw_actions, dict):
        container = "mapping"
        actions = raw_actions
    else:
        raise RuntimeError("Cannot backfill Andritz action pack: settings.actions is not an object")
    marker["actions_container"] = container
    marker["enabled_packs"] = _field_snapshot(actions, "enabled_packs")
    return marker


def _validate_marker(marker: Any) -> dict[str, Any]:
    if not isinstance(marker, dict):
        raise RuntimeError("Ambiguous 058 canonical-contract migration marker")
    if (
        marker.get("revision") != revision
        or marker.get("schema") != MIGRATION_MARKER_SCHEMA
        or marker.get("applied_family") not in WORKSPACE_FAMILIES
        or not isinstance(marker.get("family"), dict)
        or marker["family"].get("state") not in {"absent", "present"}
    ):
        raise RuntimeError("Ambiguous 058 canonical-contract migration marker")
    if marker["family"]["state"] == "present" and "value" not in marker["family"]:
        raise RuntimeError("Ambiguous 058 canonical-contract migration marker")

    action_keys = {
        "actions_container",
        "enabled_packs",
        "applied_enabled_packs",
    }
    present_action_keys = action_keys.intersection(marker)
    if present_action_keys and present_action_keys != action_keys:
        raise RuntimeError("Ambiguous 058 canonical-contract migration marker")
    if present_action_keys:
        if (
            marker.get("actions_container") not in {"absent", "mapping"}
            or not isinstance(marker.get("enabled_packs"), dict)
            or marker["enabled_packs"].get("state") not in {"absent", "present"}
            or not isinstance(marker.get("applied_enabled_packs"), list)
        ):
            raise RuntimeError("Ambiguous 058 canonical-contract migration marker")
        if marker["enabled_packs"]["state"] == "present" and "value" not in marker["enabled_packs"]:
            raise RuntimeError("Ambiguous 058 canonical-contract migration marker")
    return marker


def _normalize_pack_list(
    value: Any,
    *,
    path: str,
    require_canonical: bool = False,
) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise RuntimeError(f"{path} must be an array of action-pack identifiers")
    result: list[str] = []
    for raw in value:
        pack_id = raw.strip()
        if pack_id not in ACTION_PACK_IDS:
            raise RuntimeError(f"Unknown action pack at {path}: {pack_id or '<empty>'}")
        if pack_id not in result:
            result.append(pack_id)
    if require_canonical and value != result:
        raise RuntimeError(
            f"Non-canonical action-pack list at {path}; trim and de-duplicate it before migration"
        )
    return result


def _stamp_workspace_contracts(bind) -> None:
    workspaces = sa.table(
        "workspaces",
        sa.column("id", sa.String(length=36)),
        sa.column("slug", sa.String(length=100)),
        sa.column("name", sa.String(length=255)),
        sa.column("settings", sa.JSON()),
    )
    rows = bind.execute(
        sa.select(
            workspaces.c.id,
            workspaces.c.slug,
            workspaces.c.name,
            workspaces.c.settings,
        ).with_for_update()
    ).all()
    for row in rows:
        settings = _as_settings(row._mapping["settings"])
        existing_marker = settings.get(MIGRATION_MARKER_KEY)
        if existing_marker is not None:
            marker = _validate_marker(existing_marker)
            if settings.get("family") != marker["applied_family"]:
                raise RuntimeError("Workspace family marker does not match persisted settings")
            is_andritz = str(row._mapping["slug"] or "").strip().lower() == ANDRITZ_SLUG
            if is_andritz and "applied_enabled_packs" not in marker:
                raise RuntimeError("Andritz migration marker is missing its action-pack backfill")
            if "applied_enabled_packs" in marker:
                actions = settings.get("actions")
                current = actions.get("enabled_packs") if isinstance(actions, dict) else None
                if current != marker["applied_enabled_packs"] or ANDRITZ_ACTION_PACK not in current:
                    raise RuntimeError(
                        "Andritz action-pack backfill marker does not match persisted settings"
                    )
            continue

        raw_family = str(settings.get("family") or "").strip().lower()
        applied_family = (
            raw_family
            if raw_family in WORKSPACE_FAMILIES
            else _legacy_workspace_family(
                row._mapping["slug"],
                row._mapping["name"],
            )
        )
        is_andritz_backfill = str(row._mapping["slug"] or "").strip().lower() == ANDRITZ_SLUG
        marker = _new_workspace_marker(
            settings,
            applied_family=applied_family,
            snapshot_actions=is_andritz_backfill,
        )
        settings["family"] = applied_family
        if is_andritz_backfill:
            actions = (
                deepcopy(settings.get("actions"))
                if isinstance(settings.get("actions"), dict)
                else {}
            )
            raw_packs = actions.get("enabled_packs", [])
            packs = _normalize_pack_list(
                raw_packs,
                path="andritz.settings.actions.enabled_packs",
            )
            if ANDRITZ_ACTION_PACK not in packs:
                packs.append(ANDRITZ_ACTION_PACK)
            actions["enabled_packs"] = packs
            marker["applied_enabled_packs"] = deepcopy(packs)
            settings["actions"] = actions
        settings[MIGRATION_MARKER_KEY] = marker
        bind.execute(
            sa.update(workspaces)
            .where(workspaces.c.id == row._mapping["id"])
            .values(settings=settings)
        )


def _restore_workspace_contracts(bind) -> None:
    workspaces = sa.table(
        "workspaces",
        sa.column("id", sa.String(length=36)),
        sa.column("settings", sa.JSON()),
    )
    rows = bind.execute(sa.select(workspaces.c.id, workspaces.c.settings).with_for_update()).all()
    for row in rows:
        settings = _as_settings(row._mapping["settings"])
        if MIGRATION_MARKER_KEY not in settings:
            continue
        marker = _validate_marker(settings[MIGRATION_MARKER_KEY])
        if settings.get("family") != marker["applied_family"]:
            raise RuntimeError("Refusing to overwrite workspace family changed after migration 058")

        if "applied_enabled_packs" in marker:
            actions = settings.get("actions")
            if (
                not isinstance(actions, dict)
                or actions.get("enabled_packs") != marker["applied_enabled_packs"]
            ):
                raise RuntimeError("Refusing to overwrite action packs changed after migration 058")

            action_snapshot = marker["enabled_packs"]
            if action_snapshot["state"] == "present":
                actions["enabled_packs"] = deepcopy(action_snapshot["value"])
            else:
                actions.pop("enabled_packs", None)

            if marker["actions_container"] == "absent" and not actions:
                settings.pop("actions", None)
            else:
                settings["actions"] = actions

        family_snapshot = marker["family"]
        if family_snapshot["state"] == "present":
            settings["family"] = deepcopy(family_snapshot["value"])
        else:
            settings.pop("family", None)
        settings.pop(MIGRATION_MARKER_KEY, None)
        bind.execute(
            sa.update(workspaces)
            .where(workspaces.c.id == row._mapping["id"])
            .values(settings=settings)
        )


def _audit_enum_column(bind, table_name: str, column_name: str, allowed: tuple[str, ...]) -> None:
    table = sa.table(table_name, sa.column(column_name, sa.String()))
    values = bind.execute(sa.select(table.c[column_name]).distinct()).scalars().all()
    invalid = sorted(repr(value) for value in values if value not in allowed)
    if invalid:
        raise RuntimeError(
            f"Cannot install 058 check for {table_name}.{column_name}; invalid values: "
            + ", ".join(invalid)
        )


def _action_pack_lists(settings: dict[str, Any], *, root: str):
    actions = settings.get("actions")
    if actions is not None:
        if not isinstance(actions, dict):
            raise RuntimeError(f"{root}.actions must be an object")
        for key in ("enabled_packs", "hidden_packs", "action_packs"):
            if key in actions:
                yield actions[key], f"{root}.actions.{key}"

    voice_loop = settings.get("voice_loop")
    if isinstance(voice_loop, dict) and "command_packs" in voice_loop:
        yield voice_loop["command_packs"], f"{root}.voice_loop.command_packs"

    profiles = settings.get("assistant_profiles")
    if isinstance(profiles, list):
        for index, profile in enumerate(profiles):
            if not isinstance(profile, dict):
                continue
            if "action_packs" in profile:
                yield profile["action_packs"], f"{root}.assistant_profiles[{index}].action_packs"
            profile_actions = profile.get("actions")
            if not isinstance(profile_actions, dict):
                continue
            for key in ("enabled_packs", "hidden_packs", "action_packs"):
                if key in profile_actions:
                    yield profile_actions[key], f"{root}.assistant_profiles[{index}].actions.{key}"


def _audit_action_pack_configs(bind) -> None:
    workspaces = sa.table(
        "workspaces",
        sa.column("id", sa.String(length=36)),
        sa.column("settings", sa.JSON()),
    )
    for row in bind.execute(sa.select(workspaces.c.id, workspaces.c.settings)).all():
        settings = _as_settings(row._mapping["settings"])
        for value, path in _action_pack_lists(
            settings,
            root=f"workspaces[{row._mapping['id']}].settings",
        ):
            _normalize_pack_list(value, path=path, require_canonical=True)

    systems = sa.table(
        "systems",
        sa.column("id", sa.String(length=36)),
        sa.column("settings", sa.JSON()),
        sa.column("execution_profile", sa.JSON()),
    )
    for row in bind.execute(
        sa.select(systems.c.id, systems.c.settings, systems.c.execution_profile)
    ).all():
        system_id = row._mapping["id"]
        settings = _as_settings(row._mapping["settings"])
        actions = settings.get("actions")
        if actions is not None:
            if not isinstance(actions, dict):
                raise RuntimeError(f"systems[{system_id}].settings.actions must be an object")
            for key in ("enabled_packs", "hidden_packs", "action_packs"):
                if key in actions:
                    _normalize_pack_list(
                        actions[key],
                        path=f"systems[{system_id}].settings.actions.{key}",
                        require_canonical=True,
                    )
        profile = _as_settings(row._mapping["execution_profile"], allow_none=True)
        if "action_packs" in profile:
            _normalize_pack_list(
                profile["action_packs"],
                path=f"systems[{system_id}].execution_profile.action_packs",
                require_canonical=True,
            )
        profile_actions = profile.get("actions")
        if isinstance(profile_actions, dict):
            for key in ("enabled_packs", "hidden_packs", "action_packs"):
                if key in profile_actions:
                    _normalize_pack_list(
                        profile_actions[key],
                        path=f"systems[{system_id}].execution_profile.actions.{key}",
                        require_canonical=True,
                    )


def _constraint_exists(bind, table_name: str, constraint_name: str) -> bool:
    return constraint_name in {
        item.get("name") for item in sa.inspect(bind).get_check_constraints(table_name)
    }


def _check_sql(column_name: str, allowed: tuple[str, ...]) -> str:
    values = ", ".join(repr(value) for value in allowed)
    return f"{column_name} IN ({values})"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("SET LOCAL lock_timeout = '15s'"))

    constraint_names = (
        ("workspaces", CK_WORKSPACES_MODE),
        ("systems", CK_SYSTEMS_STATUS),
        ("systems", CK_SYSTEMS_EXECUTION_MODE),
        ("workspace_member_app_entitlements", CK_WORKSPACE_APPS),
    )
    collisions = [
        f"{table_name}.{constraint_name}"
        for table_name, constraint_name in constraint_names
        if _constraint_exists(bind, table_name, constraint_name)
    ]
    if collisions:
        raise RuntimeError(
            "Cannot install 058 checks; constraint name collision(s): " + ", ".join(collisions)
        )

    # JSON action packs have no relational CHECK; reject unknown or
    # non-canonical persisted representations before writing migration state.
    _audit_action_pack_configs(bind)
    _stamp_workspace_contracts(bind)

    bind.execute(
        sa.text("UPDATE workspaces SET mode = 'executive' WHERE mode IS NULL OR mode = ''")
    )
    bind.execute(sa.text("UPDATE systems SET status = 'retired' WHERE status = 'archived'"))
    bind.execute(sa.text("UPDATE systems SET status = 'draft' WHERE status IS NULL OR status = ''"))
    bind.execute(
        sa.text(
            "UPDATE systems SET execution_mode = 'real_time_decision' "
            "WHERE execution_mode IS NULL OR execution_mode IN ('', 'real_time')"
        )
    )

    _audit_enum_column(bind, "workspaces", "mode", WORKSPACE_MODES)
    _audit_enum_column(bind, "systems", "status", SYSTEM_STATUSES)
    _audit_enum_column(bind, "systems", "execution_mode", EXECUTION_MODES)
    _audit_enum_column(
        bind,
        "workspace_member_app_entitlements",
        "app_key",
        WORKSPACE_APPS,
    )
    with op.batch_alter_table("workspaces") as batch:
        batch.alter_column(
            "mode",
            existing_type=sa.String(length=32),
            nullable=False,
            server_default=sa.text("'executive'"),
        )
        batch.create_check_constraint(
            CK_WORKSPACES_MODE,
            _check_sql("mode", WORKSPACE_MODES),
        )

    with op.batch_alter_table("systems") as batch:
        batch.alter_column(
            "status",
            existing_type=sa.String(length=20),
            nullable=False,
            server_default=sa.text("'draft'"),
        )
        batch.alter_column(
            "execution_mode",
            existing_type=sa.String(length=40),
            nullable=False,
            server_default=sa.text("'real_time_decision'"),
        )
        batch.create_check_constraint(
            CK_SYSTEMS_STATUS,
            _check_sql("status", SYSTEM_STATUSES),
        )
        batch.create_check_constraint(
            CK_SYSTEMS_EXECUTION_MODE,
            _check_sql("execution_mode", EXECUTION_MODES),
        )

    with op.batch_alter_table("workspace_member_app_entitlements") as batch:
        batch.create_check_constraint(
            CK_WORKSPACE_APPS,
            _check_sql("app_key", WORKSPACE_APPS),
        )


def downgrade() -> None:
    bind = op.get_bind()

    if _constraint_exists(bind, "workspace_member_app_entitlements", CK_WORKSPACE_APPS):
        with op.batch_alter_table("workspace_member_app_entitlements") as batch:
            batch.drop_constraint(CK_WORKSPACE_APPS, type_="check")

    system_status_exists = _constraint_exists(bind, "systems", CK_SYSTEMS_STATUS)
    system_mode_exists = _constraint_exists(bind, "systems", CK_SYSTEMS_EXECUTION_MODE)
    with op.batch_alter_table("systems") as batch:
        if system_mode_exists:
            batch.drop_constraint(CK_SYSTEMS_EXECUTION_MODE, type_="check")
        if system_status_exists:
            batch.drop_constraint(CK_SYSTEMS_STATUS, type_="check")
        batch.alter_column(
            "status",
            existing_type=sa.String(length=20),
            nullable=True,
            server_default=sa.text("'draft'"),
        )
        batch.alter_column(
            "execution_mode",
            existing_type=sa.String(length=40),
            nullable=True,
            server_default=sa.text("'real_time'"),
        )

    workspace_mode_exists = _constraint_exists(bind, "workspaces", CK_WORKSPACES_MODE)
    with op.batch_alter_table("workspaces") as batch:
        if workspace_mode_exists:
            batch.drop_constraint(CK_WORKSPACES_MODE, type_="check")
        batch.alter_column(
            "mode",
            existing_type=sa.String(length=32),
            nullable=False,
            server_default=sa.text("'executive'"),
        )

    _restore_workspace_contracts(bind)
