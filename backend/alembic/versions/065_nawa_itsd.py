"""Seed the Nawa IT service desk password-reset surface (system + entitlement).

Additive and idempotent, modelled on 060: expands the workspace-app CHECK with
``nawa-itsd``, grants that entitlement to existing ``nawa`` members, writes the
business navigation profile, and inserts/updates the ``Password Reset`` System
carrying the pinned flow artifact
``app/resources/flows/nawa_password_reset_v1.json``.

Every step is guarded: the CHECK widening runs on its own, and the seeding half
is a no-op when the ``nawa`` workspace does not exist yet (it is created by the
operator in a later phase) — the migration must never fail on a database that
has no Nawa workspace, and must never touch another workspace's rows.

The System carries BOTH flows: ``flow_definition`` is the one with the two real
model calls, and ``settings.fallback_flow_definition`` is the fully simulated
twin. Swapping them is a single PATCH on the System, which is the sub-minute
degradation path if the model provider misbehaves on stage.

No ControlPolicy is materialised on purpose: the human gate is a ``hitl`` node
inside the flow, and a membrane carrying
``mandatory_hitl_if_confidence_below`` would add a second, invisible pause on
top of it.

Revision ID: 065_nawa_itsd
Revises: 064_run_dispatch_outbox
Create Date: 2026-07-28
"""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "065_nawa_itsd"
down_revision = "064_run_dispatch_outbox"
branch_labels = None
depends_on = None


NAWA_SLUG = "nawa"
NAWA_APP_KEY = "nawa-itsd"
# Mirrors the WorkspaceApp enum, whose declaration order is the canonical order
# `normalize_app_entitlements` enforces on `navigation_profile.primary_surfaces`.
PREV_APP_KEYS = ("chat", "client360-pdr", "knowledge-capture", "fse-reports")
NEW_APP_KEYS = (*PREV_APP_KEYS, NAWA_APP_KEY)
CK_WORKSPACE_APPS = "ck_workspace_member_app_entitlements_app_key"

SEED_ORIGIN = "065_nawa_itsd"
SYSTEM_NAME = "Password Reset"
CAPABILITY_SLUG = "workspace_assistant"
MIGRATION_MARKER_KEY = "_migration_065_nawa_itsd_state"

# The workspace lands on the ITSD catalogue but keeps the full cockpit shell.
# `standard` is deliberate and load-bearing: the `business_end_user` shell
# whitelists the paths it will serve, and `/runs/{id}` and `/systems/{id}/flow`
# — the trace and the Flow Builder, both required by the demo — are not on that
# list, so it would bounce them to /chat and drop `default_route` on the floor
# too. `chat` stays granted so the assistant conversation is one click away.
# Surface order must match NEW_APP_KEYS: `normalize_app_entitlements` rejects a
# `primary_surfaces` list that is not in canonical app order.
NAVIGATION_PROFILE = {
    "key": "standard",
    "default_route": "/nawa/itsd",
    "primary_surfaces": ["chat", NAWA_APP_KEY],
    "advanced_access": "admin_only",
}

# White-label identity of the platform chrome for this workspace: the title bar
# and the browser tab carry the customer brand while the platform navigation and
# its vocabulary (Build, Operate, Flow Builder, Skills) stay as they are. Read by
# the frontend `platform_brand` reader, which refuses a half declaration; absent
# the key, the chrome stays Agentium, which is every other workspace's case.
# `home` is where the branded emblem returns, so an operator who pivoted into the
# cockpit has one click back to the customer app.
PLATFORM_BRAND = {
    "label": "NAWA WE",
    "emblem": "/assets/nawa/nawa-logo.png",
    "home": "/nawa/itsd",
}

# The flow binds these by slug, and none of them is attached to a Capability,
# so they resolve to nothing in this workspace's catalogue unless the workspace
# names them itself. Harmless today (the release under demo performs no binding
# check) and required tomorrow: the binding validator refuses any node whose
# skill is not in the System's resolved visible skills. Written here so it
# survives a dump restore instead of living only in an API call someone made
# once. Additive and workspace-scoped — no other workspace sees it.
CATALOG_ENABLED_SKILLS = (
    "azure_llm_v1",
    "response_eval_v1",
    "rpa_dispatch_v1",
    "audit_log_v1",
)

ARTIFACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "resources"
    / "flows"
    / "nawa_password_reset_v1.json"
)

# Skills the flow binds by slug. Upserted if absent so `skill_id` resolution
# never leaves a hole, whatever order the catalog seed ran in. Metadata mirrors
# the canonical entries in app/services/skills_registry/seed.py.
REQUIRED_SKILLS = (
    {
        "slug": "azure_llm_v1",
        "name": "Azure OpenAI LLM",
        "description": "LLM call routed through Azure OpenAI.",
        "type": "llm",
        "provider": "azure",
        "certification_level": "production",
    },
    {
        "slug": "response_eval_v1",
        "name": "Response Eval",
        "description": (
            "Embedding-based RAG quality wrapper around ResponseEvaluator. Single authoritative "
            "source of the 0-100 composite, with hallucination_rate and context_count."
        ),
        "type": "analysis",
        "provider": "internal",
        "certification_level": "production",
    },
    {
        "slug": "rpa_dispatch_v1",
        "name": "RPA Dispatch",
        "description": (
            "Dispatches a job to the workspace RPA Bridge connector (generic REST orchestrator) "
            "and polls to completion within a bounded timeout."
        ),
        "type": "connector",
        "provider": "internal",
        "certification_level": "beta",
    },
    {
        "slug": "audit_log_v1",
        "name": "Audit Log",
        "description": "Persists a typed audit event for compliance and replay.",
        "type": "compliance",
        "provider": "internal",
        "certification_level": "enterprise",
    },
)


def _check_sql(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


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


def _constraint_exists(bind, table_name: str, constraint_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in set(inspector.get_table_names()):
        return False
    return any(c["name"] == constraint_name for c in inspector.get_check_constraints(table_name))


def _load_artifact() -> Optional[dict[str, Any]]:
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
    members = sa.table(
        "workspace_members",
        sa.column("id"),
        sa.column("workspace_id"),
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
    capabilities = sa.table(
        "capabilities",
        sa.column("id"),
        sa.column("slug"),
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
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
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
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    return workspaces, members, entitlements, capabilities, skills, systems


def _ensure_required_skills(bind, skills, now) -> None:
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


def _resolve_flow_skill_ids(bind, skills, *flows: dict[str, Any]) -> list[str]:
    """Fill each task node's ``config.skill_id`` from its ``skill_slug``.

    Mutates every flow in place and returns the de-duplicated list of resolved
    ids, for ``System.skill_ids``.
    """
    slugs = {
        (node.get("config") or {}).get("skill_slug")
        for flow in flows
        for node in flow.get("nodes") or []
        if isinstance(node, dict) and (node.get("config") or {}).get("skill_slug")
    }
    id_by_slug: dict[str, str] = {}
    if slugs:
        rows = bind.execute(
            sa.select(skills.c.id, skills.c.slug).where(skills.c.slug.in_(slugs))
        ).all()
        id_by_slug = {r._mapping["slug"]: r._mapping["id"] for r in rows}

    ordered: list[str] = []
    for flow in flows:
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


def _grant_entitlements(bind, tables, workspace_id, now) -> None:
    _workspaces, members, entitlements, _caps, _skills, _systems = tables
    member_ids = [
        row._mapping["id"]
        for row in bind.execute(
            sa.select(members.c.id).where(members.c.workspace_id == workspace_id)
        ).all()
    ]
    for member_id in member_ids:
        exists = bind.execute(
            sa.select(entitlements.c.id)
            .where(entitlements.c.workspace_member_id == member_id)
            .where(entitlements.c.app_key == NAWA_APP_KEY)
        ).first()
        if exists:
            continue
        bind.execute(
            sa.insert(entitlements).values(
                workspace_member_id=member_id,
                app_key=NAWA_APP_KEY,
                granted_at=now,
                granted_by_user_id=None,
                grant_source=SEED_ORIGIN,
            )
        )


def _merge_catalog_override(settings: dict[str, Any]) -> None:
    """Union the slugs the flow needs into ``settings.catalog.enabled_skills``.

    Read-modify-write on the sub-key, never a replacement of ``catalog``: that
    dict also carries ``family``, and dropping it would silently re-scope the
    whole resolved catalogue of the workspace.

    Membership is compared case-insensitively because the reader lower-cases
    every entry, so a differently-cased duplicate would be invisible at runtime
    and would make a second run of this migration non-idempotent.
    """
    catalog = settings.get("catalog")
    catalog = dict(catalog) if isinstance(catalog, dict) else {}
    enabled = [s for s in catalog.get("enabled_skills") or [] if isinstance(s, str)]
    present = {s.strip().lower() for s in enabled}
    for slug in CATALOG_ENABLED_SKILLS:
        if slug.lower() not in present:
            enabled.append(slug)
            present.add(slug.lower())
    catalog["enabled_skills"] = enabled
    settings["catalog"] = catalog


def _write_workspace_settings(bind, workspaces, workspace_id, settings, now) -> None:
    profile = settings.get("navigation_profile")
    if isinstance(profile, dict):
        # An operator-authored profile keeps its own shape; we only make sure
        # the new surface is present, in the canonical app order.
        profile = dict(profile)
        surfaces = [s for s in profile.get("primary_surfaces") or [] if isinstance(s, str)]
        if NAWA_APP_KEY not in surfaces:
            surfaces.append(NAWA_APP_KEY)
        profile["primary_surfaces"] = [k for k in NEW_APP_KEYS if k in set(surfaces)]
    else:
        profile = deepcopy(NAVIGATION_PROFILE)
    settings["navigation_profile"] = profile
    # An operator-authored brand is authoritative: we only fill the hole.
    if not isinstance(settings.get("platform_brand"), dict):
        settings["platform_brand"] = deepcopy(PLATFORM_BRAND)
    _merge_catalog_override(settings)
    settings[MIGRATION_MARKER_KEY] = {"schema": 1, "applied_at": now.isoformat()}
    bind.execute(
        sa.update(workspaces).where(workspaces.c.id == workspace_id).values(settings=settings)
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "workspace_member_app_entitlements" in tables:
        if _constraint_exists(bind, "workspace_member_app_entitlements", CK_WORKSPACE_APPS):
            with op.batch_alter_table("workspace_member_app_entitlements") as batch:
                batch.drop_constraint(CK_WORKSPACE_APPS, type_="check")
        with op.batch_alter_table("workspace_member_app_entitlements") as batch:
            batch.create_check_constraint(
                CK_WORKSPACE_APPS,
                _check_sql("app_key", NEW_APP_KEYS),
            )

    if not {"workspaces", "systems", "skills"}.issubset(tables):
        return

    artifact = _load_artifact()
    if not artifact:
        return
    flow = _as_dict(artifact.get("flow_definition"))
    fallback_flow = _as_dict(artifact.get("fallback_flow_definition"))
    if not flow:
        return

    db_tables = _tables()
    workspaces, _members, _entitlements, capabilities, skills, systems = db_tables

    # The Nawa workspace is created by the operator, possibly after this
    # migration has run. Its absence is a normal state, not a failure.
    rows = bind.execute(
        sa.select(workspaces.c.id, workspaces.c.settings).where(workspaces.c.slug == NAWA_SLUG)
    ).all()
    if not rows:
        return

    now = datetime.utcnow()
    _ensure_required_skills(bind, skills, now)
    skill_ids = _resolve_flow_skill_ids(bind, skills, flow, fallback_flow)

    cap_row = bind.execute(
        sa.select(capabilities.c.id).where(capabilities.c.slug == CAPABILITY_SLUG)
    ).first()
    capability_id = cap_row._mapping["id"] if cap_row else None

    artifact_system = artifact.get("system") if isinstance(artifact.get("system"), dict) else {}
    settings_payload = _as_dict(artifact.get("system_settings"))
    settings_payload["seed_origin"] = SEED_ORIGIN
    if fallback_flow:
        settings_payload["fallback_flow_definition"] = fallback_flow

    for row in rows:
        ws = row._mapping
        workspace_id = ws["id"]

        _write_workspace_settings(
            bind, workspaces, workspace_id, _as_dict(ws["settings"]), now
        )
        if {"workspace_members", "workspace_member_app_entitlements"}.issubset(tables):
            _grant_entitlements(bind, db_tables, workspace_id, now)

        # Marker-scoped lookup: only ever update the System WE seeded, never an
        # operator-authored one that happens to share the name.
        ours = None
        for existing in bind.execute(
            sa.select(systems.c.id, systems.c.settings).where(
                systems.c.workspace_id == workspace_id,
                systems.c.name == SYSTEM_NAME,
            )
        ).all():
            if _as_dict(existing._mapping["settings"]).get("seed_origin") == SEED_ORIGIN:
                ours = existing._mapping
                break

        values = dict(
            capability_id=capability_id,
            skill_ids=skill_ids,
            flow_definition=deepcopy(flow),
            settings=deepcopy(settings_payload),
            status="active",
            default_model=artifact_system.get("default_model") or "gpt-4o-mini",
            updated_at=now,
        )
        if ours is not None:
            bind.execute(
                sa.update(systems).where(systems.c.id == ours["id"]).values(**values)
            )
            continue
        bind.execute(
            sa.insert(systems).values(
                id=str(uuid4()),
                workspace_id=workspace_id,
                name=SYSTEM_NAME,
                objective=artifact_system.get("objective") or SYSTEM_NAME,
                execution_mode=artifact_system.get("execution_mode") or "human_augmented",
                execution_profile={
                    "surface": NAWA_APP_KEY,
                    "durability": "audit_events",
                    "simulated_system_actions": True,
                },
                coordination_pattern=artifact_system.get("coordination_pattern")
                or "single_agent",
                created_by=f"system:{SEED_ORIGIN}",
                retrieval_mode_default="auto",
                created_at=now,
                **values,
            )
        )


def downgrade() -> None:
    """Retire what we seeded; never delete another workspace's data.

    The System is flipped to ``retired`` rather than deleted so its runs, their
    invocations and the audit events that reference them stay readable.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "workspace_member_app_entitlements" in tables:
        entitlements = sa.table(
            "workspace_member_app_entitlements",
            sa.column("id"),
            sa.column("app_key"),
            sa.column("grant_source"),
        )
        bind.execute(
            sa.delete(entitlements)
            .where(entitlements.c.app_key == NAWA_APP_KEY)
            .where(entitlements.c.grant_source == SEED_ORIGIN)
        )
        if _constraint_exists(bind, "workspace_member_app_entitlements", CK_WORKSPACE_APPS):
            with op.batch_alter_table("workspace_member_app_entitlements") as batch:
                batch.drop_constraint(CK_WORKSPACE_APPS, type_="check")
        with op.batch_alter_table("workspace_member_app_entitlements") as batch:
            batch.create_check_constraint(
                CK_WORKSPACE_APPS,
                _check_sql("app_key", PREV_APP_KEYS),
            )

    if "workspaces" not in tables:
        return

    workspaces, _members, _entitlements, _caps, _skills, systems = _tables()
    rows = bind.execute(
        sa.select(workspaces.c.id, workspaces.c.settings).where(workspaces.c.slug == NAWA_SLUG)
    ).all()
    for row in rows:
        ws = row._mapping
        settings = _as_dict(ws["settings"])
        profile = settings.get("navigation_profile")
        if isinstance(profile, dict):
            profile = dict(profile)
            profile["primary_surfaces"] = [
                s
                for s in profile.get("primary_surfaces") or []
                if isinstance(s, str) and s != NAWA_APP_KEY
            ]
            settings["navigation_profile"] = profile
        # Only ever remove the brand we wrote: an operator-authored one is theirs.
        if settings.get("platform_brand") == PLATFORM_BRAND:
            settings.pop("platform_brand", None)
        catalog = settings.get("catalog")
        if isinstance(catalog, dict):
            catalog = dict(catalog)
            ours = {s.lower() for s in CATALOG_ENABLED_SKILLS}
            remaining = [
                s
                for s in catalog.get("enabled_skills") or []
                if isinstance(s, str) and s.strip().lower() not in ours
            ]
            if remaining:
                catalog["enabled_skills"] = remaining
                settings["catalog"] = catalog
            else:
                catalog.pop("enabled_skills", None)
                settings["catalog"] = catalog
                if not catalog:
                    settings.pop("catalog", None)
        settings.pop(MIGRATION_MARKER_KEY, None)
        bind.execute(
            sa.update(workspaces).where(workspaces.c.id == ws["id"]).values(settings=settings)
        )

        if "systems" not in tables:
            continue
        for existing in bind.execute(
            sa.select(systems.c.id, systems.c.settings).where(
                systems.c.workspace_id == ws["id"],
                systems.c.name == SYSTEM_NAME,
            )
        ).all():
            if _as_dict(existing._mapping["settings"]).get("seed_origin") != SEED_ORIGIN:
                continue
            bind.execute(
                sa.update(systems)
                .where(systems.c.id == existing._mapping["id"])
                .values(status="retired")
            )
