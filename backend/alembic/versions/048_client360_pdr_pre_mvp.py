"""Client360 PDR pre-MVP workspace system and data model.

Revision ID: 048_client360_pdr
Revises: 047_andritz_membrane
Create Date: 2026-07-08
"""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "048_client360_pdr"
down_revision = "047_andritz_membrane"
branch_labels = None
depends_on = None


CAPABILITY_SLUG = "client360_pdr_opportunity_engine"
SYSTEM_VARIANT = "client360_pdr"
SYSTEM_NAME = "Client360 PDR"


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


def _create_tables() -> None:
    op.create_table(
        "client360_data_sources",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("source_type", sa.String(length=40), nullable=False, server_default="other"),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("filename", sa.Text(), nullable=True),
        sa.Column("collection_id", sa.String(length=36), sa.ForeignKey("knowledge_collections.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("collection_slug", sa.String(length=120), nullable=True, index=True),
        sa.Column("knowledge_source_id", sa.String(length=36), sa.ForeignKey("knowledge_collection_sources.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("deposit_file_id", sa.String(length=36), sa.ForeignKey("deposit_files.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="candidate"),
        sa.Column("row_count", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("evidence_refs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "source_type IN ('installed_base', 'periodicity', 'sap_sales_history', 'contact_hub', 'market_signal', 'other')",
            name="ck_client360_data_sources_type",
        ),
        sa.CheckConstraint(
            "status IN ('candidate', 'mapped', 'ready', 'needs_review', 'error', 'archived')",
            name="ck_client360_data_sources_status",
        ),
    )
    op.create_index("ix_client360_data_sources_workspace_type", "client360_data_sources", ["workspace_id", "source_type"])

    op.create_table(
        "client360_opportunities",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("customer_key", sa.String(length=160), nullable=False, index=True),
        sa.Column("customer_name", sa.String(length=255), nullable=False),
        sa.Column("site_name", sa.String(length=255), nullable=True),
        sa.Column("country", sa.String(length=120), nullable=True, index=True),
        sa.Column("hub", sa.String(length=120), nullable=True, index=True),
        sa.Column("technology", sa.String(length=120), nullable=True, index=True),
        sa.Column("line_label", sa.String(length=255), nullable=True),
        sa.Column("machine_label", sa.String(length=255), nullable=True),
        sa.Column("part_family", sa.String(length=200), nullable=False, index=True),
        sa.Column("part_reference", sa.String(length=160), nullable=True, index=True),
        sa.Column("part_description", sa.Text(), nullable=True),
        sa.Column("installed_quantity", sa.Float(), nullable=True),
        sa.Column("recommended_quantity", sa.Float(), nullable=True),
        sa.Column("periodicity_weeks", sa.Float(), nullable=True),
        sa.Column("delivery_time_weeks", sa.Float(), nullable=True),
        sa.Column("annual_theoretical_qty", sa.Float(), nullable=True),
        sa.Column("potential_theoretical", sa.Float(), nullable=True),
        sa.Column("potential_addressable", sa.Float(), nullable=True),
        sa.Column("potential_unit", sa.String(length=40), nullable=False, server_default="quantity_per_year"),
        sa.Column("currency", sa.String(length=12), nullable=True),
        sa.Column("sales_known_qty", sa.Float(), nullable=True),
        sa.Column("sales_known_value", sa.Float(), nullable=True),
        sa.Column("potential_gap_qty", sa.Float(), nullable=True),
        sa.Column("potential_gap_value", sa.Float(), nullable=True),
        sa.Column("next_due_at", sa.DateTime(), nullable=True, index=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("confidence_label", sa.String(length=24), nullable=False, server_default="low"),
        sa.Column("score_reasons", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("recommended_action", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="detected", index=True),
        sa.Column("data_gaps", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("evidence_refs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("source_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('detected', 'validated', 'draft_generated', 'sent', 'responded', 'quote_requested', 'won', 'lost', 'dismissed')",
            name="ck_client360_opportunities_status",
        ),
    )
    op.create_index("ix_client360_opportunities_workspace_customer", "client360_opportunities", ["workspace_id", "customer_key"])
    op.create_index("ix_client360_opportunities_workspace_status", "client360_opportunities", ["workspace_id", "status"])

    op.create_table(
        "client360_mapping_rules",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("source_part_reference", sa.String(length=160), nullable=True, index=True),
        sa.Column("source_part_label", sa.String(length=255), nullable=True),
        sa.Column("source_part_family", sa.String(length=200), nullable=True, index=True),
        sa.Column("source_system", sa.String(length=80), nullable=False, server_default="sap"),
        sa.Column("technology", sa.String(length=120), nullable=True, index=True),
        sa.Column("pdr_family", sa.String(length=200), nullable=False, index=True),
        sa.Column("normalized_key", sa.String(length=320), nullable=False, index=True),
        sa.Column("recommended_quantity", sa.Float(), nullable=True),
        sa.Column("periodicity_weeks", sa.Float(), nullable=True),
        sa.Column("delivery_time_weeks", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="candidate", index=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.4"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence_refs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('candidate', 'validated', 'rejected', 'needs_review')",
            name="ck_client360_mapping_rules_status",
        ),
    )
    op.create_index("ix_client360_mapping_rules_workspace_key", "client360_mapping_rules", ["workspace_id", "normalized_key"])

    op.create_table(
        "client360_mail_drafts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("opportunity_id", sa.String(length=36), sa.ForeignKey("client360_opportunities.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("action_item_id", sa.String(length=36), sa.ForeignKey("workspace_action_items.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("generated_body", sa.Text(), nullable=False),
        sa.Column("sent_body", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=False, server_default="fr"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft_generated"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("sent_at", sa.DateTime(), nullable=True, index=True),
        sa.CheckConstraint(
            "status IN ('draft_generated', 'edited_by_sales', 'approved', 'sent', 'cancelled')",
            name="ck_client360_mail_drafts_status",
        ),
    )
    op.create_index("ix_client360_mail_drafts_workspace_status", "client360_mail_drafts", ["workspace_id", "status"])

    op.create_table(
        "client360_impact_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("opportunity_id", sa.String(length=36), sa.ForeignKey("client360_opportunities.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("action_item_id", sa.String(length=36), sa.ForeignKey("workspace_action_items.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("mail_draft_id", sa.String(length=36), sa.ForeignKey("client360_mail_drafts.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("impact_type", sa.String(length=32), nullable=False),
        sa.Column("attribution", sa.String(length=24), nullable=False, server_default="unknown"),
        sa.Column("reason", sa.String(length=40), nullable=False, server_default="unknown"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("quote_value", sa.Float(), nullable=True),
        sa.Column("order_value", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(length=12), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), index=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "impact_type IN ('response', 'quote', 'order', 'lost', 'no_response', 'note')",
            name="ck_client360_impact_events_type",
        ),
        sa.CheckConstraint(
            "attribution IN ('direct', 'probable', 'unknown', 'none')",
            name="ck_client360_impact_events_attribution",
        ),
        sa.CheckConstraint(
            "reason IN ('price', 'competitor', 'no_need', 'wrong_contact', 'timing', 'hub', 'technical_mismatch', 'bad_data', 'other', 'unknown')",
            name="ck_client360_impact_events_reason",
        ),
    )
    op.create_index("ix_client360_impact_events_workspace_type", "client360_impact_events", ["workspace_id", "impact_type"])


def _seed_andritz_surface() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if not {"workspaces", "capabilities", "systems"}.issubset(tables):
        return

    workspaces = sa.table(
        "workspaces",
        sa.column("id"),
        sa.column("slug"),
        sa.column("settings", sa.JSON()),
    )
    capabilities = sa.table(
        "capabilities",
        sa.column("id"),
        sa.column("slug"),
        sa.column("name"),
        sa.column("description"),
        sa.column("tier"),
        sa.column("industry"),
        sa.column("input_unit"),
        sa.column("output_unit"),
        sa.column("skill_ids"),
        sa.column("pricing"),
        sa.column("value_per_outcome"),
        sa.column("confidence_threshold"),
        sa.column("sla"),
        sa.column("roi_model"),
        sa.column("is_seeded"),
        sa.column("created_at"),
        sa.column("updated_at"),
    )
    systems = sa.table(
        "systems",
        sa.column("id"),
        sa.column("workspace_id"),
        sa.column("name"),
        sa.column("objective"),
        sa.column("capability_id"),
        sa.column("skill_ids"),
        sa.column("flow_definition"),
        sa.column("settings"),
        sa.column("execution_mode"),
        sa.column("execution_profile"),
        sa.column("coordination_pattern"),
        sa.column("status"),
        sa.column("created_by"),
        sa.column("default_prompt_type"),
        sa.column("retrieval_mode_default"),
        sa.column("created_at"),
        sa.column("updated_at"),
    )

    cap_row = bind.execute(sa.select(capabilities.c.id).where(capabilities.c.slug == CAPABILITY_SLUG)).first()
    cap_id = cap_row._mapping["id"] if cap_row else str(uuid4())
    now = datetime.utcnow()
    if not cap_row:
        bind.execute(
            sa.insert(capabilities).values(
                id=cap_id,
                slug=CAPABILITY_SLUG,
                name="Client360 PDR Opportunity Engine",
                description="Explainable spare-parts commercial potential, mail draft and impact tracking for Andritz Client360 PDR.",
                tier="client",
                industry="industrial_nonwovens",
                input_unit="data_source",
                output_unit="opportunity",
                skill_ids=[],
                pricing={"unit": "per_outcome", "unit_price": 0.0, "currency": "EUR"},
                value_per_outcome=None,
                confidence_threshold=0.55,
                sla={"latency": "interactive", "human_validation_required": True},
                roi_model={},
                is_seeded="Y",
                created_at=now,
                updated_at=now,
            )
        )

    rows = bind.execute(sa.select(workspaces.c.id, workspaces.c.settings).where(workspaces.c.slug == "andritz")).all()
    for row in rows:
        ws = row._mapping
        settings = _as_settings(ws["settings"])
        profile = settings.get("navigation_profile")
        if isinstance(profile, dict) and profile.get("key") == "business_end_user":
            profile = dict(profile)
            profile["default_route"] = profile.get("default_route") or "/chat"
            surfaces = [s for s in profile.get("primary_surfaces", []) if isinstance(s, str)]
            if "client360-pdr" not in surfaces:
                surfaces.insert(1 if "chat" in surfaces else 0, "client360-pdr")
            profile["primary_surfaces"] = surfaces or ["chat", "client360-pdr", "knowledge-capture"]
            profile["advanced_access"] = profile.get("advanced_access") or "admin_only"
            settings["navigation_profile"] = profile
            bind.execute(sa.update(workspaces).where(workspaces.c.id == ws["id"]).values(settings=settings))

        flow = {
            "variant": SYSTEM_VARIANT,
            "schema_version": 1,
            "source": "system_seed",
            "template_id": SYSTEM_VARIANT,
            "template_name": "Client360 PDR",
            "nodes": [
                {"id": "source.data_sources", "type": "source", "label": "SFTP / Knowledge sources"},
                {"id": "task.potential_engine", "type": "task", "label": "Explainable PDR potential"},
                {"id": "task.mail_draft", "type": "task", "label": "Human-validated mail draft"},
                {"id": "sink.impact_tracking", "type": "sink", "label": "Campaign impact loop"},
            ],
            "edges": [
                {"from": "source.data_sources", "to": "task.potential_engine"},
                {"from": "task.potential_engine", "to": "task.mail_draft"},
                {"from": "task.mail_draft", "to": "sink.impact_tracking"},
            ],
            "ui": {"type": "client360_pdr", "entry_route": "client360", "surface_routes": ["/client360"]},
            "runtime_contract": {
                "surface": "/client360",
                "entrypoints": [
                    "GET /api/v1/client360/summary",
                    "GET /api/v1/client360/opportunities",
                    "PATCH /api/v1/client360/opportunities/{id}",
                    "GET /api/v1/client360/mappings",
                    "POST /api/v1/client360/engines/opportunities/run",
                    "POST /api/v1/client360/mail-drafts",
                    "POST /api/v1/client360/actions/{id}/impact",
                ],
                "engines": [
                    "source_discovery",
                    "sap_pdr_mapping",
                    "opportunity_generation",
                    "potential_scoring",
                    "mail_draft_generation",
                    "impact_learning_loop",
                ],
                "prediction_policy": "explainable_potential_only",
                "email_send_policy": "manual_only",
            },
        }
        system_settings = {
            "system_type": "client360_pdr",
            "surface": "client360",
            "surface_routes": ["/client360"],
            "family": "andritz",
            "human_validation_required": True,
            "no_automatic_email_send": True,
            "prediction_policy": "explainable_potential_only",
        }
        existing = bind.execute(
            sa.select(systems.c.id)
            .where(systems.c.workspace_id == ws["id"])
            .where(systems.c.name == SYSTEM_NAME)
        ).first()
        if existing:
            bind.execute(
                sa.update(systems)
                .where(systems.c.id == existing._mapping["id"])
                .values(
                    capability_id=cap_id,
                    flow_definition=flow,
                    settings=system_settings,
                    execution_mode="human_augmented",
                    execution_profile={"surface": "client360", "durability": "database", "email_send": "manual_only"},
                    coordination_pattern="single_agent",
                    status="active",
                    updated_at=now,
                )
            )
            continue
        bind.execute(
            sa.insert(systems).values(
                id=str(uuid4()),
                workspace_id=ws["id"],
                name=SYSTEM_NAME,
                objective="Identify explainable spare-parts commercial potential, prepare human-validated outreach drafts and track impact for Andritz.",
                capability_id=cap_id,
                skill_ids=[],
                flow_definition=flow,
                settings=system_settings,
                execution_mode="human_augmented",
                execution_profile={"surface": "client360", "durability": "database", "email_send": "manual_only"},
                coordination_pattern="single_agent",
                status="active",
                created_by="system:client360_pdr_seed",
                default_prompt_type="factual",
                retrieval_mode_default="auto",
                created_at=now,
                updated_at=now,
            )
        )


def upgrade() -> None:
    _create_tables()
    _seed_andritz_surface()


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "systems" in tables:
        systems = sa.table("systems", sa.column("name"), sa.column("created_by"))
        bind.execute(
            sa.delete(systems).where(
                sa.and_(systems.c.name == SYSTEM_NAME, systems.c.created_by == "system:client360_pdr_seed")
            )
        )
    if "client360_impact_events" in tables:
        op.drop_index("ix_client360_impact_events_workspace_type", table_name="client360_impact_events")
        op.drop_table("client360_impact_events")
    if "client360_mail_drafts" in tables:
        op.drop_index("ix_client360_mail_drafts_workspace_status", table_name="client360_mail_drafts")
        op.drop_table("client360_mail_drafts")
    if "client360_mapping_rules" in tables:
        op.drop_index("ix_client360_mapping_rules_workspace_key", table_name="client360_mapping_rules")
        op.drop_table("client360_mapping_rules")
    if "client360_opportunities" in tables:
        op.drop_index("ix_client360_opportunities_workspace_status", table_name="client360_opportunities")
        op.drop_index("ix_client360_opportunities_workspace_customer", table_name="client360_opportunities")
        op.drop_table("client360_opportunities")
    if "client360_data_sources" in tables:
        op.drop_index("ix_client360_data_sources_workspace_type", table_name="client360_data_sources")
        op.drop_table("client360_data_sources")
