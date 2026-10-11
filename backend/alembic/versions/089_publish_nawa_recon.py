"""Publish NAWA Password Reset, seed PO↔Invoice, certified nawa-reset.

Revision ID: 089_publish_nawa_recon
Revises: 088_xp_nawa_recon

Data only. Idempotent.

065 writes Password Reset with a flow_definition and never publishes.
086/088 therefore skip ``nawa.password_reset``. This revision publishes that
System the same way 077/081 append a SystemVersion and set the pointer, then
retries the binding.

It also seeds a minimal published ``PO vs Invoice Reconciliation`` System
(manual ingress + catalog extract/reconcile skills) when none exists, then
attaches ``rapprochement.po.factures`` and Experience ``rapprochement-po-factures``
if 088 did not. Experience ``nawa-reset`` is the certified password-reset form;
``nawa`` stays the inventory pointer to ``/nawa``.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "089_publish_nawa_recon"
down_revision = "088_xp_nawa_recon"
branch_labels = None
depends_on = None

NAWA_SLUG = "nawa"
PASSWORD_RESET_NAME = "Password Reset"
SEED_ORIGIN_065 = "065_nawa_itsd"
SEED_ORIGIN = "089_publish_nawa_recon"
NAWA_BINDING_KEY = "nawa.password_reset"
NAWA_RESET_SLUG = "nawa-reset"
NAWA_RESET_NAME = "NAWA — Password reset"
RECON_BINDING_KEY = "rapprochement.po.factures"
RECON_EXPERIENCE_SLUG = "rapprochement-po-factures"
RECON_EXACT_NAME = "po vs invoice reconciliation"
RECON_SYSTEM_NAME = "PO vs Invoice Reconciliation"
RENDERER_VERSION = "certified-components-0.1.0"
CAPABILITY_SLUG = "document_reconciliation"

ARTIFACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "resources"
    / "flows"
    / "po_invoice_reconciliation_v1.json"
)

REQUIRED_SKILLS = (
    {
        "slug": "spreadsheet_table_extract_v1",
        "name": "Spreadsheet Table Extract",
        "description": "Reads an .xlsx from the Secure Deposit and returns typed rows.",
        "type": "analysis",
        "provider": "internal",
        "certification_level": "production",
    },
    {
        "slug": "invoice_document_extract_v1",
        "name": "Invoice Document Extract",
        "description": "Extracts header fields and line items from a text PDF invoice.",
        "type": "analysis",
        "provider": "internal",
        "certification_level": "production",
    },
    {
        "slug": "line_items_reconcile_v1",
        "name": "Line Items Reconcile",
        "description": "Deterministic reconciliation of two line-item sets.",
        "type": "analysis",
        "provider": "internal",
        "certification_level": "production",
    },
)

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


def _encoded(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_encoded(value).encode("utf-8")).hexdigest()


def _content_sha256(pages: dict[str, Any], binding_keys: list[str]) -> str:
    return _sha256({"binding_keys": binding_keys, "pages": pages})


def _load_recon_artifact() -> dict[str, Any] | None:
    try:
        with ARTIFACT_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _tables():
    workspaces = sa.table(
        "workspaces",
        sa.column("id"),
        sa.column("slug"),
        sa.column("settings", sa.JSON()),
    )
    systems = sa.table(
        "systems",
        sa.column("id"),
        sa.column("workspace_id"),
        sa.column("name"),
        sa.column("objective"),
        sa.column("capability_id"),
        sa.column("skill_ids", sa.JSON()),
        sa.column("flow_definition", sa.JSON()),
        sa.column("settings", sa.JSON()),
        sa.column("execution_mode"),
        sa.column("execution_profile", sa.JSON()),
        sa.column("coordination_pattern"),
        sa.column("status"),
        sa.column("created_by"),
        sa.column("default_model"),
        sa.column("retrieval_mode_default"),
        sa.column("blueprint_key"),
        sa.column("published_flow_version_id"),
        sa.column("published_by"),
        sa.column("published_at"),
        sa.column("created_at"),
        sa.column("updated_at"),
    )
    versions = sa.table(
        "system_versions",
        sa.column("id"),
        sa.column("system_id"),
        sa.column("workspace_id"),
        sa.column("version_number"),
        sa.column("flow_definition", sa.JSON()),
        sa.column("configuration_snapshot", sa.JSON()),
        sa.column("message"),
        sa.column("rolled_back_from_id"),
        sa.column("created_at"),
        sa.column("created_by"),
        sa.column("flow_sha256"),
        sa.column("release_kind"),
        sa.column("draft_revision"),
        sa.column("execution_contract", sa.JSON()),
    )
    drafts = sa.table(
        "system_flow_drafts",
        sa.column("system_id"),
        sa.column("workspace_id"),
        sa.column("flow_definition", sa.JSON()),
        sa.column("revision"),
        sa.column("flow_sha256"),
        sa.column("base_published_version_id"),
        sa.column("updated_by"),
        sa.column("created_at"),
        sa.column("updated_at"),
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
    exp_drafts = sa.table(
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
    skills = sa.table(
        "skills",
        sa.column("id"),
        sa.column("slug"),
        sa.column("version"),
        sa.column("name"),
        sa.column("description"),
        sa.column("type"),
        sa.column("certification_level"),
        sa.column("is_seeded"),
        sa.column("provider"),
        sa.column("created_at"),
        sa.column("updated_at"),
    )
    capabilities = sa.table("capabilities", sa.column("id"), sa.column("slug"))
    return (
        workspaces,
        systems,
        versions,
        drafts,
        bindings,
        experiences,
        exp_drafts,
        releases,
        deployments,
        skills,
        capabilities,
    )


def _ports_schema(raw_ports: Any) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for raw in _as_list(raw_ports):
        if not isinstance(raw, dict):
            continue
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            continue
        primitive = raw.get("schema")
        schema = (
            {"type": primitive}
            if primitive in {"string", "number", "integer", "boolean", "object", "array"}
            else {}
        )
        properties[name] = schema
        if raw.get("required") is True:
            required.append(name)
    result: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        result["required"] = sorted(required)
    return result


def _is_source(node: dict[str, Any]) -> bool:
    kind = str(node.get("kind") or "")
    ntype = str(node.get("type") or "")
    return kind == "source" or ntype == "source" or ntype.startswith("source.")


def _ingress_kind(node: dict[str, Any]) -> str | None:
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    explicit = config.get("ingress_kind")
    if isinstance(explicit, str) and explicit:
        return explicit
    if not _is_source(node):
        return None
    ntype = str(node.get("type") or "")
    if ntype == "input":
        return "chat"
    if ntype.startswith("source."):
        return "event"
    return "manual"


def compile_seed_contract(flow: dict[str, Any]) -> dict[str, Any]:
    """Ingress/output contract from the graph. Skills stay on catalog rows."""
    ingresses: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    inbound = {
        str(edge.get("to") or edge.get("target") or "").strip()
        for edge in _as_list(flow.get("edges"))
        if isinstance(edge, dict)
    }
    for node in _as_list(flow.get("nodes")):
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            continue
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        kind = _ingress_kind(node)
        if kind and node_id not in inbound:
            raw_schema = config.get("input_schema")
            schema = (
                deepcopy(raw_schema)
                if isinstance(raw_schema, dict)
                else _ports_schema(node.get("outputs"))
            )
            ingresses.append(
                {
                    "ingress_id": node_id,
                    "source_node_id": node_id,
                    "kind": kind,
                    "input_schema": schema,
                    "input_schema_sha256": _sha256(schema),
                }
            )
        if str(node.get("kind") or "") == "sink":
            raw_schema = config.get("output_schema")
            schema = (
                deepcopy(raw_schema)
                if isinstance(raw_schema, dict)
                else _ports_schema(node.get("inputs"))
            )
            outputs.append(
                {
                    "node_id": node_id,
                    "schema": schema,
                    "schema_sha256": _sha256(schema),
                }
            )
    ingresses.sort(key=lambda item: item["ingress_id"])
    outputs.sort(key=lambda item: item["node_id"])
    return {"ingresses": ingresses, "outputs": outputs}


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
        (item for item in ingresses if item.get("ingress_id") == "source.request"),
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
        sa.select(
            bindings.c.id,
            bindings.c.system_id,
            bindings.c.published_flow_version_id,
            bindings.c.flow_sha256,
            bindings.c.ingress_id,
            bindings.c.input_schema_sha256,
            bindings.c.output_schema_sha256,
            bindings.c.confirmation_policy,
            bindings.c.on_unavailable,
            bindings.c.binding_key,
        ).where(
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
    contract = _as_dict(version._mapping["execution_contract"])
    if not contract.get("ingresses"):
        return None
    ingress = _pick_ingress(contract, prefer_manual=prefer_manual)
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
    exp_drafts,
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
        sa.insert(exp_drafts).values(
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


def _compile_system_home(
    *,
    system_name: str,
    binding_key: str,
    ingress: dict[str, Any] | None,
    has_hitl: bool,
) -> dict[str, Any]:
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


def publish_unpublished_system(
    bind,
    systems,
    versions,
    drafts,
    *,
    system_id: str,
    workspace_id: str,
    flow: dict[str, Any],
    now: datetime,
    tables_present: set[str],
) -> str | None:
    """Append a SystemVersion and point published_flow_version_id at it.

    Skips when the System already has a published pointer. Reuses an exact
    historical snapshot when one exists (077/081).
    """
    current = bind.execute(
        sa.select(systems.c.published_flow_version_id).where(systems.c.id == system_id)
    ).first()
    if current is None:
        return None
    pointer = current._mapping["published_flow_version_id"]
    if pointer:
        return str(pointer)
    if not flow:
        return None
    digest = _sha256(flow)
    contract = compile_seed_contract(flow)
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
        version_id = str(exact["id"])
        updates: dict[str, Any] = {}
        if not exact["flow_sha256"]:
            updates["flow_sha256"] = digest
        if exact["execution_contract"] is None:
            updates["execution_contract"] = contract
        if updates:
            bind.execute(versions.update().where(versions.c.id == version_id).values(**updates))
    else:
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
                message="Migration 089 published Flow",
                rolled_back_from_id=None,
                created_at=now,
                created_by=f"system:{SEED_ORIGIN}",
                flow_sha256=digest,
                release_kind="migration",
                draft_revision=1,
                execution_contract=contract,
            )
        )
    bind.execute(
        systems.update()
        .where(systems.c.id == system_id)
        .values(
            published_flow_version_id=version_id,
            published_by=f"system:{SEED_ORIGIN}",
            published_at=now,
        )
    )
    if "system_flow_drafts" in tables_present:
        has_draft = bind.execute(
            sa.select(drafts.c.system_id).where(drafts.c.system_id == system_id)
        ).first()
        if has_draft is None:
            bind.execute(
                drafts.insert().values(
                    system_id=system_id,
                    workspace_id=workspace_id,
                    flow_definition=flow,
                    revision=1,
                    flow_sha256=digest,
                    base_published_version_id=version_id,
                    updated_by=f"system:{SEED_ORIGIN}",
                    created_at=now,
                    updated_at=now,
                )
            )
    return version_id


def _find_password_reset(bind, systems, workspace_id: str):
    rows = bind.execute(
        sa.select(
            systems.c.id,
            systems.c.settings,
            systems.c.flow_definition,
            systems.c.published_flow_version_id,
        ).where(
            systems.c.workspace_id == workspace_id,
            systems.c.name == PASSWORD_RESET_NAME,
        )
    ).all()
    marked = [
        row
        for row in rows
        if _as_dict(row._mapping["settings"]).get("seed_origin") == SEED_ORIGIN_065
    ]
    chosen = marked or list(rows)
    return chosen[0]._mapping if chosen else None


def _publish_and_bind_nawa(bind, tables, now: datetime, tables_present: set[str]) -> None:
    workspaces, systems, versions, drafts, bindings, *_rest = tables
    for ws in bind.execute(sa.select(workspaces.c.id).where(workspaces.c.slug == NAWA_SLUG)).all():
        workspace_id = ws._mapping["id"]
        system = _find_password_reset(bind, systems, workspace_id)
        if system is None:
            continue
        version_id = system["published_flow_version_id"]
        if not version_id:
            version_id = publish_unpublished_system(
                bind,
                systems,
                versions,
                drafts,
                system_id=system["id"],
                workspace_id=workspace_id,
                flow=_as_dict(system["flow_definition"]),
                now=now,
                tables_present=tables_present,
            )
        if not version_id:
            continue
        _insert_binding_if_missing(
            bind,
            bindings,
            versions,
            workspace_id=workspace_id,
            binding_key=NAWA_BINDING_KEY,
            system_id=system["id"],
            published_flow_version_id=str(version_id),
            prefer_manual=False,
            confirmation_policy="hitl",
            now=now,
        )


def _seed_nawa_reset(bind, tables, now: datetime) -> None:
    workspaces, _systems, versions, _drafts, bindings, experiences, exp_drafts, releases, deployments, *_rest = tables
    for ws in bind.execute(sa.select(workspaces.c.id).where(workspaces.c.slug == NAWA_SLUG)).all():
        workspace_id = ws._mapping["id"]
        row = _existing_binding(
            bind, bindings, workspace_id=workspace_id, binding_key=NAWA_BINDING_KEY
        )
        if row is None:
            continue
        version = _load_published_version(
            bind,
            versions,
            workspace_id=workspace_id,
            system_id=row._mapping["system_id"],
            version_id=row._mapping["published_flow_version_id"],
        )
        contract = _as_dict(version._mapping["execution_contract"]) if version is not None else {}
        ingress = _pick_ingress(contract, prefer_manual=False)
        pages = _compile_system_home(
            system_name=NAWA_RESET_NAME,
            binding_key=NAWA_BINDING_KEY,
            ingress=ingress,
            has_hitl=True,
        )
        _insert_experience(
            bind,
            experiences,
            exp_drafts,
            releases,
            deployments,
            workspace_id=workspace_id,
            name=NAWA_RESET_NAME,
            slug=NAWA_RESET_SLUG,
            pattern="form_result",
            languages=["en"],
            theme={},
            pages=pages,
            binding_keys=[NAWA_BINDING_KEY],
            bindings_snapshot=[_snapshot_from_row(row)],
            channel="live",
            notes="Lot leftover: certified password-reset form on /work/nawa-reset.",
            now=now,
        )


def _ensure_required_skills(bind, skills, now: datetime) -> None:
    for meta in REQUIRED_SKILLS:
        exists = bind.execute(
            sa.select(skills.c.id).where(skills.c.slug == meta["slug"])
        ).first()
        if exists:
            continue
        bind.execute(
            sa.insert(skills).values(
                id=str(uuid4()),
                slug=meta["slug"],
                version="1",
                name=meta["name"],
                description=meta["description"],
                type=meta["type"],
                certification_level=meta["certification_level"],
                is_seeded="Y",
                provider=meta["provider"],
                created_at=now,
                updated_at=now,
            )
        )


def _resolve_flow_skill_ids(bind, skills, flow: dict[str, Any]) -> list[str]:
    slugs = {
        (node.get("config") or {}).get("skill_slug")
        for node in flow.get("nodes") or []
        if isinstance(node, dict) and (node.get("config") or {}).get("skill_slug")
    }
    id_by_slug: dict[str, str] = {}
    if slugs:
        rows = bind.execute(
            sa.select(skills.c.id, skills.c.slug).where(skills.c.slug.in_(list(slugs)))
        ).all()
        id_by_slug = {r._mapping["slug"]: r._mapping["id"] for r in rows}
    ordered: list[str] = []
    for node in flow.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        config = node.get("config")
        if not isinstance(config, dict) or not config.get("skill_slug"):
            continue
        skill_id = id_by_slug.get(config["skill_slug"])
        config["skill_id"] = skill_id
        if skill_id and skill_id not in ordered:
            ordered.append(skill_id)
    return ordered


def _merge_catalog_override(settings: dict[str, Any]) -> None:
    catalog = settings.get("catalog")
    catalog = dict(catalog) if isinstance(catalog, dict) else {}
    enabled = [s for s in catalog.get("enabled_skills") or [] if isinstance(s, str)]
    present = {s.strip().lower() for s in enabled}
    for slug in (item["slug"] for item in REQUIRED_SKILLS):
        if slug.lower() not in present:
            enabled.append(slug)
            present.add(slug.lower())
    catalog["enabled_skills"] = enabled
    settings["catalog"] = catalog


def _find_recon_system(bind, systems, workspace_id: str):
    rows = bind.execute(
        sa.select(
            systems.c.id,
            systems.c.name,
            systems.c.settings,
            systems.c.flow_definition,
            systems.c.published_flow_version_id,
        ).where(systems.c.workspace_id == workspace_id)
    ).all()
    matches = [row._mapping for row in rows if _is_recon_name(row._mapping["name"])]
    published = [row for row in matches if row["published_flow_version_id"]]
    return (published or matches)[0] if (published or matches) else None


def _seed_po_invoice_system(bind, tables, now: datetime, tables_present: set[str]) -> None:
    workspaces, systems, versions, drafts, _bindings, *_rest = tables
    skills = tables[9]
    capabilities = tables[10]
    artifact = _load_recon_artifact()
    if not artifact:
        return
    flow = _as_dict(artifact.get("flow_definition"))
    if not flow:
        return
    skill_ids: list[str] = []
    if "skills" in tables_present:
        _ensure_required_skills(bind, skills, now)
        skill_ids = _resolve_flow_skill_ids(bind, skills, flow)
    capability_id = None
    if "capabilities" in tables_present:
        cap = bind.execute(
            sa.select(capabilities.c.id).where(capabilities.c.slug == CAPABILITY_SLUG)
        ).first()
        capability_id = cap._mapping["id"] if cap else None
    artifact_system = artifact.get("system") if isinstance(artifact.get("system"), dict) else {}
    settings_payload = _as_dict(artifact.get("system_settings"))
    settings_payload["seed_origin"] = SEED_ORIGIN
    system_columns = {col["name"] for col in sa.inspect(bind).get_columns("systems")}
    for ws in bind.execute(
        sa.select(workspaces.c.id, workspaces.c.settings).where(workspaces.c.slug == NAWA_SLUG)
    ).all():
        workspace_id = ws._mapping["id"]
        existing = _find_recon_system(bind, systems, workspace_id)
        if existing is None:
            system_id = str(uuid4())
            settings = _as_dict(ws._mapping["settings"])
            _merge_catalog_override(settings)
            bind.execute(
                workspaces.update()
                .where(workspaces.c.id == workspace_id)
                .values(settings=settings)
            )
            values = dict(
                id=system_id,
                workspace_id=workspace_id,
                name=RECON_SYSTEM_NAME,
                objective=artifact_system.get("objective") or RECON_SYSTEM_NAME,
                capability_id=capability_id,
                skill_ids=skill_ids,
                flow_definition=deepcopy(flow),
                settings=deepcopy(settings_payload),
                execution_mode=artifact_system.get("execution_mode") or "human_augmented",
                execution_profile={"surface": "experience", "durability": "audit_events"},
                coordination_pattern=artifact_system.get("coordination_pattern") or "single_agent",
                status="active",
                created_by=f"system:{SEED_ORIGIN}",
                default_model=artifact_system.get("default_model") or "gpt-4o-mini",
                retrieval_mode_default="auto",
                created_at=now,
                updated_at=now,
            )
            if "blueprint_key" in system_columns:
                values["blueprint_key"] = system_id
            bind.execute(sa.insert(systems).values(**values))
            existing = {
                "id": system_id,
                "name": RECON_SYSTEM_NAME,
                "settings": settings_payload,
                "flow_definition": flow,
                "published_flow_version_id": None,
            }
        version_id = existing["published_flow_version_id"]
        if not version_id:
            version_id = publish_unpublished_system(
                bind,
                systems,
                versions,
                drafts,
                system_id=existing["id"],
                workspace_id=workspace_id,
                flow=_as_dict(existing["flow_definition"]) or flow,
                now=now,
                tables_present=tables_present,
            )
        if not version_id:
            continue


def _seed_reconciliation_experience(bind, tables, now: datetime) -> None:
    workspaces, systems, versions, _drafts, bindings, experiences, exp_drafts, releases, deployments, *_rest = tables
    for ws in bind.execute(sa.select(workspaces.c.id).where(workspaces.c.slug == NAWA_SLUG)).all():
        workspace_id = ws._mapping["id"]
        system = _find_recon_system(bind, systems, workspace_id)
        if system is None or not system["published_flow_version_id"]:
            continue
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
            exp_drafts,
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
            notes="Lot leftover: System Home from published PO↔Invoice Flow.",
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
    _publish_and_bind_nawa(bind, tables, now, tables_present)
    _seed_nawa_reset(bind, tables, now)
    _seed_po_invoice_system(bind, tables, now, tables_present)
    _seed_reconciliation_experience(bind, tables, now)


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
    if "system_flow_drafts" in tables:
        flow_drafts = sa.table("system_flow_drafts", sa.column("updated_by"), sa.column("revision"))
        bind.execute(
            sa.delete(flow_drafts).where(
                sa.and_(flow_drafts.c.updated_by == actor, flow_drafts.c.revision == 1)
            )
        )
    if "systems" in tables:
        systems = sa.table(
            "systems",
            sa.column("id"),
            sa.column("settings", sa.JSON()),
            sa.column("published_by"),
            sa.column("published_flow_version_id"),
            sa.column("published_at"),
            sa.column("status"),
        )
        bind.execute(
            systems.update()
            .where(systems.c.published_by == actor)
            .values(published_flow_version_id=None, published_by=None, published_at=None)
        )
        for row in bind.execute(sa.select(systems.c.id, systems.c.settings)).all():
            if _as_dict(row._mapping["settings"]).get("seed_origin") != SEED_ORIGIN:
                continue
            bind.execute(
                systems.update()
                .where(systems.c.id == row._mapping["id"])
                .values(status="retired")
            )
