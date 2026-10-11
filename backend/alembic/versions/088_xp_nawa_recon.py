"""Lot 7: retry NAWA binding, inventory Experience, optional PO↔Invoice seed.

Revision ID: 088_xp_nawa_recon
Revises: 087_experiences

Data only. Idempotent.

086 skipped ``nawa.password_reset`` when Password Reset had no published
Flow yet (065 never publishes). This retry binds a published System of
that name in the ``nawa`` workspace even if the 065 marker is gone.

The NAWA Experience is an inventory pointer to ``/nawa`` — not a clone of
the custom ITSD UI. The PO↔Invoice Experience is seeded only when a
published reconciliation System already exists; this revision never
invents one.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "088_xp_nawa_recon"
down_revision = "087_experiences"
branch_labels = None
depends_on = None

NAWA_SLUG = "nawa"
PASSWORD_RESET_NAME = "Password Reset"
SEED_ORIGIN_065 = "065_nawa_itsd"
SEED_ORIGIN = "088_xp_nawa_recon"
NAWA_BINDING_KEY = "nawa.password_reset"
NAWA_EXPERIENCE_SLUG = "nawa"
NAWA_EXPERIENCE_NAME = "NAWA — IT Help Desk"
RECON_BINDING_KEY = "rapprochement.po.factures"
RECON_EXPERIENCE_SLUG = "rapprochement-po-factures"
RECON_EXACT_NAME = "po vs invoice reconciliation"
RENDERER_VERSION = "certified-components-0.1.0"

HOME_LABELS = {
    "subtitle": "Fill in the details, then send.",
    "submit": "Submit",
    "missing_entry": "No manual entry is offered right now.",
    "approval_title": "Approval",
    "approval_body": "A person must approve before this continues.",
}


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return deepcopy(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _content_sha256(pages: dict[str, Any], binding_keys: list[str]) -> str:
    canonical = json.dumps(
        {"binding_keys": binding_keys, "pages": pages},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _tables():
    workspaces = sa.table("workspaces", sa.column("id"), sa.column("slug"))
    systems = sa.table(
        "systems",
        sa.column("id"),
        sa.column("workspace_id"),
        sa.column("name"),
        sa.column("settings", sa.JSON()),
        sa.column("published_flow_version_id"),
    )
    versions = sa.table(
        "system_versions",
        sa.column("id"),
        sa.column("system_id"),
        sa.column("workspace_id"),
        sa.column("flow_sha256"),
        sa.column("execution_contract", sa.JSON()),
    )
    bindings = sa.table(
        "system_bindings",
        sa.column("id"),
        sa.column("workspace_id"),
        sa.column("binding_key"),
        sa.column("system_id"),
        sa.column("published_flow_version_id"),
        sa.column("flow_sha256"),
        sa.column("ingress_id"),
        sa.column("input_schema_sha256"),
        sa.column("output_schema_sha256"),
        sa.column("confirmation_policy"),
        sa.column("on_unavailable"),
        sa.column("created_by"),
        sa.column("created_at"),
        sa.column("updated_at"),
    )
    experiences = sa.table(
        "experiences",
        sa.column("id"),
        sa.column("workspace_id"),
        sa.column("name"),
        sa.column("slug"),
        sa.column("pattern"),
        sa.column("languages", sa.JSON()),
        sa.column("theme", sa.JSON()),
        sa.column("created_by"),
        sa.column("created_at"),
        sa.column("updated_at"),
    )
    drafts = sa.table(
        "experience_draft_revisions",
        sa.column("experience_id"),
        sa.column("workspace_id"),
        sa.column("revision"),
        sa.column("pages", sa.JSON()),
        sa.column("binding_keys", sa.JSON()),
        sa.column("content_sha256"),
        sa.column("updated_by"),
        sa.column("created_at"),
        sa.column("updated_at"),
    )
    releases = sa.table(
        "experience_releases",
        sa.column("id"),
        sa.column("experience_id"),
        sa.column("workspace_id"),
        sa.column("release_number"),
        sa.column("content_sha256"),
        sa.column("pages", sa.JSON()),
        sa.column("bindings_snapshot", sa.JSON()),
        sa.column("access_snapshot", sa.JSON()),
        sa.column("languages", sa.JSON()),
        sa.column("theme", sa.JSON()),
        sa.column("renderer_version"),
        sa.column("notes"),
        sa.column("created_by"),
        sa.column("created_at"),
    )
    deployments = sa.table(
        "experience_deployments",
        sa.column("id"),
        sa.column("experience_id"),
        sa.column("workspace_id"),
        sa.column("channel"),
        sa.column("release_id"),
        sa.column("previous_release_id"),
        sa.column("audience", sa.JSON()),
        sa.column("updated_by"),
        sa.column("created_at"),
        sa.column("updated_at"),
    )
    return workspaces, systems, versions, bindings, experiences, drafts, releases, deployments


def _pick_ingress(contract: dict[str, Any], *, prefer_manual: bool) -> dict[str, Any] | None:
    ingresses = [item for item in _as_list(contract.get("ingresses")) if isinstance(item, dict)]
    if prefer_manual:
        manual = next(
            (
                item
                for item in ingresses
                if item.get("kind") == "manual" and item.get("ingress_id")
            ),
            None,
        )
        if manual is not None:
            return manual
    named = next(
        (
            item
            for item in ingresses
            if item.get("ingress_id") == "source.request"
        ),
        None,
    )
    if named is not None:
        return named
    return next((item for item in ingresses if item.get("ingress_id")), None)


def _has_hitl(contract: dict[str, Any]) -> bool:
    for item in _as_list(contract.get("ingresses")):
        if not isinstance(item, dict):
            continue
        blob = f"{item.get('ingress_id') or ''} {item.get('source_node_id') or ''}"
        if "hitl" in blob.lower():
            return True
    return False


def _binding_values(
    *,
    workspace_id: str,
    binding_key: str,
    system_id: str,
    version: Any,
    ingress: dict[str, Any],
    confirmation_policy: str,
    now: datetime,
) -> dict[str, Any] | None:
    mapping = version._mapping
    flow_sha256 = mapping["flow_sha256"]
    ingress_id = ingress.get("ingress_id")
    input_sha = ingress.get("input_schema_sha256")
    if not isinstance(flow_sha256, str) or len(flow_sha256) != 64:
        return None
    if not isinstance(ingress_id, str) or not ingress_id:
        return None
    if not isinstance(input_sha, str) or len(input_sha) != 64:
        return None
    outputs = _as_list(_as_dict(mapping["execution_contract"]).get("outputs"))
    output_sha = None
    if len(outputs) == 1 and isinstance(outputs[0], dict):
        digest = outputs[0].get("schema_sha256")
        if isinstance(digest, str) and len(digest) == 64:
            output_sha = digest
    return {
        "id": str(uuid4()),
        "workspace_id": workspace_id,
        "binding_key": binding_key,
        "system_id": system_id,
        "published_flow_version_id": mapping["id"],
        "flow_sha256": flow_sha256,
        "ingress_id": ingress_id,
        "input_schema_sha256": input_sha,
        "output_schema_sha256": output_sha,
        "confirmation_policy": confirmation_policy,
        "on_unavailable": "unavailable",
        "created_by": f"system:{SEED_ORIGIN}",
        "created_at": now,
        "updated_at": now,
    }


def _load_published_version(bind, versions, *, workspace_id: str, system_id: str, version_id: str):
    return bind.execute(
        sa.select(
            versions.c.id,
            versions.c.flow_sha256,
            versions.c.execution_contract,
        ).where(
            versions.c.id == version_id,
            versions.c.system_id == system_id,
            versions.c.workspace_id == workspace_id,
        )
    ).first()


def _existing_binding(bind, bindings, *, workspace_id: str, binding_key: str):
    return bind.execute(
        sa.select(bindings.c.id, bindings.c.system_id, bindings.c.published_flow_version_id,
                  bindings.c.flow_sha256, bindings.c.ingress_id, bindings.c.input_schema_sha256,
                  bindings.c.output_schema_sha256, bindings.c.confirmation_policy,
                  bindings.c.on_unavailable, bindings.c.binding_key).where(
            bindings.c.workspace_id == workspace_id,
            bindings.c.binding_key == binding_key,
        )
    ).first()


def _snapshot_from_row(row: Any) -> dict[str, Any]:
    mapping = row._mapping
    return {
        "binding_key": mapping["binding_key"],
        "system_id": mapping["system_id"],
        "published_flow_version_id": mapping["published_flow_version_id"],
        "flow_sha256": mapping["flow_sha256"],
        "ingress_id": mapping["ingress_id"],
        "input_schema_sha256": mapping["input_schema_sha256"],
        "output_schema_sha256": mapping["output_schema_sha256"],
        "confirmation_policy": mapping["confirmation_policy"],
        "on_unavailable": mapping["on_unavailable"],
    }


def _insert_binding_if_missing(
    bind,
    bindings,
    versions,
    *,
    workspace_id: str,
    binding_key: str,
    system_id: str,
    published_flow_version_id: str,
    prefer_manual: bool,
    confirmation_policy: str,
    now: datetime,
) -> Any:
    already = _existing_binding(bind, bindings, workspace_id=workspace_id, binding_key=binding_key)
    if already:
        return already
    version = _load_published_version(
        bind,
        versions,
        workspace_id=workspace_id,
        system_id=system_id,
        version_id=published_flow_version_id,
    )
    if version is None:
        return None
    ingress = _pick_ingress(_as_dict(version._mapping["execution_contract"]), prefer_manual=prefer_manual)
    if ingress is None:
        return None
    values = _binding_values(
        workspace_id=workspace_id,
        binding_key=binding_key,
        system_id=system_id,
        version=version,
        ingress=ingress,
        confirmation_policy=confirmation_policy,
        now=now,
    )
    if values is None:
        return None
    bind.execute(sa.insert(bindings).values(**values))
    return _existing_binding(bind, bindings, workspace_id=workspace_id, binding_key=binding_key)


def _slug_exists(bind, experiences, *, workspace_id: str, slug: str) -> bool:
    return (
        bind.execute(
            sa.select(experiences.c.id).where(
                experiences.c.workspace_id == workspace_id,
                experiences.c.slug == slug,
            )
        ).first()
        is not None
    )


def _insert_experience(
    bind,
    experiences,
    drafts,
    releases,
    deployments,
    *,
    workspace_id: str,
    name: str,
    slug: str,
    pattern: str,
    languages: list[str],
    theme: dict[str, Any],
    pages: dict[str, Any],
    binding_keys: list[str],
    bindings_snapshot: list[dict[str, Any]],
    channel: str,
    notes: str,
    now: datetime,
) -> None:
    if _slug_exists(bind, experiences, workspace_id=workspace_id, slug=slug):
        return
    experience_id = str(uuid4())
    release_id = str(uuid4())
    digest = _content_sha256(pages, binding_keys)
    actor = f"system:{SEED_ORIGIN}"
    bind.execute(
        sa.insert(experiences).values(
            id=experience_id,
            workspace_id=workspace_id,
            name=name,
            slug=slug,
            pattern=pattern,
            languages=languages,
            theme=theme,
            created_by=actor,
            created_at=now,
            updated_at=now,
        )
    )
    bind.execute(
        sa.insert(drafts).values(
            experience_id=experience_id,
            workspace_id=workspace_id,
            revision=1,
            pages=pages,
            binding_keys=binding_keys,
            content_sha256=digest,
            updated_by=actor,
            created_at=now,
            updated_at=now,
        )
    )
    bind.execute(
        sa.insert(releases).values(
            id=release_id,
            experience_id=experience_id,
            workspace_id=workspace_id,
            release_number=1,
            content_sha256=digest,
            pages=pages,
            bindings_snapshot=bindings_snapshot,
            access_snapshot={},
            languages=languages,
            theme=theme,
            renderer_version=RENDERER_VERSION,
            notes=notes,
            created_by=actor,
            created_at=now,
        )
    )
    bind.execute(
        sa.insert(deployments).values(
            id=str(uuid4()),
            experience_id=experience_id,
            workspace_id=workspace_id,
            channel=channel,
            release_id=release_id,
            previous_release_id=None,
            audience={},
            updated_by=actor,
            created_at=now,
            updated_at=now,
        )
    )


def _compile_system_home(*, system_name: str, binding_key: str, ingress: dict[str, Any] | None, has_hitl: bool) -> dict[str, Any]:
    components: list[dict[str, Any]] = [
        {
            "type": "header",
            "id": "home-head",
            "props": {"title": system_name, "subtitle": HOME_LABELS["subtitle"]},
        }
    ]
    if ingress is not None:
        components.extend(
            [
                {
                    "type": "form",
                    "id": "home-form",
                    "props": {
                        "bindingKey": binding_key,
                        "schema": ingress.get("input_schema") or {"type": "object", "properties": {}},
                    },
                },
                {
                    "type": "action_button",
                    "id": "home-action",
                    "props": {"bindingKey": binding_key, "label": HOME_LABELS["submit"]},
                },
            ]
        )
    else:
        components.append(
            {
                "type": "callout",
                "id": "home-missing",
                "props": {"body": HOME_LABELS["missing_entry"]},
            }
        )
    if has_hitl:
        components.append(
            {
                "type": "approval_card",
                "id": "home-approval",
                "props": {
                    "title": HOME_LABELS["approval_title"],
                    "body": HOME_LABELS["approval_body"],
                },
            }
        )
    components.extend(
        [
            {"type": "runtime_status", "id": "home-status"},
            {"type": "result", "id": "home-result"},
            {"type": "evidence", "id": "home-evidence"},
            {"type": "history", "id": "home-history"},
        ]
    )
    return {"pages": [{"id": "form_result", "title": system_name, "components": components}]}


def _is_recon_name(name: str) -> bool:
    lowered = (name or "").casefold()
    if lowered == RECON_EXACT_NAME:
        return True
    return "invoice" in lowered and ("reconcil" in lowered or "rapprochement" in lowered)


def _nawa_pages() -> dict[str, Any]:
    return {
        "pages": [
            {
                "id": "home",
                "title": NAWA_EXPERIENCE_NAME,
                "components": [
                    {
                        "type": "header",
                        "id": "nawa-head",
                        "props": {
                            "title": NAWA_EXPERIENCE_NAME,
                            "subtitle": "IT service desk. The live surface stays /nawa.",
                        },
                    },
                    {
                        "type": "callout",
                        "id": "nawa-live",
                        "props": {
                            "body": "Open NAWA WE on /nawa — this inventory entry does not replace the custom ITSD UI.",
                            "href": "/nawa",
                        },
                    },
                ],
            }
        ]
    }


def _find_password_reset(bind, systems, workspace_id: str):
    rows = bind.execute(
        sa.select(
            systems.c.id,
            systems.c.settings,
            systems.c.published_flow_version_id,
        ).where(
            systems.c.workspace_id == workspace_id,
            systems.c.name == PASSWORD_RESET_NAME,
        )
    ).all()
    published = [row for row in rows if row._mapping["published_flow_version_id"]]
    marked = [
        row
        for row in published
        if _as_dict(row._mapping["settings"]).get("seed_origin") == SEED_ORIGIN_065
    ]
    chosen = (marked or published)
    return chosen[0]._mapping if chosen else None


def _retry_nawa_password_reset(bind, tables, now: datetime) -> None:
    workspaces, systems, versions, bindings, *_rest = tables
    for ws in bind.execute(sa.select(workspaces.c.id).where(workspaces.c.slug == NAWA_SLUG)).all():
        workspace_id = ws._mapping["id"]
        system = _find_password_reset(bind, systems, workspace_id)
        if system is None:
            continue
        _insert_binding_if_missing(
            bind,
            bindings,
            versions,
            workspace_id=workspace_id,
            binding_key=NAWA_BINDING_KEY,
            system_id=system["id"],
            published_flow_version_id=system["published_flow_version_id"],
            prefer_manual=False,
            confirmation_policy="hitl",
            now=now,
        )


def _seed_nawa_experience(bind, tables, now: datetime) -> None:
    workspaces, _systems, _versions, bindings, experiences, drafts, releases, deployments = tables
    for ws in bind.execute(sa.select(workspaces.c.id).where(workspaces.c.slug == NAWA_SLUG)).all():
        workspace_id = ws._mapping["id"]
        row = _existing_binding(
            bind, bindings, workspace_id=workspace_id, binding_key=NAWA_BINDING_KEY
        )
        keys = [NAWA_BINDING_KEY] if row else []
        snapshot = [_snapshot_from_row(row)] if row else []
        _insert_experience(
            bind,
            experiences,
            drafts,
            releases,
            deployments,
            workspace_id=workspace_id,
            name=NAWA_EXPERIENCE_NAME,
            slug=NAWA_EXPERIENCE_SLUG,
            pattern="assistant",
            languages=["en"],
            theme={"live_href": "/nawa"},
            pages=_nawa_pages(),
            binding_keys=keys,
            bindings_snapshot=snapshot,
            channel="live",
            notes="Lot 7 dual-run: inventory pointer to /nawa.",
            now=now,
        )


def _find_recon_systems(bind, workspaces, systems) -> list[Any]:
    nawa_ids = {
        row._mapping["id"]
        for row in bind.execute(sa.select(workspaces.c.id).where(workspaces.c.slug == NAWA_SLUG)).all()
    }
    found: list[Any] = []
    for row in bind.execute(
        sa.select(
            systems.c.id,
            systems.c.workspace_id,
            systems.c.name,
            systems.c.published_flow_version_id,
        )
    ).all():
        mapping = row._mapping
        if not mapping["published_flow_version_id"]:
            continue
        if not _is_recon_name(mapping["name"]):
            continue
        found.append(mapping)
    found.sort(key=lambda item: (0 if item["workspace_id"] in nawa_ids else 1, item["name"]))
    return found


def _seed_reconciliation(bind, tables, now: datetime) -> None:
    workspaces, systems, versions, bindings, experiences, drafts, releases, deployments = tables
    seen_workspaces: set[str] = set()
    for system in _find_recon_systems(bind, workspaces, systems):
        workspace_id = system["workspace_id"]
        if workspace_id in seen_workspaces:
            continue
        seen_workspaces.add(workspace_id)
        version = _load_published_version(
            bind,
            versions,
            workspace_id=workspace_id,
            system_id=system["id"],
            version_id=system["published_flow_version_id"],
        )
        if version is None:
            continue
        contract = _as_dict(version._mapping["execution_contract"])
        ingress = _pick_ingress(contract, prefer_manual=True)
        has_hitl = _has_hitl(contract)
        confirmation = "hitl" if has_hitl else "confirm"
        binding_row = None
        if ingress is not None:
            binding_row = _insert_binding_if_missing(
                bind,
                bindings,
                versions,
                workspace_id=workspace_id,
                binding_key=RECON_BINDING_KEY,
                system_id=system["id"],
                published_flow_version_id=system["published_flow_version_id"],
                prefer_manual=True,
                confirmation_policy=confirmation,
                now=now,
            )
        keys = [RECON_BINDING_KEY] if binding_row else []
        snapshot = [_snapshot_from_row(binding_row)] if binding_row else []
        pages = _compile_system_home(
            system_name=system["name"],
            binding_key=RECON_BINDING_KEY,
            ingress=ingress if binding_row else None,
            has_hitl=has_hitl,
        )
        _insert_experience(
            bind,
            experiences,
            drafts,
            releases,
            deployments,
            workspace_id=workspace_id,
            name=system["name"],
            slug=RECON_EXPERIENCE_SLUG,
            pattern="form_result",
            languages=["fr", "en"],
            theme={},
            pages=pages,
            binding_keys=keys,
            bindings_snapshot=snapshot,
            channel="pilot",
            notes="Lot 7 System Home from published PO↔Invoice Flow.",
            now=now,
        )


def upgrade() -> None:
    bind = op.get_bind()
    tables_present = set(sa.inspect(bind).get_table_names())
    needed = {
        "workspaces",
        "systems",
        "system_versions",
        "system_bindings",
        "experiences",
        "experience_draft_revisions",
        "experience_releases",
        "experience_deployments",
    }
    if not needed.issubset(tables_present):
        return
    now = datetime.utcnow()
    tables = _tables()
    _retry_nawa_password_reset(bind, tables, now)
    _seed_nawa_experience(bind, tables, now)
    _seed_reconciliation(bind, tables, now)


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    actor = f"system:{SEED_ORIGIN}"
    if "experience_deployments" in tables:
        deployments = sa.table("experience_deployments", sa.column("updated_by"))
        bind.execute(sa.delete(deployments).where(deployments.c.updated_by == actor))
    if "experience_releases" in tables:
        releases = sa.table("experience_releases", sa.column("created_by"))
        bind.execute(sa.delete(releases).where(releases.c.created_by == actor))
    if "experience_draft_revisions" in tables:
        drafts = sa.table("experience_draft_revisions", sa.column("updated_by"))
        bind.execute(sa.delete(drafts).where(drafts.c.updated_by == actor))
    if "experiences" in tables:
        experiences = sa.table("experiences", sa.column("created_by"))
        bind.execute(sa.delete(experiences).where(experiences.c.created_by == actor))
    if "system_bindings" in tables:
        bindings = sa.table(
            "system_bindings",
            sa.column("created_by"),
            sa.column("binding_key"),
        )
        bind.execute(
            sa.delete(bindings).where(
                bindings.c.created_by == actor,
                bindings.c.binding_key.in_((NAWA_BINDING_KEY, RECON_BINDING_KEY)),
            )
        )
