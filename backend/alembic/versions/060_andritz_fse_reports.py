"""Seed Andritz FSE intervention-report surface (system + entitlement).

Expands the workspace-app CHECK to include ``fse-reports``, grants that
entitlement to existing Andritz members, adds the surface to the business
navigation profile, and inserts/updates the constrained capture System
``Rapport d'intervention FSE`` with ``settings.capture.template_id``.

Revision ID: 060_andritz_fse_reports
Revises: 059_andritz_agentic_default
Create Date: 2026-07-20
"""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "060_andritz_fse_reports"
down_revision = "059_andritz_agentic_default"
branch_labels = None
depends_on = None

ANDRITZ_SLUG = "andritz"
FSE_APP_KEY = "fse-reports"
PREV_APP_KEYS = ("chat", "client360-pdr", "knowledge-capture")
NEW_APP_KEYS = (*PREV_APP_KEYS, FSE_APP_KEY)
CK_WORKSPACE_APPS = "ck_workspace_member_app_entitlements_app_key"
BACKFILL_SOURCE = "060_andritz_fse_reports"
SYSTEM_NAME = "Rapport d'intervention FSE"
CAPABILITY_SLUG = "expert_knowledge_capture"
TEMPLATE_ID = "fse_intervention_v1"
MIGRATION_MARKER_KEY = "_migration_060_andritz_fse_reports_state"


def _check_sql(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


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


def _constraint_exists(bind, table_name: str, constraint_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in set(inspector.get_table_names()):
        return False
    return any(c["name"] == constraint_name for c in inspector.get_check_constraints(table_name))


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

    if "workspaces" not in tables or "systems" not in tables:
        return

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
        sa.column("retrieval_mode_default"),
        sa.column("created_at"),
        sa.column("updated_at"),
    )

    cap_row = bind.execute(
        sa.select(capabilities.c.id).where(capabilities.c.slug == CAPABILITY_SLUG)
    ).first()
    cap_id = cap_row._mapping["id"] if cap_row else None
    now = datetime.utcnow()

    rows = bind.execute(
        sa.select(workspaces.c.id, workspaces.c.settings).where(workspaces.c.slug == ANDRITZ_SLUG)
    ).all()
    for row in rows:
        ws = row._mapping
        workspace_id = ws["id"]
        settings = _as_settings(ws["settings"])

        # Navigation surface
        profile = settings.get("navigation_profile")
        if isinstance(profile, dict) and profile.get("key") == "business_end_user":
            profile = dict(profile)
            surfaces = [s for s in profile.get("primary_surfaces", []) if isinstance(s, str)]
            if FSE_APP_KEY not in surfaces:
                if "knowledge-capture" in surfaces:
                    idx = surfaces.index("knowledge-capture") + 1
                    surfaces.insert(idx, FSE_APP_KEY)
                else:
                    surfaces.append(FSE_APP_KEY)
            profile["primary_surfaces"] = surfaces
            settings["navigation_profile"] = profile

        settings[MIGRATION_MARKER_KEY] = {"schema": 1, "applied_at": now.isoformat()}
        bind.execute(
            sa.update(workspaces).where(workspaces.c.id == workspace_id).values(settings=settings)
        )

        # Entitlement backfill for Andritz members
        if "workspace_member_app_entitlements" in tables and "workspace_members" in tables:
            member_ids = [
                m._mapping["id"]
                for m in bind.execute(
                    sa.select(members.c.id).where(members.c.workspace_id == workspace_id)
                ).all()
            ]
            for member_id in member_ids:
                exists = bind.execute(
                    sa.select(entitlements.c.id)
                    .where(entitlements.c.workspace_member_id == member_id)
                    .where(entitlements.c.app_key == FSE_APP_KEY)
                ).first()
                if exists:
                    continue
                bind.execute(
                    sa.insert(entitlements).values(
                        workspace_member_id=member_id,
                        app_key=FSE_APP_KEY,
                        granted_at=now,
                        granted_by_user_id=None,
                        grant_source=BACKFILL_SOURCE,
                    )
                )

        if not cap_id:
            continue

        flow = {
            "schema_version": 3,
            "variant": "expert_knowledge_capture",
            "source": "migration_060",
            "extended": True,
            "template_id": "fse-intervention-report-v1",
            "template_name": SYSTEM_NAME,
            "nodes": [],
            "edges": [],
            "collections": [],
            "rag_mode": "C-HAH",
            "canonical_rag_mode": "chah",
            "ui": {
                "type": "knowledge_capture",
                "label": SYSTEM_NAME,
                "entry_route": "interventions",
                "primary_action": "Nouveau rapport",
                "legacy_route": "/knowledge/interventions",
                "surface": "fse-reports",
            },
        }
        system_settings = {
            "capture": {"template_id": TEMPLATE_ID},
            "surface": "fse-reports",
            "surface_routes": ["/knowledge/interventions"],
        }
        existing = bind.execute(
            sa.select(systems.c.id)
            .where(systems.c.workspace_id == workspace_id)
            .where(systems.c.name == SYSTEM_NAME)
        ).first()
        if existing:
            bind.execute(
                sa.update(systems)
                .where(systems.c.id == existing._mapping["id"])
                .values(
                    capability_id=cap_id,
                    settings=system_settings,
                    status="active",
                    execution_mode="human_augmented",
                    updated_at=now,
                )
            )
            continue
        bind.execute(
            sa.insert(systems).values(
                id=str(uuid4()),
                workspace_id=workspace_id,
                name=SYSTEM_NAME,
                objective=(
                    "Produire des rapports d'intervention terrain structurés (Visit Report) : "
                    "plan type verrouillé, champs obligatoires, synthèse contrainte et publication "
                    "dans la collection andritz-fse-reports."
                ),
                capability_id=cap_id,
                skill_ids=[],
                flow_definition=flow,
                settings=system_settings,
                execution_mode="human_augmented",
                execution_profile={
                    "runtime": "voice2voice_cascade",
                    "surface": "fse-reports",
                    "durability": "audit_events",
                },
                coordination_pattern="single_agent",
                status="active",
                created_by="system:fse_report_seed",
                retrieval_mode_default="chah",
                created_at=now,
                updated_at=now,
            )
        )


def downgrade() -> None:
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
            .where(entitlements.c.app_key == FSE_APP_KEY)
            .where(entitlements.c.grant_source == BACKFILL_SOURCE)
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
        sa.column("created_by"),
        sa.column("status"),
    )

    rows = bind.execute(
        sa.select(workspaces.c.id, workspaces.c.settings).where(workspaces.c.slug == ANDRITZ_SLUG)
    ).all()
    for row in rows:
        ws = row._mapping
        settings = _as_settings(ws["settings"])
        profile = settings.get("navigation_profile")
        if isinstance(profile, dict):
            surfaces = [s for s in profile.get("primary_surfaces", []) if isinstance(s, str)]
            profile = dict(profile)
            profile["primary_surfaces"] = [s for s in surfaces if s != FSE_APP_KEY]
            settings["navigation_profile"] = profile
        settings.pop(MIGRATION_MARKER_KEY, None)
        bind.execute(
            sa.update(workspaces).where(workspaces.c.id == ws["id"]).values(settings=settings)
        )
        if "systems" in tables:
            bind.execute(
                sa.update(systems)
                .where(systems.c.workspace_id == ws["id"])
                .where(systems.c.name == SYSTEM_NAME)
                .where(systems.c.created_by == "system:fse_report_seed")
                .values(status="retired")
            )
