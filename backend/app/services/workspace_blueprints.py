"""Workspace Blueprint export/import helpers.

Blueprints sit one level above the existing System export envelope: they
capture the workspace structure and configuration needed to recreate a
reference workspace without leaking members, credentials, raw files or
vector payloads.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.models.capability import Capability
from app.models.context import Context
from app.models.evaluation_preset import EvaluationPreset
from app.models.knowledge_collection import KnowledgeCollection
from app.models.rag_preset import RagPreset
from app.models.skill import Skill
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services import knowledge_collections
from app.services.audit_logger import emit_audit_event
from app.services.chains import dag_validator, export_service, version_service
from app.services.iam.config_service import load_iam_config, patch_iam_config


BLUEPRINT_KIND = "agentium.workspace.blueprint"
SCHEMA_VERSION = 1


class WorkspaceBlueprintError(ValueError):
    """Raised when a workspace blueprint payload is malformed."""


def actor_display_name(user: User | None) -> str:
    if not user:
        return "system"
    return user.email or user.username or user.id or "system"


def export_workspace_blueprint(
    *,
    db: DBSession,
    workspace: Workspace,
    exported_by: User | None,
) -> dict[str, Any]:
    """Build a portable workspace blueprint.

    Data policy is intentionally conservative: the blueprint exports
    structure, model/config choices and collection metadata only. It never
    exports secure-deposit files, passwords, members, raw documents, vectors
    or Keycloak identity data.
    """
    actor = actor_display_name(exported_by)
    systems = (
        db.query(System)
        .filter(System.workspace_id == workspace.id)
        .order_by(System.created_at.asc(), System.name.asc())
        .all()
    )

    capability_ids = {s.capability_id for s in systems if s.capability_id}
    capability_filter = Capability.workspace_id == workspace.id
    if capability_ids:
        capability_filter = or_(capability_filter, Capability.id.in_(capability_ids))
    capabilities = (
        db.query(Capability)
        .filter(capability_filter)
        .order_by(Capability.workspace_id.is_(None), Capability.slug.asc())
        .all()
    )

    contexts = (
        db.query(Context)
        .filter(Context.workspace_id == workspace.id, Context.ephemeral.is_(False))
        .order_by(Context.name.asc(), Context.version.asc())
        .all()
    )
    collections = (
        db.query(KnowledgeCollection)
        .filter(KnowledgeCollection.workspace_id == workspace.id)
        .order_by(KnowledgeCollection.slug.asc())
        .all()
    )
    rag_presets = (
        db.query(RagPreset)
        .filter(RagPreset.workspace_id == workspace.id)
        .order_by(RagPreset.scope.asc(), RagPreset.name.asc())
        .all()
    )
    evaluation_presets = (
        db.query(EvaluationPreset)
        .filter(EvaluationPreset.workspace_id == workspace.id)
        .order_by(EvaluationPreset.scope.asc(), EvaluationPreset.name.asc())
        .all()
    )
    iam_config = load_iam_config(db, workspace.id, create=False)

    systems_by_id = {s.id: s for s in systems}
    capabilities_by_id = {c.id: c for c in capabilities}
    contexts_by_id = {c.id: c for c in contexts}
    capability_skill_ids = {
        skill_id
        for capability in capabilities
        for skill_id in (capability.skill_ids or [])
    }
    skill_slugs_by_id = {
        row.id: row.slug
        for row in db.query(Skill.id, Skill.slug).filter(Skill.id.in_(capability_skill_ids)).all()
    } if capability_skill_ids else {}

    payload = {
        "kind": BLUEPRINT_KIND,
        "schema_version": SCHEMA_VERSION,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "exported_by": actor,
        "source": {
            "workspace_id": workspace.id,
            "workspace_slug": workspace.slug,
            "workspace_name": workspace.name,
        },
        "workspace": {
            "name": workspace.name,
            "slug": workspace.slug,
            "mode": workspace.mode,
            "settings": workspace.settings or {},
        },
        "capabilities": [
            _serialize_capability(c, workspace_id=workspace.id, skill_slugs_by_id=skill_slugs_by_id)
            for c in capabilities
        ],
        "contexts": [
            _serialize_context(c, systems_by_id=systems_by_id) for c in contexts
        ],
        "systems": [
            _serialize_system(
                db=db,
                system=s,
                actor=actor,
                capabilities_by_id=capabilities_by_id,
                contexts_by_id=contexts_by_id,
            )
            for s in systems
        ],
        "knowledge": {
            "collections": [_serialize_collection(c) for c in collections],
            "exports_raw_documents": False,
            "exports_vectors": False,
        },
        "presets": {
            "rag": [
                _serialize_preset(p, systems_by_id=systems_by_id, capabilities_by_id=capabilities_by_id)
                for p in rag_presets
            ],
            "evaluation": [
                _serialize_preset(p, systems_by_id=systems_by_id, capabilities_by_id=capabilities_by_id)
                for p in evaluation_presets
            ],
        },
        "iam": {
            "exports_members": False,
            "role_flags": (iam_config.role_flags or {}) if iam_config else {},
            "capability_overrides": (iam_config.capability_overrides or {}) if iam_config else {},
        },
        "connectors": {
            "secure_deposit": {
                "enabled": True,
                "exports_links": False,
                "exports_passwords": False,
                "exports_files": False,
                "staging_policy": "manual_promotion",
            }
        },
        "data_policy": {
            "workspace_members": "excluded",
            "keycloak_identities": "excluded",
            "secure_deposit_links": "excluded",
            "secure_deposit_passwords": "excluded",
            "secure_deposit_files": "excluded",
            "raw_documents": "excluded",
            "knowledge_vectors": "excluded",
            "run_history": "excluded",
            "audit_log": "excluded",
            "collections": "metadata_only",
            "systems": "structure_and_config",
        },
    }
    emit_audit_event(
        workspace_id=workspace.id,
        event_type="workspace.blueprint.exported",
        actor=actor,
        details={
            "system_count": len(payload["systems"]),
            "capability_count": len(payload["capabilities"]),
            "collection_count": len(payload["knowledge"]["collections"]),
        },
        db=db,
    )
    return payload


def apply_workspace_blueprint(
    *,
    db: DBSession,
    workspace: Workspace,
    blueprint: Mapping[str, Any],
    actor: User | None,
    dry_run: bool = True,
    activate_systems: bool = False,
) -> dict[str, Any]:
    """Apply a workspace blueprint to ``workspace``.

    Dry-run is the default and performs no writes. Real import is additive:
    existing objects are reused by stable keys (slug/name/scope), and no raw
    data, members, credentials or historical runs are created.
    """
    _validate_blueprint(blueprint)
    actor_name = actor_display_name(actor)
    report: dict[str, Any] = {
        "dry_run": bool(dry_run),
        "activate_systems": bool(activate_systems),
        "workspace": {"id": workspace.id, "slug": workspace.slug, "name": workspace.name},
        "created": {"capabilities": 0, "contexts": 0, "collections": 0, "systems": 0, "presets": 0},
        "reused": {"capabilities": 0, "contexts": 0, "collections": 0, "systems": 0, "presets": 0},
        "skipped": [],
        "unresolved_skills": [],
        "actions": [],
    }

    capability_map = _apply_capabilities(
        db=db,
        workspace=workspace,
        capabilities=list(blueprint.get("capabilities") or []),
        dry_run=dry_run,
        report=report,
    )
    context_map = _apply_contexts(
        db=db,
        workspace=workspace,
        contexts=list(blueprint.get("contexts") or []),
        dry_run=dry_run,
        report=report,
    )
    _apply_collections(
        db=db,
        workspace=workspace,
        collections=list(((blueprint.get("knowledge") or {}).get("collections")) or []),
        actor=actor,
        dry_run=dry_run,
        report=report,
    )
    system_map = _apply_systems(
        db=db,
        workspace=workspace,
        systems=list(blueprint.get("systems") or []),
        capability_map=capability_map,
        context_map=context_map,
        actor_name=actor_name,
        dry_run=dry_run,
        activate_systems=activate_systems,
        report=report,
    )
    _apply_presets(
        db=db,
        workspace=workspace,
        presets_by_kind=blueprint.get("presets") or {},
        capability_map=capability_map,
        system_map=system_map,
        dry_run=dry_run,
        report=report,
    )
    _apply_iam_config(
        db=db,
        workspace=workspace,
        iam=blueprint.get("iam") or {},
        actor=actor,
        dry_run=dry_run,
        report=report,
    )

    if not dry_run:
        emit_audit_event(
            workspace_id=workspace.id,
            event_type="workspace.blueprint.applied",
            actor=actor_name,
            details={
                "source": blueprint.get("source") or {},
                "created": report["created"],
                "reused": report["reused"],
                "skipped_count": len(report["skipped"]),
                "dry_run": dry_run,
            },
            db=db,
        )
    return report


def _validate_blueprint(blueprint: Mapping[str, Any]) -> None:
    if not isinstance(blueprint, Mapping):
        raise WorkspaceBlueprintError("Blueprint must be a JSON object.")
    if blueprint.get("kind") != BLUEPRINT_KIND:
        raise WorkspaceBlueprintError(
            f"Unexpected blueprint kind: {blueprint.get('kind')!r} "
            f"(expected {BLUEPRINT_KIND!r})."
        )
    if blueprint.get("schema_version") != SCHEMA_VERSION:
        raise WorkspaceBlueprintError(
            f"Unsupported schema_version: {blueprint.get('schema_version')!r} "
            f"(expected {SCHEMA_VERSION})."
        )


def _serialize_capability(
    capability: Capability,
    *,
    workspace_id: str,
    skill_slugs_by_id: dict[str, str],
) -> dict[str, Any]:
    return {
        "slug": capability.slug,
        "name": capability.name,
        "description": capability.description or "",
        "tier": capability.tier,
        "industry": capability.industry,
        "input_unit": capability.input_unit,
        "output_unit": capability.output_unit,
        "skill_slugs": [
            skill_slugs_by_id[skill_id]
            for skill_id in (capability.skill_ids or [])
            if skill_id in skill_slugs_by_id
        ],
        "pricing": capability.pricing or {},
        "value_per_outcome": capability.value_per_outcome,
        "confidence_threshold": capability.confidence_threshold,
        "sla": capability.sla or {},
        "roi_model": capability.roi_model or {},
        "source_scope": "workspace" if capability.workspace_id == workspace_id else "global_reference",
    }


def _serialize_context(context: Context, *, systems_by_id: dict[str, System]) -> dict[str, Any]:
    system = systems_by_id.get(context.system_id or "")
    return {
        "name": context.name,
        "version": context.version,
        "system_name": system.name if system else None,
        "data_refs": context.data_refs or [],
        "memory_refs": context.memory_refs or [],
        "history_refs": context.history_refs or [],
        "environment_state": context.environment_state or {},
        "business_constraints": context.business_constraints or {},
        "permissions": context.permissions or {},
    }


def _serialize_system(
    *,
    db: DBSession,
    system: System,
    actor: str,
    capabilities_by_id: dict[str, Capability],
    contexts_by_id: dict[str, Context],
) -> dict[str, Any]:
    envelope = export_service.serialize_for_export(db=db, system=system, exported_by=actor)
    payload = dict(envelope["system"])
    capability = capabilities_by_id.get(system.capability_id or "")
    context = contexts_by_id.get(system.context_id or "")
    payload.update(
        {
            "capability_slug": capability.slug if capability else None,
            "context_name": context.name if context else None,
            "source_status": system.status,
            "import_status_default": "draft",
        }
    )
    return payload


def _serialize_collection(collection: KnowledgeCollection) -> dict[str, Any]:
    return {
        "slug": collection.slug,
        "name": collection.name,
        "description": collection.description or "",
        "embedding_model": collection.embedding_model,
        "chunking_method": collection.chunking_method,
        "chunking_params": collection.chunking_params or {},
        "source_status": collection.status,
        "source_document_count": collection.document_count or 0,
        "source_chunk_count": collection.chunk_count or 0,
    }


def _serialize_preset(
    preset: RagPreset | EvaluationPreset,
    *,
    systems_by_id: dict[str, System],
    capabilities_by_id: dict[str, Capability],
) -> dict[str, Any]:
    scope_ref = None
    if preset.scope == "system":
        system = systems_by_id.get(preset.scope_id or "")
        scope_ref = system.name if system else None
    elif preset.scope == "capability":
        capability = capabilities_by_id.get(preset.scope_id or "")
        scope_ref = capability.slug if capability else None
    return {
        "name": preset.name,
        "scope": preset.scope,
        "scope_ref": scope_ref,
        "config": preset.config or {},
        "is_default": bool(preset.is_default),
    }


def _apply_capabilities(
    *,
    db: DBSession,
    workspace: Workspace,
    capabilities: list[Mapping[str, Any]],
    dry_run: bool,
    report: dict[str, Any],
) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for item in capabilities:
        slug = str(item.get("slug") or "").strip()
        if not slug:
            report["skipped"].append({"kind": "capability", "reason": "missing_slug"})
            continue
        existing = (
            db.query(Capability)
            .filter(Capability.slug == slug)
            .filter((Capability.workspace_id == workspace.id) | (Capability.workspace_id.is_(None)))
            .first()
        )
        if existing:
            out[slug] = existing.id
            report["reused"]["capabilities"] += 1
            report["actions"].append({"kind": "capability", "slug": slug, "action": "reuse"})
            continue
        target_slug = slug
        collision = db.query(Capability).filter(Capability.slug == slug).first()
        if collision:
            target_slug = _unique_capability_slug(db, f"{slug}-{workspace.slug}")
        report["created"]["capabilities"] += 1
        report["actions"].append(
            {
                "kind": "capability",
                "slug": target_slug,
                "source_slug": slug,
                "action": "create" if target_slug == slug else "create_renamed",
            }
        )
        skill_ids = _resolve_skill_slugs(
            db=db,
            workspace_id=workspace.id,
            slugs=list(item.get("skill_slugs") or []),
        )
        if dry_run:
            out[slug] = f"dry-run:{target_slug}"
            continue
        capability = Capability(
            id=str(uuid4()),
            workspace_id=workspace.id,
            slug=target_slug,
            name=item.get("name") or slug,
            description=item.get("description") or "",
            tier=item.get("tier") or "client",
            industry=item.get("industry"),
            input_unit=item.get("input_unit") or "request",
            output_unit=item.get("output_unit") or "answer",
            skill_ids=skill_ids,
            pricing=item.get("pricing") or {},
            value_per_outcome=item.get("value_per_outcome"),
            confidence_threshold=item.get("confidence_threshold"),
            sla=item.get("sla") or {},
            roi_model=item.get("roi_model") or {},
            is_seeded="N",
        )
        db.add(capability)
        db.flush()
        out[slug] = capability.id
    return out


def _unique_capability_slug(db: DBSession, base_slug: str) -> str:
    base = (base_slug or "capability").strip("-_")[:110] or "capability"
    candidate = base
    index = 2
    while db.query(Capability).filter(Capability.slug == candidate).first():
        suffix = f"-{index}"
        candidate = f"{base[:120 - len(suffix)]}{suffix}"
        index += 1
    return candidate


def _resolve_skill_slugs(
    *,
    db: DBSession,
    workspace_id: str,
    slugs: list[str],
) -> list[str]:
    if not slugs:
        return []
    rows = (
        db.query(Skill)
        .filter(Skill.slug.in_(slugs))
        .filter((Skill.workspace_id == workspace_id) | (Skill.workspace_id.is_(None)))
        .all()
    )
    by_slug = {row.slug: row.id for row in rows}
    return [by_slug[slug] for slug in slugs if slug in by_slug]


def _apply_contexts(
    *,
    db: DBSession,
    workspace: Workspace,
    contexts: list[Mapping[str, Any]],
    dry_run: bool,
    report: dict[str, Any],
) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for item in contexts:
        name = str(item.get("name") or "").strip()
        if not name:
            report["skipped"].append({"kind": "context", "reason": "missing_name"})
            continue
        existing = (
            db.query(Context)
            .filter(Context.workspace_id == workspace.id, Context.name == name, Context.ephemeral.is_(False))
            .first()
        )
        if existing:
            out[name] = existing.id
            report["reused"]["contexts"] += 1
            report["actions"].append({"kind": "context", "name": name, "action": "reuse"})
            continue
        report["created"]["contexts"] += 1
        report["actions"].append({"kind": "context", "name": name, "action": "create"})
        if dry_run:
            out[name] = f"dry-run:{name}"
            continue
        context = Context(
            id=str(uuid4()),
            workspace_id=workspace.id,
            name=name,
            version=int(item.get("version") or 1),
            data_refs=item.get("data_refs") or [],
            memory_refs=item.get("memory_refs") or [],
            history_refs=item.get("history_refs") or [],
            environment_state=item.get("environment_state") or {},
            business_constraints=item.get("business_constraints") or {},
            permissions=item.get("permissions") or {},
            ephemeral=False,
        )
        db.add(context)
        db.flush()
        out[name] = context.id
    return out


def _apply_collections(
    *,
    db: DBSession,
    workspace: Workspace,
    collections: list[Mapping[str, Any]],
    actor: User | None,
    dry_run: bool,
    report: dict[str, Any],
) -> None:
    for item in collections:
        slug = str(item.get("slug") or "").strip()
        name = str(item.get("name") or slug or "").strip()
        if not slug or not name:
            report["skipped"].append({"kind": "collection", "reason": "missing_slug_or_name"})
            continue
        existing = (
            db.query(KnowledgeCollection)
            .filter(KnowledgeCollection.workspace_id == workspace.id, KnowledgeCollection.slug == slug)
            .first()
        )
        if existing:
            report["reused"]["collections"] += 1
            report["actions"].append({"kind": "collection", "slug": slug, "action": "reuse"})
            continue
        report["created"]["collections"] += 1
        report["actions"].append({"kind": "collection", "slug": slug, "action": "create_metadata_only"})
        if not dry_run:
            collection = knowledge_collections.create_collection(
                db,
                workspace=workspace,
                name=name,
                description=item.get("description") or "",
                created_by_user_id=actor.id if actor else None,
                slug=slug,
            )
            collection.embedding_model = item.get("embedding_model") or collection.embedding_model
            collection.chunking_method = item.get("chunking_method")
            collection.chunking_params = item.get("chunking_params") or {}


def _apply_systems(
    *,
    db: DBSession,
    workspace: Workspace,
    systems: list[Mapping[str, Any]],
    capability_map: dict[str, str | None],
    context_map: dict[str, str | None],
    actor_name: str,
    dry_run: bool,
    activate_systems: bool,
    report: dict[str, Any],
) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for item in systems:
        name = str(item.get("name") or "").strip()
        if not name:
            report["skipped"].append({"kind": "system", "reason": "missing_name"})
            continue
        existing = (
            db.query(System)
            .filter(System.workspace_id == workspace.id, System.name == name)
            .first()
        )
        if existing:
            out[name] = existing.id
            report["reused"]["systems"] += 1
            report["actions"].append({"kind": "system", "name": name, "action": "reuse"})
            continue

        envelope = {
            "kind": export_service.ENVELOPE_KIND,
            "schema_version": export_service.SCHEMA_VERSION,
            "system": dict(item),
        }
        try:
            create_kwargs, rebind_report = export_service.prepare_import(
                db=db,
                envelope=envelope,
                workspace_id=workspace.id,
                target_name=name,
            )
        except export_service.ChainExportError as exc:
            report["skipped"].append({"kind": "system", "name": name, "reason": str(exc)})
            continue

        flow = create_kwargs.get("flow_definition") or {}
        issues = dag_validator.validate_flow(flow)
        if dag_validator.has_errors(issues):
            report["skipped"].append(
                {
                    "kind": "system",
                    "name": name,
                    "reason": "flow_invalid",
                    "issues": dag_validator.issues_to_payload(issues),
                }
            )
            continue

        report["unresolved_skills"].extend(rebind_report.get("unresolved_skills", []))
        report["created"]["systems"] += 1
        report["actions"].append({"kind": "system", "name": name, "action": "create"})
        if dry_run:
            out[name] = f"dry-run:{name}"
            continue
        system = System(
            id=str(uuid4()),
            workspace_id=workspace.id,
            name=name,
            objective=create_kwargs["objective"],
            capability_id=capability_map.get(item.get("capability_slug") or "") or None,
            skill_ids=create_kwargs["skill_ids"],
            flow_definition=flow,
            execution_mode=create_kwargs["execution_mode"],
            execution_profile=create_kwargs["execution_profile"] or None,
            coordination_pattern=create_kwargs["coordination_pattern"],
            context_id=context_map.get(item.get("context_name") or "") or None,
            status=item.get("source_status") if activate_systems else "draft",
            created_by=actor_name,
            default_prompt_type=create_kwargs["default_prompt_type"],
            default_model=create_kwargs["default_model"],
            retrieval_mode_default=create_kwargs["retrieval_mode_default"] or "auto",
        )
        db.add(system)
        db.flush()
        version_service.record_new_version(
            db=db,
            system=system,
            flow_definition=flow,
            created_by=actor_name,
            message="Imported from workspace blueprint",
        )
        out[name] = system.id
    report["unresolved_skills"] = sorted(set(report["unresolved_skills"]))
    return out


def _apply_presets(
    *,
    db: DBSession,
    workspace: Workspace,
    presets_by_kind: Mapping[str, Any],
    capability_map: dict[str, str | None],
    system_map: dict[str, str | None],
    dry_run: bool,
    report: dict[str, Any],
) -> None:
    for kind, model in (("rag", RagPreset), ("evaluation", EvaluationPreset)):
        for item in presets_by_kind.get(kind) or []:
            name = str(item.get("name") or "").strip()
            scope = str(item.get("scope") or "workspace")
            if not name or scope not in {"workspace", "capability", "system"}:
                report["skipped"].append({"kind": f"{kind}_preset", "name": name, "reason": "invalid_scope_or_name"})
                continue
            scope_id = None
            if scope == "capability":
                scope_id = capability_map.get(str(item.get("scope_ref") or ""))
            elif scope == "system":
                scope_id = system_map.get(str(item.get("scope_ref") or ""))
            if scope != "workspace" and not scope_id:
                report["skipped"].append(
                    {"kind": f"{kind}_preset", "name": name, "reason": "unresolved_scope_ref"}
                )
                continue
            existing = (
                db.query(model)
                .filter(
                    model.workspace_id == workspace.id,
                    model.name == name,
                    model.scope == scope,
                    model.scope_id == scope_id,
                )
                .first()
            )
            if existing:
                report["reused"]["presets"] += 1
                report["actions"].append({"kind": f"{kind}_preset", "name": name, "action": "reuse"})
                continue
            report["created"]["presets"] += 1
            report["actions"].append({"kind": f"{kind}_preset", "name": name, "action": "create"})
            if not dry_run:
                db.add(
                    model(
                        id=str(uuid4()),
                        workspace_id=workspace.id,
                        name=name,
                        scope=scope,
                        scope_id=scope_id,
                        config=item.get("config") or {},
                        is_default=bool(item.get("is_default")),
                    )
                )
                db.flush()


def _apply_iam_config(
    *,
    db: DBSession,
    workspace: Workspace,
    iam: Mapping[str, Any],
    actor: User | None,
    dry_run: bool,
    report: dict[str, Any],
) -> None:
    role_flags = iam.get("role_flags")
    capability_overrides = iam.get("capability_overrides")
    if not role_flags and not capability_overrides:
        return
    report["actions"].append({"kind": "iam_config", "action": "patch" if not dry_run else "dry_run_patch"})
    if not dry_run:
        patch_iam_config(
            db,
            workspace_id=workspace.id,
            role_flags=role_flags if isinstance(role_flags, dict) else None,
            capability_overrides=capability_overrides if isinstance(capability_overrides, dict) else None,
            updated_by_user_id=actor.id if actor else None,
        )
