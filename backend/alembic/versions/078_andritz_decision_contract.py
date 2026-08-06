"""Upgrade the canonical Andritz graph to the explicit Decision contract.

Revision ID: 078_andritz_decision_contract
Revises: 077_flow_publication_v1

Migration 077 freezes every legacy ``systems.flow_definition`` behind an
immutable published pointer.  This data migration therefore updates the
canonical Andritz graph and that pointer in one transaction.  It never edits a
version in place and it leaves operator-authored or otherwise drifted graphs
untouched, which makes the chat router fail closed to the classic runtime.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "078_andritz_decision_contract"
down_revision = "077_flow_publication_v1"
branch_labels = None
depends_on = None

OLD_FLOW_REVISION = "056_andritz_chat_asset_binding"
NEW_FLOW_REVISION = revision
OLD_CONTRACT_SHA256 = "6780628580346fb97c7112e86e7492fb31abc688329b7d72cd81afecf75c762a"
NEW_CONTRACT_SHA256 = "55611adbfba8848376c567b1be13ca39b2a5c5b008cd78548b7cbf40b077c4a5"
ROLLOUT_MARKER = "_migration_059_andritz_agentic_default_state"
STATE_KEY = "_migration_078_andritz_decision_contract_state"
SYSTEM_TYPE = "chat_agentic"
VARIANT = "chat_agentic_thinking_v1"
_IGNORED_CONFIG_KEYS = frozenset({"skill_id", "params_note"})
_ARTIFACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "resources"
    / "flows"
    / "andritz_chat_agentic_v3.json"
)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _contract_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _contract_value(item)
            for key, item in value.items()
            if key not in _IGNORED_CONFIG_KEYS
        }
    if isinstance(value, list):
        return [_contract_value(item) for item in value]
    return value


def _contract_sha256(flow_definition: Any) -> str | None:
    flow = _as_dict(flow_definition)
    nodes = flow.get("nodes")
    edges = flow.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return None
    if not all(isinstance(node, Mapping) for node in nodes):
        return None
    if not all(isinstance(edge, Mapping) for edge in edges):
        return None
    canonical = {
        "variant": flow.get("variant"),
        "nodes": [
            {
                "id": node.get("id"),
                "kind": node.get("kind"),
                "config": _contract_value(node.get("config") or {}),
            }
            for node in nodes
        ],
        "edges": [
            {
                "from": edge.get("from"),
                "to": edge.get("to"),
                "kind": edge.get("kind"),
                "branch_label": edge.get("branch_label"),
            }
            for edge in edges
        ],
    }
    try:
        encoded = json.dumps(
            canonical,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def _flow_sha256(flow: Mapping[str, Any]) -> str:
    encoded = json.dumps(flow, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _load_flow() -> dict[str, Any]:
    with _ARTIFACT_PATH.open("r", encoding="utf-8") as handle:
        artifact = json.load(handle)
    flow = _as_dict(_as_dict(artifact).get("flow_definition"))
    if _contract_sha256(flow) != NEW_CONTRACT_SHA256:
        raise RuntimeError("Migration 078 artifact does not match its pinned contract digest")
    return flow


def _tables():
    workspaces = sa.table(
        "workspaces",
        sa.column("id"),
        sa.column("settings", sa.JSON()),
    )
    systems = sa.table(
        "systems",
        sa.column("id"),
        sa.column("workspace_id"),
        sa.column("settings", sa.JSON()),
        sa.column("flow_definition", sa.JSON()),
        sa.column("published_flow_version_id"),
        sa.column("published_by"),
        sa.column("published_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    versions = sa.table(
        "system_versions",
        sa.column("id"),
        sa.column("system_id"),
        sa.column("workspace_id"),
        sa.column("version_number", sa.Integer()),
        sa.column("flow_definition", sa.JSON()),
        sa.column("configuration_snapshot", sa.JSON()),
        sa.column("message"),
        sa.column("rolled_back_from_id"),
        sa.column("created_at", sa.DateTime()),
        sa.column("created_by"),
        sa.column("flow_sha256"),
        sa.column("release_kind"),
        sa.column("draft_revision", sa.Integer()),
        sa.column("execution_contract", sa.JSON()),
    )
    drafts = sa.table(
        "system_flow_drafts",
        sa.column("system_id"),
        sa.column("workspace_id"),
        sa.column("flow_definition", sa.JSON()),
        sa.column("revision", sa.Integer()),
        sa.column("flow_sha256"),
        sa.column("base_published_version_id"),
        sa.column("updated_by"),
        sa.column("updated_at", sa.DateTime()),
    )
    return workspaces, systems, versions, drafts


def _target_id(workspace_settings: Mapping[str, Any]) -> str | None:
    marker = _as_dict(workspace_settings.get(ROLLOUT_MARKER))
    system_id = marker.get("system_id")
    if (
        marker.get("revision") != "059_andritz_agentic_default"
        or marker.get("schema") != 1
        or not isinstance(system_id, str)
        or not system_id
    ):
        return None
    return system_id


def _update_rollout_marker(
    settings: dict[str, Any],
    *,
    expected_system_id: str,
    flow_revision: str,
) -> dict[str, Any]:
    marker = _as_dict(settings.get(ROLLOUT_MARKER))
    if marker.get("system_id") != expected_system_id:
        raise RuntimeError("Migration 078 refuses a mismatched Andritz rollout marker")
    applied = _as_dict(marker.get("applied"))
    current = applied.get("flow_revision")
    if current not in {OLD_FLOW_REVISION, NEW_FLOW_REVISION}:
        raise RuntimeError("Migration 078 refuses rollout-marker flow revision drift")
    applied["flow_revision"] = flow_revision
    marker["applied"] = applied
    settings[ROLLOUT_MARKER] = marker
    return settings


def _owned_version(bind: Any, versions: Any, system_id: str, version_id: str | None):
    if not version_id:
        return None
    return bind.execute(
        sa.select(versions).where(
            versions.c.id == version_id,
            versions.c.system_id == system_id,
        )
    ).mappings().one_or_none()


def _exact_version(bind: Any, versions: Any, system_id: str, flow: Mapping[str, Any]):
    expected = json.dumps(flow, sort_keys=True, separators=(",", ":"))
    candidates = bind.execute(
        sa.select(versions)
        .where(versions.c.system_id == system_id)
        .order_by(versions.c.version_number.desc())
    ).mappings()
    return next(
        (
            row
            for row in candidates
            if json.dumps(
                _as_dict(row["flow_definition"]),
                sort_keys=True,
                separators=(",", ":"),
            )
            == expected
        ),
        None,
    )


def _upgrade_target(
    bind: Any,
    *,
    workspace_row: Mapping[str, Any],
    system_row: Mapping[str, Any],
    new_flow: Mapping[str, Any],
    workspaces: Any,
    systems: Any,
    versions: Any,
    drafts: Any,
    now: datetime,
) -> None:
    system_id = str(system_row["id"])
    old_flow = _as_dict(system_row["flow_definition"])
    old_contract = _contract_sha256(old_flow)
    if old_contract not in {OLD_CONTRACT_SHA256, NEW_CONTRACT_SHA256}:
        # Never overwrite an operator-authored or otherwise drifted graph.
        return

    system_settings = _as_dict(system_row["settings"])
    state = _as_dict(system_settings.get(STATE_KEY))
    if state:
        if (
            state.get("revision") != NEW_FLOW_REVISION
            or state.get("schema") != 1
            or old_contract != NEW_CONTRACT_SHA256
        ):
            raise RuntimeError("Migration 078 state or canonical graph has drifted")
        return
    if system_settings.get("system_type") != SYSTEM_TYPE:
        return
    if system_settings.get("flow_revision") != OLD_FLOW_REVISION:
        raise RuntimeError("Migration 078 refuses System flow revision drift")

    old_pointer = system_row["published_flow_version_id"]
    old_version = _owned_version(bind, versions, system_id, old_pointer)
    if old_version is None:
        raise RuntimeError("Migration 078 requires migration 077 published evidence")
    if _flow_sha256(_as_dict(old_version["flow_definition"])) != _flow_sha256(old_flow):
        raise RuntimeError("Migration 078 refuses a drifted published Flow mirror")

    graph_changed = old_contract == OLD_CONTRACT_SHA256
    target_flow = deepcopy(dict(new_flow)) if graph_changed else old_flow
    exact = _exact_version(bind, versions, system_id, target_flow)
    draft = bind.execute(
        sa.select(drafts).where(drafts.c.system_id == system_id)
    ).mappings().one_or_none()
    draft_revision = int(draft["revision"]) if draft is not None else None
    if exact is None:
        latest_number = bind.execute(
            sa.select(sa.func.max(versions.c.version_number)).where(
                versions.c.system_id == system_id
            )
        ).scalar_one()
        new_pointer = str(uuid4())
        bind.execute(
            versions.insert().values(
                id=new_pointer,
                system_id=system_id,
                workspace_id=system_row["workspace_id"],
                version_number=int(latest_number or 0) + 1,
                flow_definition=target_flow,
                configuration_snapshot=None,
                message="Migration 078 explicit Decision contract",
                rolled_back_from_id=None,
                created_at=now,
                created_by="migration-078",
                flow_sha256=_flow_sha256(target_flow),
                release_kind="migration",
                draft_revision=draft_revision,
                execution_contract=None,
            )
        )
    else:
        new_pointer = str(exact["id"])

    draft_upgraded = False
    if draft is not None and graph_changed:
        draft_flow = _as_dict(draft["flow_definition"])
        if (
            _flow_sha256(draft_flow) == _flow_sha256(old_flow)
            and draft["base_published_version_id"] == old_pointer
        ):
            bind.execute(
                drafts.update()
                .where(drafts.c.system_id == system_id)
                .values(
                    flow_definition=target_flow,
                    revision=int(draft["revision"]) + 1,
                    flow_sha256=_flow_sha256(target_flow),
                    base_published_version_id=new_pointer,
                    updated_by="migration-078",
                    updated_at=now,
                )
            )
            draft_upgraded = True

    system_settings["flow_revision"] = NEW_FLOW_REVISION
    system_settings[STATE_KEY] = {
        "schema": 1,
        "revision": NEW_FLOW_REVISION,
        "old_flow_revision": OLD_FLOW_REVISION,
        "old_contract_sha256": old_contract,
        "new_contract_sha256": NEW_CONTRACT_SHA256,
        "old_published_version_id": old_pointer,
        "new_published_version_id": new_pointer,
        "graph_changed": graph_changed,
        "draft_upgraded": draft_upgraded,
    }
    bind.execute(
        systems.update()
        .where(systems.c.id == system_id)
        .values(
            settings=system_settings,
            flow_definition=target_flow,
            published_flow_version_id=new_pointer,
            published_by="migration-078",
            published_at=now,
            updated_at=now,
        )
    )
    workspace_settings = _update_rollout_marker(
        _as_dict(workspace_row["settings"]),
        expected_system_id=system_id,
        flow_revision=NEW_FLOW_REVISION,
    )
    bind.execute(
        workspaces.update()
        .where(workspaces.c.id == workspace_row["id"])
        .values(settings=workspace_settings)
    )


def _upgrade(bind: Any) -> None:
    new_flow = _load_flow()
    workspaces, systems, versions, drafts = _tables()
    now = datetime.utcnow()
    for workspace_row in bind.execute(sa.select(workspaces)).mappings():
        target_id = _target_id(_as_dict(workspace_row["settings"]))
        if target_id is None:
            continue
        system_row = bind.execute(
            sa.select(systems).where(
                systems.c.id == target_id,
                systems.c.workspace_id == workspace_row["id"],
            )
        ).mappings().one_or_none()
        if system_row is None:
            raise RuntimeError("Migration 078 rollout marker target is missing or cross-tenant")
        _upgrade_target(
            bind,
            workspace_row=workspace_row,
            system_row=system_row,
            new_flow=new_flow,
            workspaces=workspaces,
            systems=systems,
            versions=versions,
            drafts=drafts,
            now=now,
        )


def _downgrade(bind: Any) -> None:
    workspaces, systems, versions, drafts = _tables()
    now = datetime.utcnow()
    rows = bind.execute(sa.select(systems)).mappings().all()
    for system_row in rows:
        system_settings = _as_dict(system_row["settings"])
        state = _as_dict(system_settings.get(STATE_KEY))
        if not state:
            continue
        if (
            state.get("schema") != 1
            or state.get("revision") != NEW_FLOW_REVISION
            or system_settings.get("flow_revision") != NEW_FLOW_REVISION
            or _contract_sha256(system_row["flow_definition"]) != NEW_CONTRACT_SHA256
            or system_row["published_flow_version_id"]
            != state.get("new_published_version_id")
        ):
            raise RuntimeError("Migration 078 downgrade refuses post-migration drift")

        values: dict[str, Any] = {}
        old_pointer = state.get("old_published_version_id")
        if state.get("graph_changed") is True:
            old_version = _owned_version(bind, versions, str(system_row["id"]), old_pointer)
            if (
                old_version is None
                or _contract_sha256(old_version["flow_definition"])
                != OLD_CONTRACT_SHA256
            ):
                raise RuntimeError("Migration 078 downgrade lost its old immutable Flow")
            old_flow = _as_dict(old_version["flow_definition"])
            values.update(
                flow_definition=old_flow,
                published_flow_version_id=old_pointer,
            )
            if state.get("draft_upgraded") is True:
                draft = bind.execute(
                    sa.select(drafts).where(drafts.c.system_id == system_row["id"])
                ).mappings().one_or_none()
                if (
                    draft is None
                    or _contract_sha256(draft["flow_definition"])
                    != NEW_CONTRACT_SHA256
                    or draft["base_published_version_id"]
                    != state.get("new_published_version_id")
                ):
                    raise RuntimeError("Migration 078 downgrade refuses draft drift")
                bind.execute(
                    drafts.update()
                    .where(drafts.c.system_id == system_row["id"])
                    .values(
                        flow_definition=old_flow,
                        revision=int(draft["revision"]) + 1,
                        flow_sha256=_flow_sha256(old_flow),
                        base_published_version_id=old_pointer,
                        updated_by="migration-078-downgrade",
                        updated_at=now,
                    )
                )

        system_settings["flow_revision"] = state.get(
            "old_flow_revision", OLD_FLOW_REVISION
        )
        system_settings.pop(STATE_KEY, None)
        values.update(
            settings=system_settings,
            published_by="migration-078-downgrade",
            published_at=now,
            updated_at=now,
        )
        bind.execute(
            systems.update().where(systems.c.id == system_row["id"]).values(**values)
        )

        workspace_row = bind.execute(
            sa.select(workspaces).where(
                workspaces.c.id == system_row["workspace_id"]
            )
        ).mappings().one()
        workspace_settings = _update_rollout_marker(
            _as_dict(workspace_row["settings"]),
            expected_system_id=str(system_row["id"]),
            flow_revision=OLD_FLOW_REVISION,
        )
        bind.execute(
            workspaces.update()
            .where(workspaces.c.id == workspace_row["id"])
            .values(settings=workspace_settings)
        )


def upgrade() -> None:
    _upgrade(op.get_bind())


def downgrade() -> None:
    _downgrade(op.get_bind())
