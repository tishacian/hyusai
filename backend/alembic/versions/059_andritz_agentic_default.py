"""Stage the Andritz Agentic chat runtime behind a zero-percent rollout.

Only workspaces whose persisted family is ``andritz`` and which own exactly
one active canonical Agentic chat System are changed.  The public chat surface
therefore remains on the classic runtime after this migration; operators can
exercise the Agentic System explicitly before increasing the rollout.

The Agentic System is also given an authoritative retrieval contract for the
SPL notices collection, mirrored into its bound ControlPolicy membrane as a
defence-in-depth inbound allowlist.  Every field owned by this migration is
snapshotted individually so downgrade restores it without replacing unrelated
workspace, System or ControlPolicy settings added later.

Revision ID: 059_andritz_agentic_default
Revises: 058_canonical_contracts
Create Date: 2026-07-16
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "059_andritz_agentic_default"
down_revision = "058_canonical_contracts"
branch_labels = None
depends_on = None


MIGRATION_MARKER_KEY = "_migration_059_andritz_agentic_default_state"
MIGRATION_MARKER_SCHEMA = 1
AGENTIC_SYSTEM_TYPE = "chat_agentic"
AGENTIC_VARIANT = "chat_agentic_thinking_v1"
EXPECTED_FLOW_REVISION = "056_andritz_chat_asset_binding"
NOTICES_COLLECTION = "andritz-notices-techniques-spl-pilot"
EXPECTED_FLOW_CONTRACT_SHA256 = "6780628580346fb97c7112e86e7492fb31abc688329b7d72cd81afecf75c762a"
_INSTALLATION_OR_COSMETIC_CONFIG_KEYS = frozenset({"skill_id", "params_note"})

# Alembic revisions must remain replayable after application contracts evolve.
# Keep the exact 056 graph identity frozen here instead of importing runtime
# helpers that a later release may legitimately advance to another revision.

CHAT_EXECUTION_POLICY = {
    "version": 1,
    "mode": "agentic_default",
    "target": {
        "system_type": AGENTIC_SYSTEM_TYPE,
        "variant": AGENTIC_VARIANT,
    },
    "fallback": "classic",
    "rollout": {
        "percentage": 0,
        "salt": "andritz-agentic-v1",
    },
}

RETRIEVAL_CONTRACT = {
    "collection": NOTICES_COLLECTION,
    "asset_binding": "authoritative",
    "empty_bound_collection": "abstain",
    "allow_workspace_fallback": False,
}


def _as_settings(value: Any, *, path: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return deepcopy(value)
    raise RuntimeError(f"{path} must be a JSON object")


def _as_flow(value: Any) -> dict[str, Any]:
    return deepcopy(value) if isinstance(value, dict) else {}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _contract_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _contract_value(item)
            for key, item in value.items()
            if key not in _INSTALLATION_OR_COSMETIC_CONFIG_KEYS
        }
    if isinstance(value, list):
        return [_contract_value(item) for item in value]
    return value


def _flow_contract_digest(flow_definition: Any) -> str | None:
    flow = _mapping(flow_definition)
    raw_nodes = flow.get("nodes")
    raw_edges = flow.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        return None
    if not all(isinstance(node, Mapping) for node in raw_nodes) or not all(
        isinstance(edge, Mapping) for edge in raw_edges
    ):
        return None
    canonical = {
        "variant": flow.get("variant"),
        "nodes": [
            {
                "id": node.get("id"),
                "kind": node.get("kind"),
                "config": _contract_value(node.get("config") or {}),
            }
            for node in raw_nodes
        ],
        "edges": [
            {
                "from": edge.get("from"),
                "to": edge.get("to"),
                "kind": edge.get("kind"),
                "branch_label": edge.get("branch_label"),
            }
            for edge in raw_edges
        ],
    }
    try:
        payload = json.dumps(
            canonical,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(payload).hexdigest()


def _is_expected_agentic_flow(settings: Any, flow_definition: Any) -> bool:
    """Frozen structural identity for the 056 graph consumed by revision 059."""

    system_settings = _mapping(settings)
    if (
        system_settings.get("system_type") != AGENTIC_SYSTEM_TYPE
        or system_settings.get("flow_revision") != EXPECTED_FLOW_REVISION
    ):
        return False
    return _flow_contract_digest(flow_definition) == EXPECTED_FLOW_CONTRACT_SHA256


def _field_snapshot(container: dict[str, Any], key: str) -> dict[str, Any]:
    if key not in container:
        return {"state": "absent"}
    return {"state": "present", "value": deepcopy(container[key])}


def _restore_field(
    container: dict[str, Any],
    key: str,
    snapshot: dict[str, Any],
) -> None:
    if not isinstance(snapshot, dict) or snapshot.get("state") not in {
        "absent",
        "present",
    }:
        raise RuntimeError(f"Ambiguous 059 snapshot for {key}")
    if snapshot["state"] == "present":
        if "value" not in snapshot:
            raise RuntimeError(f"Ambiguous 059 snapshot for {key}")
        container[key] = deepcopy(snapshot["value"])
    else:
        container.pop(key, None)


def _tables():
    workspaces = sa.table(
        "workspaces",
        sa.column("id", sa.String(length=36)),
        sa.column("settings", sa.JSON()),
    )
    systems = sa.table(
        "systems",
        sa.column("id", sa.String(length=36)),
        sa.column("workspace_id", sa.String(length=36)),
        sa.column("status", sa.String(length=20)),
        sa.column("settings", sa.JSON()),
        sa.column("flow_definition", sa.JSON()),
        sa.column("execution_profile", sa.JSON()),
        sa.column("control_policy_id", sa.String(length=36)),
    )
    control_policies = sa.table(
        "control_policies",
        sa.column("id", sa.String(length=36)),
        sa.column("workspace_id", sa.String(length=36)),
        sa.column("scope", sa.String(length=32)),
        sa.column("target_id", sa.String(length=36)),
        sa.column("extra", sa.JSON()),
    )
    return workspaces, systems, control_policies


def _is_agentic_target(row: Any) -> bool:
    return _is_expected_agentic_flow(
        row._mapping["settings"],
        row._mapping["flow_definition"],
    )


def _target_for_workspace(bind, systems, workspace_id: str):
    rows = bind.execute(
        sa.select(
            systems.c.id,
            systems.c.settings,
            systems.c.flow_definition,
            systems.c.execution_profile,
            systems.c.control_policy_id,
        )
        .where(
            systems.c.workspace_id == workspace_id,
            systems.c.status == "active",
        )
        .with_for_update()
    ).all()
    targets = [row for row in rows if _is_agentic_target(row)]
    if len(targets) > 1:
        raise RuntimeError(
            f"Workspace {workspace_id} has multiple active canonical Agentic chat Systems"
        )
    return targets[0] if targets else None


def _membrane_parts(extra: Any, *, policy_id: str):
    if not isinstance(extra, dict):
        raise RuntimeError(f"ControlPolicy {policy_id}.extra must be a JSON object")
    copied_extra = deepcopy(extra)
    membrane_spec = copied_extra.get("membrane_spec")
    if not isinstance(membrane_spec, dict):
        raise RuntimeError(f"ControlPolicy {policy_id} has no authoritative membrane_spec")
    raw_inbound = membrane_spec.get("inbound")
    if raw_inbound is not None and not isinstance(raw_inbound, dict):
        raise RuntimeError(
            f"ControlPolicy {policy_id}.extra.membrane_spec.inbound must be an object"
        )
    inbound = deepcopy(raw_inbound) if isinstance(raw_inbound, dict) else {}
    return (
        copied_extra,
        membrane_spec,
        inbound,
        ("mapping" if isinstance(raw_inbound, dict) else "absent"),
    )


def _policy_for_target(bind, control_policies, target, *, workspace_id: str):
    policy_id = target._mapping["control_policy_id"]
    if not isinstance(policy_id, str) or not policy_id:
        raise RuntimeError(f"Agentic System {target._mapping['id']} has no bound ControlPolicy")
    policy = bind.execute(
        sa.select(
            control_policies.c.id,
            control_policies.c.workspace_id,
            control_policies.c.scope,
            control_policies.c.target_id,
            control_policies.c.extra,
        )
        .where(
            control_policies.c.id == policy_id,
            control_policies.c.workspace_id == workspace_id,
            control_policies.c.scope == "system",
            control_policies.c.target_id == target._mapping["id"],
        )
        .with_for_update()
    ).first()
    if policy is None:
        raise RuntimeError(
            f"Bound ControlPolicy {policy_id} is not an authoritative policy "
            f"for Agentic System {target._mapping['id']} in workspace {workspace_id}"
        )
    return policy


def _new_marker(
    workspace_settings: dict[str, Any],
    *,
    system_id: str,
    system_settings: dict[str, Any],
    execution_profile: Any,
    control_policy_id: str,
    control_policy_extra: dict[str, Any],
) -> dict[str, Any]:
    profile = deepcopy(execution_profile) if isinstance(execution_profile, dict) else {}
    _, _, inbound, inbound_container = _membrane_parts(
        control_policy_extra,
        policy_id=control_policy_id,
    )
    return {
        "revision": revision,
        "schema": MIGRATION_MARKER_SCHEMA,
        "system_id": system_id,
        "workspace": {
            "chat_execution": _field_snapshot(workspace_settings, "chat_execution"),
        },
        "system": {
            "retrieval_contract": _field_snapshot(system_settings, "retrieval_contract"),
            "execution_profile": {
                "container": "mapping" if isinstance(execution_profile, dict) else "null",
                "max_runtime_s": _field_snapshot(profile, "max_runtime_s"),
            },
        },
        "control_policy": {
            "id": control_policy_id,
            "inbound_container": inbound_container,
            "collection_allowlist": _field_snapshot(
                inbound,
                "collection_allowlist",
            ),
        },
        "applied": {
            "chat_execution": deepcopy(CHAT_EXECUTION_POLICY),
            "retrieval_contract": deepcopy(RETRIEVAL_CONTRACT),
            "execution_profile_max_runtime_s": 40,
            "collection_allowlist": [NOTICES_COLLECTION],
            "flow_revision": EXPECTED_FLOW_REVISION,
        },
    }


def _validate_marker(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError("Ambiguous 059 Andritz Agentic rollout marker")
    workspace = value.get("workspace")
    system = value.get("system")
    control_policy = value.get("control_policy")
    applied = value.get("applied")
    if (
        value.get("revision") != revision
        or value.get("schema") != MIGRATION_MARKER_SCHEMA
        or not isinstance(value.get("system_id"), str)
        or not isinstance(workspace, dict)
        or not isinstance(system, dict)
        or not isinstance(control_policy, dict)
        or not isinstance(applied, dict)
        or "chat_execution" not in workspace
        or "retrieval_contract" not in system
        or not isinstance(system.get("execution_profile"), dict)
        or system["execution_profile"].get("container") not in {"null", "mapping"}
        or "max_runtime_s" not in system["execution_profile"]
        or not isinstance(control_policy.get("id"), str)
        or control_policy.get("inbound_container") not in {"absent", "mapping"}
        or "collection_allowlist" not in control_policy
        or applied.get("chat_execution") != CHAT_EXECUTION_POLICY
        or applied.get("retrieval_contract") != RETRIEVAL_CONTRACT
        or applied.get("execution_profile_max_runtime_s") != 40
        or applied.get("collection_allowlist") != [NOTICES_COLLECTION]
        or applied.get("flow_revision") != EXPECTED_FLOW_REVISION
    ):
        raise RuntimeError("Ambiguous 059 Andritz Agentic rollout marker")
    # Validate field snapshots before any write occurs.
    probe: dict[str, Any] = {}
    _restore_field(probe, "chat_execution", workspace["chat_execution"])
    _restore_field(probe, "retrieval_contract", system["retrieval_contract"])
    _restore_field(
        probe,
        "max_runtime_s",
        system["execution_profile"]["max_runtime_s"],
    )
    _restore_field(
        probe,
        "collection_allowlist",
        control_policy["collection_allowlist"],
    )
    return value


def _assert_applied_state(
    *,
    workspace_settings: dict[str, Any],
    system_settings: dict[str, Any],
    flow_definition: Any,
    execution_profile: Any,
    control_policy_id: Any,
    expected_control_policy_id: str,
    control_policy_extra: Any,
) -> None:
    current_policy = deepcopy(workspace_settings.get("chat_execution"))
    expected_policy = deepcopy(CHAT_EXECUTION_POLICY)
    current_rollout = current_policy.get("rollout") if isinstance(current_policy, dict) else None
    expected_rollout = expected_policy["rollout"]
    if isinstance(current_rollout, dict):
        percentage = current_rollout.get("percentage")
        try:
            percentage_is_valid = 0 <= float(percentage) <= 100
        except (TypeError, ValueError):
            percentage_is_valid = False
        current_rollout["percentage"] = 0
    else:
        percentage_is_valid = False
    expected_rollout["percentage"] = 0
    # The rollout percentage is deliberately mutable after the zero-percent
    # migration.  Every structural policy field remains protected.
    if not percentage_is_valid or current_policy != expected_policy:
        raise RuntimeError("Andritz chat execution policy changed after migration 059")
    if system_settings.get("retrieval_contract") != RETRIEVAL_CONTRACT:
        raise RuntimeError("Andritz retrieval contract changed after migration 059")
    if not _is_expected_agentic_flow(system_settings, flow_definition):
        raise RuntimeError("Andritz Agentic flow contract changed after migration 059")
    if not isinstance(execution_profile, dict) or execution_profile.get("max_runtime_s") != 40:
        raise RuntimeError("Andritz Agentic runtime limit changed after migration 059")
    if control_policy_id != expected_control_policy_id:
        raise RuntimeError("Andritz Agentic ControlPolicy binding changed after migration 059")
    _, _, inbound, _ = _membrane_parts(
        control_policy_extra,
        policy_id=expected_control_policy_id,
    )
    if inbound.get("collection_allowlist") != [NOTICES_COLLECTION]:
        raise RuntimeError("Andritz membrane collection allowlist changed after migration 059")


def _apply_andritz_defaults(bind) -> None:
    workspaces, systems, control_policies = _tables()
    rows = bind.execute(sa.select(workspaces.c.id, workspaces.c.settings).with_for_update()).all()
    for row in rows:
        workspace_id = row._mapping["id"]
        if not isinstance(row._mapping["settings"], dict):
            # Unrelated legacy/null settings rows are not Andritz targets and
            # must not block a fleet migration.
            continue
        workspace_settings = _as_settings(
            row._mapping["settings"],
            path=f"workspace {workspace_id}.settings",
        )
        if workspace_settings.get("family") != "andritz":
            continue

        existing_marker = workspace_settings.get(MIGRATION_MARKER_KEY)
        if existing_marker is not None:
            marker = _validate_marker(existing_marker)
            target = bind.execute(
                sa.select(
                    systems.c.id,
                    systems.c.workspace_id,
                    systems.c.status,
                    systems.c.settings,
                    systems.c.flow_definition,
                    systems.c.execution_profile,
                    systems.c.control_policy_id,
                )
                .where(
                    systems.c.id == marker["system_id"],
                    systems.c.workspace_id == workspace_id,
                    systems.c.status == "active",
                )
                .with_for_update()
            ).first()
            if target is None:
                raise RuntimeError(
                    "Agentic System recorded by migration 059 is no longer an active "
                    "target in its Andritz workspace"
                )
            if not _is_agentic_target(target):
                raise RuntimeError(
                    "Agentic System recorded by migration 059 changed canonical identity"
                )
            policy = bind.execute(
                sa.select(control_policies.c.id, control_policies.c.extra)
                .where(
                    control_policies.c.id == marker["control_policy"]["id"],
                    control_policies.c.workspace_id == workspace_id,
                    control_policies.c.scope == "system",
                    control_policies.c.target_id == marker["system_id"],
                )
                .with_for_update()
            ).first()
            if policy is None:
                raise RuntimeError("ControlPolicy recorded by migration 059 no longer exists")
            _assert_applied_state(
                workspace_settings=workspace_settings,
                system_settings=_as_settings(
                    target._mapping["settings"],
                    path=f"system {marker['system_id']}.settings",
                ),
                flow_definition=target._mapping["flow_definition"],
                execution_profile=target._mapping["execution_profile"],
                control_policy_id=target._mapping["control_policy_id"],
                expected_control_policy_id=marker["control_policy"]["id"],
                control_policy_extra=policy._mapping["extra"],
            )
            continue

        target = _target_for_workspace(bind, systems, workspace_id)
        # Family-only workspaces without the canonical graph remain safely on
        # classic chat and can be configured when their graph is provisioned.
        if target is None:
            continue

        system_id = target._mapping["id"]
        system_settings = _as_settings(
            target._mapping["settings"],
            path=f"system {system_id}.settings",
        )
        raw_profile = target._mapping["execution_profile"]
        if raw_profile is not None and not isinstance(raw_profile, dict):
            raise RuntimeError(f"system {system_id}.execution_profile must be a JSON object")
        execution_profile = deepcopy(raw_profile) if isinstance(raw_profile, dict) else {}
        policy = _policy_for_target(
            bind,
            control_policies,
            target,
            workspace_id=workspace_id,
        )
        policy_id = policy._mapping["id"]
        policy_extra, membrane_spec, inbound, _ = _membrane_parts(
            policy._mapping["extra"],
            policy_id=policy_id,
        )
        marker = _new_marker(
            workspace_settings,
            system_id=system_id,
            system_settings=system_settings,
            execution_profile=raw_profile,
            control_policy_id=policy_id,
            control_policy_extra=policy._mapping["extra"],
        )

        system_settings["retrieval_contract"] = deepcopy(RETRIEVAL_CONTRACT)
        execution_profile["max_runtime_s"] = 40
        inbound["collection_allowlist"] = [NOTICES_COLLECTION]
        membrane_spec["inbound"] = inbound
        policy_extra["membrane_spec"] = membrane_spec
        workspace_settings["chat_execution"] = deepcopy(CHAT_EXECUTION_POLICY)
        workspace_settings[MIGRATION_MARKER_KEY] = marker

        bind.execute(
            sa.update(systems)
            .where(systems.c.id == system_id)
            .values(
                settings=system_settings,
                execution_profile=execution_profile,
            )
        )
        bind.execute(
            sa.update(control_policies)
            .where(control_policies.c.id == policy_id)
            .values(extra=policy_extra)
        )
        bind.execute(
            sa.update(workspaces)
            .where(workspaces.c.id == workspace_id)
            .values(settings=workspace_settings)
        )


def _restore_andritz_defaults(bind) -> None:
    workspaces, systems, control_policies = _tables()
    rows = bind.execute(sa.select(workspaces.c.id, workspaces.c.settings).with_for_update()).all()
    for row in rows:
        workspace_id = row._mapping["id"]
        if not isinstance(row._mapping["settings"], dict):
            continue
        workspace_settings = _as_settings(
            row._mapping["settings"],
            path=f"workspace {workspace_id}.settings",
        )
        if MIGRATION_MARKER_KEY not in workspace_settings:
            continue
        marker = _validate_marker(workspace_settings[MIGRATION_MARKER_KEY])
        system_id = marker["system_id"]
        target = bind.execute(
            sa.select(
                systems.c.id,
                systems.c.workspace_id,
                systems.c.settings,
                systems.c.flow_definition,
                systems.c.execution_profile,
                systems.c.control_policy_id,
            )
            .where(
                systems.c.id == system_id,
                systems.c.workspace_id == workspace_id,
            )
            .with_for_update()
        ).first()
        if target is None:
            raise RuntimeError(
                "Cannot restore migration 059: Agentic System is missing from its workspace"
            )
        if not _is_agentic_target(target):
            raise RuntimeError(
                "Cannot restore migration 059: Agentic System changed canonical identity"
            )
        policy_id = marker["control_policy"]["id"]
        policy = bind.execute(
            sa.select(control_policies.c.id, control_policies.c.extra)
            .where(
                control_policies.c.id == policy_id,
                control_policies.c.workspace_id == workspace_id,
                control_policies.c.scope == "system",
                control_policies.c.target_id == system_id,
            )
            .with_for_update()
        ).first()
        if policy is None:
            raise RuntimeError("Cannot restore migration 059: ControlPolicy is missing")

        system_settings = _as_settings(
            target._mapping["settings"],
            path=f"system {system_id}.settings",
        )
        _assert_applied_state(
            workspace_settings=workspace_settings,
            system_settings=system_settings,
            flow_definition=target._mapping["flow_definition"],
            execution_profile=target._mapping["execution_profile"],
            control_policy_id=target._mapping["control_policy_id"],
            expected_control_policy_id=policy_id,
            control_policy_extra=policy._mapping["extra"],
        )

        _restore_field(
            workspace_settings,
            "chat_execution",
            marker["workspace"]["chat_execution"],
        )
        _restore_field(
            system_settings,
            "retrieval_contract",
            marker["system"]["retrieval_contract"],
        )
        current_profile = target._mapping["execution_profile"]
        if not isinstance(current_profile, dict):
            raise RuntimeError("Cannot restore migration 059: execution profile is invalid")
        restored_profile = deepcopy(current_profile)
        profile_snapshot = marker["system"]["execution_profile"]
        _restore_field(
            restored_profile,
            "max_runtime_s",
            profile_snapshot["max_runtime_s"],
        )
        if profile_snapshot["container"] == "null" and not restored_profile:
            restored_profile = None

        policy_extra, membrane_spec, inbound, _ = _membrane_parts(
            policy._mapping["extra"],
            policy_id=policy_id,
        )
        _restore_field(
            inbound,
            "collection_allowlist",
            marker["control_policy"]["collection_allowlist"],
        )
        if marker["control_policy"]["inbound_container"] == "absent" and not inbound:
            membrane_spec.pop("inbound", None)
        else:
            membrane_spec["inbound"] = inbound
        policy_extra["membrane_spec"] = membrane_spec
        workspace_settings.pop(MIGRATION_MARKER_KEY, None)

        bind.execute(
            sa.update(systems)
            .where(systems.c.id == system_id)
            .values(
                settings=system_settings,
                execution_profile=restored_profile,
            )
        )
        bind.execute(
            sa.update(control_policies)
            .where(control_policies.c.id == policy_id)
            .values(extra=policy_extra)
        )
        bind.execute(
            sa.update(workspaces)
            .where(workspaces.c.id == workspace_id)
            .values(settings=workspace_settings)
        )


def upgrade() -> None:
    bind = op.get_bind()
    if not {"workspaces", "systems", "control_policies"}.issubset(
        sa.inspect(bind).get_table_names()
    ):
        return
    _apply_andritz_defaults(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if not {"workspaces", "systems", "control_policies"}.issubset(
        sa.inspect(bind).get_table_names()
    ):
        return
    _restore_andritz_defaults(bind)
