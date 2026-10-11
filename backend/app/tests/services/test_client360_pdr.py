from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

import pytest

from app.models.action_plan import WorkspaceActionItem
from app.models.capability import Capability
from app.models.client360 import (
    Client360Campaign,
    Client360DataSource,
    Client360ImpactEvent,
    Client360MailDraft,
    Client360MappingRule,
    Client360Opportunity,
)
from app.models.knowledge_collection import KnowledgeCollection, KnowledgeCollectionSource
from app.models.rag_preset import RagPreset
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services import client360_pdr as client360_module
from app.services.client360_pdr import (
    _estimate_unit_price,
    _index_purchase_costs,
    _index_purchase_lead_times,
    _index_reference_prices,
    _mapping_key,
    build_customer_timeline,
    build_installed_base_tree,
    calculate_annual_theoretical_qty,
    campaign_stats,
    client360_mail_settings_payload,
    create_campaign,
    create_mail_draft,
    customer_payload,
    generate_campaign_drafts,
    list_opportunities,
    list_customers,
    patch_client360_mail_settings,
    patch_opportunity,
    record_impact,
    run_opportunity_engine,
    send_mail_draft,
    serialize_opportunity,
    summary_payload,
)
from app.services.systems.bootstrap import (
    CLIENT360_PDR_CAPABILITY_SLUG,
    CLIENT360_PDR_SYSTEM_NAME,
    CLIENT360_PDR_VARIANT,
    ensure_client360_pdr_system_default,
)


def _seed_workspace(
    db_session, *, slug: str = "andritz", settings: dict | None = None
) -> Workspace:
    workspace_settings = {"family": "andritz", **(settings or {})}
    workspace = Workspace(
        id=str(uuid4()),
        name=slug.title(),
        slug=slug,
        settings=workspace_settings,
    )
    db_session.add(workspace)
    db_session.flush()
    return workspace


def _seed_user(db_session) -> User:
    user = User(
        id=str(uuid4()),
        username=f"client360-{uuid4().hex[:8]}",
        email=f"client360-{uuid4().hex[:8]}@example.test",
        role="member",
    )
    db_session.add(user)
    db_session.flush()
    return user


def _seed_opportunity(db_session, workspace: Workspace, **overrides) -> Client360Opportunity:
    payload = {
        "id": str(uuid4()),
        "workspace_id": workspace.id,
        "customer_key": "septona",
        "customer_name": "Septona",
        "site_name": "Oinofyta",
        "country": "Greece",
        "hub": "EMEA",
        "technology": "Nonwoven",
        "line_label": "Line 1",
        "machine_label": "Needlepunch",
        "part_family": "wear belts",
        "part_reference": "PDR-001",
        "installed_quantity": 10,
        "recommended_quantity": 2,
        "periodicity_weeks": 4,
        "delivery_time_weeks": 6,
        "sales_known_qty": 8,
        "sales_known_value": 1200,
        "next_due_at": datetime(2026, 8, 15, 9, 0, 0),
        "evidence_refs": [{"kind": "source", "filename": "SEPTONA - Client 360.xlsx"}],
        "source_ids": ["source-1"],
        "status": "detected",
    }
    payload.update(overrides)
    opportunity = Client360Opportunity(**payload)
    db_session.add(opportunity)
    db_session.flush()
    return opportunity


def test_calculates_explainable_pdr_potential_and_gaps(db_session) -> None:
    workspace = _seed_workspace(db_session)
    opportunity = _seed_opportunity(db_session, workspace)

    assert (
        calculate_annual_theoretical_qty(
            installed_quantity=10,
            recommended_quantity=2,
            periodicity_weeks=4,
        )
        == 260
    )

    serialized = serialize_opportunity(opportunity)
    assert serialized["annual_theoretical_qty"] == 260
    assert serialized["potential_theoretical"] == 260
    assert serialized["potential_gap_qty"] == 252
    assert serialized["confidence_label"] == "high"
    assert serialized["confidence_score"] >= 0.78
    assert any(
        reason["code"] == "sap_sales_history" and reason["met"]
        for reason in serialized["score_reasons"]
    )
    assert serialized["recommended_action"] in {
        "prepare_inspection_or_spa",
        "draft_expertise_email",
    }
    assert "periodicity_missing" not in serialized["data_gaps"]

    incomplete = _seed_opportunity(
        db_session,
        workspace,
        customer_key="septona-missing",
        installed_quantity=None,
        recommended_quantity=None,
        periodicity_weeks=None,
        sales_known_qty=None,
        sales_known_value=None,
        evidence_refs=[],
        source_ids=[],
    )
    missing = serialize_opportunity(incomplete)
    assert missing["annual_theoretical_qty"] is None
    assert "installed_quantity_missing" in missing["data_gaps"]
    assert "recommended_quantity_missing" in missing["data_gaps"]
    assert "periodicity_missing" in missing["data_gaps"]
    assert "sap_sales_history_missing" in missing["data_gaps"]


def test_summary_discovers_real_knowledge_sources_and_reports_missing_inputs(db_session) -> None:
    workspace = _seed_workspace(db_session)
    collection = KnowledgeCollection(
        id=str(uuid4()),
        workspace_id=workspace.id,
        slug="andritz-client360-installed-base",
        name="Andritz Client360 Installed Base",
        status="ready",
        document_names=["SEPTONA - Client 360 periodicite.xlsx"],
        vector_collection_name="andritz_client360_installed_base",
        artifact_prefix="knowledge/andritz-client360-installed-base/",
        document_count=1,
        chunk_count=12,
    )
    source = KnowledgeCollectionSource(
        id=str(uuid4()),
        workspace_id=workspace.id,
        collection_id=collection.id,
        filename="SEPTONA - Client 360 periodicite.xlsx",
        normalized_name="septona-client360-periodicite.xlsx",
        source_kind="spreadsheet",
        extension=".xlsx",
        origin="sftp",
        status="ready",
        chunk_count=12,
    )
    db_session.add_all([collection, source])
    db_session.commit()

    payload = summary_payload(db_session, workspace)

    assert payload["source_counts"]["periodicity"] == 1
    assert payload["positioning"]["mvp_contract"]["official_name"] == "Client360 PDR"
    assert "first_replacement_confidence" in payload["positioning"]["mvp_contract"]["mvp_in_scope"]
    assert payload["positioning"]["mail_ai"]["route_id"] == "client360_pdr_mail_writer"
    assert payload["data_sources"][0]["origin"] == "knowledge_collection_source"
    assert payload["data_sources"][0]["collection_slug"] == "andritz-client360-installed-base"
    assert "installed_base_missing" in payload["data_gaps"]
    assert "sap_sales_history_missing" in payload["data_gaps"]


def test_client360_system_seed_is_andritz_scoped_and_idempotent(db_session) -> None:
    workspace = _seed_workspace(
        db_session,
        slug="andritz",
        settings={
            "navigation_profile": {
                "key": "business_end_user",
                "default_route": "/chat",
                "primary_surfaces": ["chat", "knowledge-capture"],
                "advanced_access": "admin_only",
            }
        },
    )

    first = ensure_client360_pdr_system_default(db_session, workspace.id)
    second = ensure_client360_pdr_system_default(db_session, workspace.id)

    assert first is not None
    assert second is not None
    assert first.id == second.id
    assert (
        db_session.query(System)
        .filter(System.workspace_id == workspace.id, System.name == CLIENT360_PDR_SYSTEM_NAME)
        .count()
        == 1
    )
    system = db_session.query(System).filter(System.id == first.id).one()
    assert system.flow_definition["variant"] == CLIENT360_PDR_VARIANT
    assert system.flow_definition["schema_version"] == 2
    assert "product_contract" in system.flow_definition
    assert (
        system.flow_definition["agent_routing"]["mail_draft"]["route_id"]
        == "client360_pdr_mail_writer"
    )
    assert system.settings["surface_routes"] == ["/client360"]
    assert system.settings["product_contract"]["official_name"] == "Client360 PDR"
    assert (
        system.settings["client360_pdr_mail"]["model_resolution"]
        == "agentium_system_capability_workspace"
    )
    assert system.execution_mode == "human_augmented"
    assert "sap_pdr_mapping" in system.flow_definition["runtime_contract"]["engines"]
    assert (
        "POST /api/v1/client360/engines/opportunities/run"
        in system.flow_definition["runtime_contract"]["entrypoints"]
    )
    db_session.refresh(workspace)
    assert workspace.settings["navigation_profile"]["primary_surfaces"] == [
        "chat",
        "client360-pdr",
        "knowledge-capture",
    ]
    capability = db_session.query(Capability).filter(Capability.id == system.capability_id).one()
    assert capability.slug == CLIENT360_PDR_CAPABILITY_SLUG

    other = _seed_workspace(
        db_session,
        slug="other-workspace",
        settings={"family": "generic"},
    )
    assert ensure_client360_pdr_system_default(db_session, other.id) is None


def test_client360_system_seed_uses_family_not_slug(db_session) -> None:
    legacy_slug = _seed_workspace(
        db_session,
        slug="andritz",
        settings={"family": "generic"},
    )
    configured = _seed_workspace(db_session, slug="client360-industrial")

    assert ensure_client360_pdr_system_default(db_session, legacy_slug.id) is None
    assert ensure_client360_pdr_system_default(db_session, configured.id) is not None


def test_mail_draft_creates_human_action_without_auto_send(db_session) -> None:
    workspace = _seed_workspace(db_session, settings={"client360_pdr_mail": {"ai_enabled": False}})
    user = _seed_user(db_session)
    opportunity = _seed_opportunity(db_session, workspace, confidence_label="high")

    draft, action = create_mail_draft(
        db_session,
        workspace,
        user,
        opportunity_id=opportunity.id,
        include_prices=True,
    )
    db_session.commit()

    assert draft.status == "draft_generated"
    assert draft.sent_at is None
    assert "Souhaitez-vous" in draft.generated_body
    assert draft.meta_data["generation_mode"] == "deterministic_template"
    assert action.target_kind == "client360_pdr_opportunity"
    assert action.target_id == opportunity.id
    assert action.meta_data["client360"]["manual_send_only"] is True
    assert opportunity.status == "draft_generated"
    assert db_session.query(Client360MailDraft).count() == 1
    assert db_session.query(WorkspaceActionItem).count() == 1


def test_client360_smtp_settings_are_workspace_scoped_and_mask_secret(db_session) -> None:
    workspace = _seed_workspace(db_session, settings={"client360_pdr_mail": {"ai_enabled": False}})

    payload = patch_client360_mail_settings(
        db_session,
        workspace,
        {
            "enabled": True,
            "host": "ssl0.ovh.net",
            "port": 465,
            "username": "noreply@datategy.net",
            "password": "secret-test",
            "from_email": "noreply@datategy.net",
            "from_name": "ANDRITZ Service",
            "ssl": True,
            "starttls": False,
        },
    )
    db_session.commit()

    assert payload["configured"] is True
    assert payload["password_configured"] is True
    assert "password" not in payload
    masked = client360_mail_settings_payload(workspace)
    assert masked["host"] == "ssl0.ovh.net"
    assert masked["username"] == "noreply@datategy.net"
    assert masked["ssl"] is True
    assert masked["starttls"] is False
    assert "password" not in masked
    smtp = workspace.settings["client360_pdr_mail"]["smtp"]
    assert "password" not in smtp
    assert "password_encrypted" in smtp
    assert "secret-test" not in json.dumps(workspace.settings)


def test_client360_mail_settings_payload_exposes_default_system_prompt(db_session) -> None:
    workspace = _seed_workspace(db_session, settings={"client360_pdr_mail": {"ai_enabled": False}})

    payload = client360_mail_settings_payload(workspace)

    assert payload["system_prompt_source"] == "default"
    assert payload["prompt_version"] == "client360_pdr_mail_v2"
    assert "Retourne strictement un objet JSON" in payload["system_prompt"]
    assert "system_prompt" not in (workspace.settings.get("client360_pdr_mail") or {})


def test_client360_mail_settings_patch_overrides_and_resets_system_prompt(db_session) -> None:
    workspace = _seed_workspace(db_session, settings={"client360_pdr_mail": {"ai_enabled": False}})
    custom = (
        "Tu rediges un mail Client360 de test.\n"
        'Retourne strictement un objet JSON: {"subject": "...", "body": "..."}.'
    )

    overridden = patch_client360_mail_settings(
        db_session,
        workspace,
        {"system_prompt": custom},
    )
    db_session.commit()
    db_session.refresh(workspace)

    assert overridden["system_prompt"] == custom
    assert overridden["system_prompt_source"] == "workspace"
    assert overridden["prompt_version"] == "client360_pdr_mail_v2"
    assert workspace.settings["client360_pdr_mail"]["system_prompt"] == custom

    reset = patch_client360_mail_settings(
        db_session,
        workspace,
        {"reset_system_prompt": True},
    )
    db_session.commit()
    db_session.refresh(workspace)

    assert reset["system_prompt_source"] == "default"
    assert reset["system_prompt"] != custom
    assert "Retourne strictement un objet JSON" in reset["system_prompt"]
    assert "system_prompt" not in workspace.settings["client360_pdr_mail"]


def test_send_mail_draft_uses_workspace_smtp_and_marks_sent(monkeypatch, db_session) -> None:
    workspace = _seed_workspace(
        db_session,
        settings={
            "client360_pdr_mail": {
                "ai_enabled": False,
                "smtp": {
                    "enabled": True,
                    "host": "ssl0.ovh.net",
                    "port": 465,
                    "username": "noreply@datategy.net",
                    "password": "secret-test",
                    "from_email": "noreply@datategy.net",
                    "from_name": "ANDRITZ Service",
                    "ssl": True,
                    "starttls": False,
                },
            }
        },
    )
    user = _seed_user(db_session)
    opportunity = _seed_opportunity(db_session, workspace, confidence_label="high")
    draft, action = create_mail_draft(db_session, workspace, user, opportunity_id=opportunity.id)
    calls: list[dict] = []

    def fake_send_email_with_config(**kwargs):
        calls.append(kwargs)
        return True

    monkeypatch.setattr(client360_module, "send_email_with_config", fake_send_email_with_config)

    sent_draft, sent_action = send_mail_draft(
        db_session,
        workspace,
        user,
        draft_id=draft.id,
        to_email="buyer@example.test",
        subject="Sujet valide",
        body="Bonjour,\n\nMessage valide.",
    )
    db_session.commit()
    db_session.refresh(opportunity)
    db_session.refresh(action)

    assert sent_draft.status == "sent"
    assert sent_draft.sent_body == "Bonjour,\n\nMessage valide."
    assert sent_draft.meta_data["smtp_delivery"]["to_email"] == "buyer@example.test"
    assert sent_action is not None
    assert action.meta_data["client360"]["mail_status"] == "sent"
    assert opportunity.status == "sent"
    assert calls[0]["config"].host == "ssl0.ovh.net"
    assert calls[0]["config"].use_ssl is True
    assert calls[0]["config"].use_starttls is False
    assert calls[0]["to"] == "buyer@example.test"


def test_mail_draft_uses_ai_generation_when_available(monkeypatch, db_session) -> None:
    workspace = _seed_workspace(
        db_session,
        settings={
            "client360_pdr_mail": {
                "ai_enabled": True,
                "provider": "openai",
                "model": "test-mail-model",
            }
        },
    )
    user = _seed_user(db_session)
    opportunity = _seed_opportunity(db_session, workspace, confidence_label="high")
    monkeypatch.setattr(client360_module.settings, "openai_api_key", "test-key")

    async def fake_complete(**kwargs):
        assert kwargs["provider"] == "openai"
        assert kwargs["model"] == "test-mail-model"
        assert kwargs["system_prompt"] == client360_module._CLIENT360_MAIL_SYSTEM_PROMPT
        assert "Septona" in kwargs["user_prompt"]
        assert "wear belts" in kwargs["user_prompt"]
        return '{"subject":"Plan maintenance PDR - Septona","body":"Bonjour,\\n\\nNous avons identifie une action preventive sur les wear belts.\\n\\nCordialement,"}'

    monkeypatch.setattr(client360_module, "_complete_client360_mail_ai", fake_complete)

    draft, action = create_mail_draft(db_session, workspace, user, opportunity_id=opportunity.id)
    db_session.commit()

    assert draft.subject == "Plan maintenance PDR - Septona"
    assert "action preventive" in draft.generated_body
    assert draft.meta_data["generation_mode"] == "ai_assisted"
    assert draft.meta_data["llm_model"] == "test-mail-model"
    assert draft.meta_data["prompt_version"] == "client360_pdr_mail_v2"
    assert draft.meta_data["system_prompt_source"] == "default"
    assert draft.meta_data["human_validation_required"] is True
    assert action.meta_data["client360"]["generation_mode"] == "ai_assisted"


def test_mail_draft_ai_uses_workspace_system_prompt_override(monkeypatch, db_session) -> None:
    custom_prompt = (
        "PROMPT OVERRIDE CLIENT360.\n"
        'Retourne strictement un objet JSON: {"subject": "...", "body": "..."}.'
    )
    workspace = _seed_workspace(
        db_session,
        settings={
            "client360_pdr_mail": {
                "ai_enabled": True,
                "provider": "openai",
                "model": "test-mail-model",
                "system_prompt": custom_prompt,
            }
        },
    )
    user = _seed_user(db_session)
    opportunity = _seed_opportunity(db_session, workspace, confidence_label="high")
    monkeypatch.setattr(client360_module.settings, "openai_api_key", "test-key")
    seen: dict[str, str] = {}

    async def fake_complete(**kwargs):
        seen["system_prompt"] = kwargs["system_prompt"]
        seen["prompt_hash"] = client360_module._prompt_hash(
            kwargs["system_prompt"], kwargs["user_prompt"]
        )
        return '{"subject":"Override subject","body":"Corps override."}'

    monkeypatch.setattr(client360_module, "_complete_client360_mail_ai", fake_complete)

    draft, _action = create_mail_draft(db_session, workspace, user, opportunity_id=opportunity.id)
    db_session.commit()

    assert seen["system_prompt"] == custom_prompt
    assert draft.meta_data["system_prompt_source"] == "workspace"
    assert draft.meta_data["prompt_hash"] == seen["prompt_hash"]
    assert draft.meta_data["prompt_hash"] != client360_module._prompt_hash(
        client360_module._CLIENT360_MAIL_SYSTEM_PROMPT,
        client360_module._mail_user_prompt(
            client360_module._mail_prompt_payload(opportunity, include_prices=False)
        ),
    )


def test_mail_draft_resolves_agentium_system_preset_model(monkeypatch, db_session) -> None:
    workspace = _seed_workspace(db_session, settings={"client360_pdr_mail": {"ai_enabled": True}})
    capability = Capability(
        slug=CLIENT360_PDR_CAPABILITY_SLUG,
        name="Client360 PDR Opportunity Engine",
        description="Client360 test capability",
    )
    db_session.add(capability)
    db_session.flush()
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name=CLIENT360_PDR_SYSTEM_NAME,
        objective="Client360 PDR",
        capability_id=capability.id,
        flow_definition={"variant": CLIENT360_PDR_VARIANT},
        settings={"system_type": CLIENT360_PDR_VARIANT},
        status="active",
    )
    db_session.add(system)
    db_session.flush()
    db_session.add(
        RagPreset(
            id=str(uuid4()),
            name="Client360 system preset",
            scope="system",
            scope_id=system.id,
            workspace_id=workspace.id,
            config={"defaultProvider": "openai", "defaultModel": "test-agentium-system-model"},
            is_default=True,
        )
    )
    user = _seed_user(db_session)
    opportunity = _seed_opportunity(db_session, workspace, confidence_label="high")
    user_id = user.id
    opportunity_id = opportunity.id
    db_session.commit()
    monkeypatch.setattr(client360_module.settings, "openai_api_key", "test-key")

    async def fake_complete(**kwargs):
        assert kwargs["provider"] == "openai"
        assert kwargs["model"] == "test-agentium-system-model"
        return '{"subject":"Rappel maintenance Septona","body":"Bonjour,\\n\\nProposition preventive via Agentium.\\n\\nCordialement,"}'

    monkeypatch.setattr(client360_module, "_complete_client360_mail_ai", fake_complete)

    draft, action = create_mail_draft(
        db_session,
        workspace,
        db_session.get(User, user_id),
        opportunity_id=opportunity_id,
    )
    db_session.commit()

    assert draft.meta_data["generation_mode"] == "ai_assisted"
    assert draft.meta_data["llm_model"] == "test-agentium-system-model"
    assert draft.meta_data["llm_model_source"] == "agentium.resolved.defaultModel"
    assert draft.meta_data["llm_routing_source"] == "agentium_system"
    assert draft.meta_data["agent_route"] == "client360_pdr_mail_writer"
    assert action.meta_data["client360"]["llm_provider"] == "openai"


def test_impact_tracking_updates_opportunity_and_action_status(db_session) -> None:
    workspace = _seed_workspace(db_session, settings={"client360_pdr_mail": {"ai_enabled": False}})
    user = _seed_user(db_session)
    opportunity = _seed_opportunity(db_session, workspace, confidence_label="medium")
    draft, action = create_mail_draft(db_session, workspace, user, opportunity_id=opportunity.id)

    event = record_impact(
        db_session,
        workspace,
        user,
        action.id,
        impact_type="order",
        attribution="direct",
        reason="timing",
        summary="Commande recue apres relance Client360 PDR.",
        mail_draft_id=draft.id,
        order_value=3200,
        currency="EUR",
    )
    db_session.commit()
    db_session.refresh(opportunity)
    db_session.refresh(action)

    assert event.impact_type == "order"
    assert event.attribution == "direct"
    assert event.reason == "timing"
    assert event.order_value == 3200
    assert opportunity.status == "won"
    assert action.status == "completed"
    assert db_session.query(Client360ImpactEvent).count() == 1


def test_opportunity_validation_loop_records_rejection_reason(db_session) -> None:
    workspace = _seed_workspace(db_session)
    opportunity = _seed_opportunity(db_session, workspace)

    patched = patch_opportunity(
        db_session,
        workspace,
        opportunity.id,
        {"status": "dismissed", "rejection_reason": "wrong_contact", "notes": "Contact obsolete"},
    )
    db_session.commit()

    assert patched.status == "dismissed"
    assert patched.meta_data["learning_loop"]["rejection_reason"] == "wrong_contact"
    assert patched.meta_data["learning_loop"]["notes"] == "Contact obsolete"


def test_opportunity_engine_builds_prioritized_gap_from_mapped_real_records(db_session) -> None:
    workspace = _seed_workspace(db_session)
    db_session.add_all(
        [
            Client360DataSource(
                id=str(uuid4()),
                workspace_id=workspace.id,
                source_type="installed_base",
                label="Installed base pilot",
                status="ready",
                meta_data={
                    "records": [
                        {
                            "customer_name": "Septona",
                            "country": "Greece",
                            "hub": "EMEA",
                            "technology": "JETLACE",
                            "line_label": "Line 1",
                            "part_reference": "BELT-1",
                            "part_family": "wear belts",
                            "installed_quantity": 10,
                        }
                    ]
                },
            ),
            Client360DataSource(
                id=str(uuid4()),
                workspace_id=workspace.id,
                source_type="periodicity",
                label="Wear part periodicity",
                status="ready",
                meta_data={
                    "records": [
                        {
                            "technology": "JETLACE",
                            "part_reference": "BELT-1",
                            "part_family": "wear belts",
                            "recommended_quantity": 2,
                            "periodicity_weeks": 4,
                            "delivery_time_weeks": 6,
                        }
                    ]
                },
            ),
            Client360DataSource(
                id=str(uuid4()),
                workspace_id=workspace.id,
                source_type="sap_sales_history",
                label="SAP pilot sales",
                status="ready",
                meta_data={
                    "records": [
                        {
                            "customer_name": "Septona",
                            "technology": "JETLACE",
                            "part_reference": "BELT-1",
                            "part_family": "wear belts",
                            "sales_known_qty": 8,
                            "sales_known_value": 1200,
                            "currency": "EUR",
                        }
                    ]
                },
            ),
        ]
    )
    db_session.commit()

    result = run_opportunity_engine(db_session, workspace)
    db_session.commit()

    assert result["records_seen"] == 3
    assert result["candidate_mappings_created"] == 1
    assert result["created"] == 1
    opportunity = db_session.query(Client360Opportunity).one()
    assert opportunity.customer_name == "Septona"
    assert opportunity.technology == "JETLACE"
    assert opportunity.annual_theoretical_qty == 260
    assert opportunity.potential_gap_qty == 252
    assert opportunity.sales_known_qty == 8
    assert opportunity.confidence_label == "high"
    assert opportunity.recommended_action in {"prepare_inspection_or_spa", "draft_expertise_email"}
    mapping = db_session.query(Client360MappingRule).one()
    assert mapping.status == "candidate"
    assert mapping.pdr_family == "wear belts"


def test_run_engine_purges_obsolete_customer_keys(db_session) -> None:
    workspace = _seed_workspace(db_session)
    _seed_opportunity(
        db_session,
        workspace,
        customer_key="septona s a",
        customer_name="Septona S.A.",
        part_family="injector strip",
        part_reference="OLD-1",
    )
    _seed_valuation_sources(db_session, workspace)
    db_session.commit()

    result = run_opportunity_engine(db_session, workspace)
    db_session.commit()

    assert result["purged_obsolete_customer_keys"] >= 1
    rows = db_session.query(Client360Opportunity).all()
    assert rows
    assert all(row.customer_key == "septona" for row in rows)


def test_canonicalize_source_record_keeps_forecast_anchor_fields() -> None:
    from app.services.client360_pdr import _canonicalize_source_record

    sales = _canonicalize_source_record(
        {
            "customer_name": "Septona S.A.",
            "part_reference": "208177476",
            "sales_known_qty": 1.0,
            "sales_known_value": 1768.23,
            "last_document_date": "2024-04-03 00:00:00",
            "last_purchase_date": "2024-04-03 00:00:00",
            "role": "sales_orders",
        },
        source_type="sap_sales_history",
        evidence_refs=[],
        source_id="src-1",
    )
    # Anchors used by compute_next_due must survive canonicalization.
    assert sales["last_purchase_date"] == "2024-04-03 00:00:00"
    assert sales["last_document_date"] == "2024-04-03 00:00:00"
    assert sales["customer_key"] == "septona"

    machine = _canonicalize_source_record(
        {
            "customer_name": "Septona S.A.",
            "machine_label": "HFR200",
            "construction_year": "2018",
        },
        source_type="installed_base",
        evidence_refs=[],
        source_id="src-2",
    )
    assert machine["construction_year"] == "2018"


def test_opportunity_engine_computes_next_due_from_va05_material_sales(db_session) -> None:
    """Septona-like case: family record with periodicity + VA05 customer×Material
    sales carrying a last purchase date → deterministic next_due_at."""
    workspace = _seed_workspace(db_session)
    db_session.add_all(
        [
            Client360DataSource(
                id=str(uuid4()),
                workspace_id=workspace.id,
                source_type="installed_base",
                label="SEPTONA - Client 360.xlsx",
                status="ready",
                meta_data={
                    "records": [
                        {
                            "customer_name": "Septona S.A.",
                            "customer_key": "septona s a",
                            "country": "Greece",
                            "hub": "EMEA",
                            "technology": "JETLACE HFR200",
                            "part_family": "Injector Strip",
                            "source_part_family": "Injector Strip",
                            "source_part_label": "202507741 STRIP 3600-3600-3890-2J14 MM",
                            "installed_quantity": 28.0,
                            "recommended_quantity": 1.0,
                            "periodicity_weeks": 6.0,
                        }
                    ]
                },
            ),
            Client360DataSource(
                id=str(uuid4()),
                workspace_id=workspace.id,
                source_type="sap_sales_history",
                label="Liste Sales Orders D800 MNT SPL 2011_2026 VA05.xlsx",
                status="ready",
                meta_data={
                    "role": "sales_orders",
                    "records": [
                        {
                            "customer_name": "Septona S.A.",
                            "customer_key": "septona s a",
                            "part_reference": "202507741",
                            "sales_known_qty": 3.0,
                            "sales_known_value": 2517.6,
                            "currency": "EUR",
                            "last_document_date": "2024-04-03 00:00:00",
                            "last_purchase_date": "2024-04-03 00:00:00",
                            "role": "sales_orders",
                        }
                    ],
                },
            ),
        ]
    )
    db_session.commit()

    run_opportunity_engine(db_session, workspace)
    db_session.commit()

    opportunity = next(
        row
        for row in db_session.query(Client360Opportunity).all()
        if row.part_family == "Injector Strip"
    )
    # Shared normalization folds "Septona S.A." to the registry key.
    assert opportunity.customer_key == "septona"
    assert opportunity.next_due_at is not None
    assert opportunity.next_due_at >= datetime(2024, 4, 3)
    forecast = opportunity.meta_data["forecast"]
    assert forecast["anchor_source"] == "last_purchase"
    assert forecast["anchor_date"].startswith("2024-04-03")


def test_directory_unifies_registry_and_engine_customer_keys(db_session) -> None:
    """Registry 'Septona (Alpha Leasing)' and SAP 'Septona S.A.' must land in one
    directory bucket (projects + opportunities), even with persisted old-style keys."""
    workspace = _seed_workspace(db_session)
    db_session.add_all(
        [
            Client360DataSource(
                id=str(uuid4()),
                workspace_id=workspace.id,
                source_type="contact_hub",
                label="Liste Projets _ Clients.xlsx",
                status="ready",
                meta_data={
                    "role": "project_registry",
                    "records": [
                        {
                            "project_code": "SEP100",
                            "customer_name": "Septona (Alpha Leasing)",
                            # Old-style persisted key (pre-shared-normalization).
                            "customer_key": "septona alpha leasing",
                            "sap_reference": "4500777",
                            "country": "Greece",
                            "role": "project_registry",
                        }
                    ],
                },
            ),
            Client360DataSource(
                id=str(uuid4()),
                workspace_id=workspace.id,
                source_type="installed_base",
                label="SEPTONA - Client 360.xlsx",
                status="ready",
                meta_data={
                    "records": [
                        {
                            "customer_name": "Septona S.A.",
                            "customer_key": "septona s a",
                            "country": "Greece",
                            "technology": "JETLACE HFR200",
                            "part_family": "Injector Strip",
                            "installed_quantity": 28.0,
                            "recommended_quantity": 1.0,
                            "periodicity_weeks": 6.0,
                        }
                    ]
                },
            ),
        ]
    )
    db_session.commit()

    run_opportunity_engine(db_session, workspace)
    db_session.commit()

    directory = list_customers(db_session, workspace)
    septona_items = [
        item for item in directory["items"] if item["customer_key"] == "septona"
    ]
    assert len(septona_items) == 1
    assert septona_items[0]["project_count"] >= 1
    assert septona_items[0]["opportunity_count"] >= 1


def test_serialize_opportunity_values_gap_in_euros_from_direct_price(db_session) -> None:
    workspace = _seed_workspace(db_session)
    opportunity = _seed_opportunity(db_session, workspace)

    serialized = serialize_opportunity(opportunity)

    assert serialized["potential_gap_qty"] == 252
    # unit price = sales_known_value / sales_known_qty = 1200 / 8 = 150
    assert serialized["potential_gap_value"] == 37800.0


def test_serialize_opportunity_gap_value_none_without_price(db_session) -> None:
    workspace = _seed_workspace(db_session)
    opportunity = _seed_opportunity(
        db_session,
        workspace,
        customer_key="septona-noprice",
        sales_known_value=None,
    )

    serialized = serialize_opportunity(opportunity)

    assert serialized["potential_gap_qty"] == 252
    assert serialized["potential_gap_value"] is None


def _seed_valuation_sources(db_session, workspace) -> None:
    db_session.add_all(
        [
            Client360DataSource(
                id=str(uuid4()),
                workspace_id=workspace.id,
                source_type="installed_base",
                label="Installed base pilot",
                status="ready",
                meta_data={
                    "records": [
                        {
                            "customer_name": "Septona",
                            "country": "Greece",
                            "hub": "EMEA",
                            "technology": "JETLACE",
                            "line_label": "Line 1",
                            "part_reference": "BELT-1",
                            "part_family": "wear belts",
                            "installed_quantity": 10,
                        }
                    ]
                },
            ),
            Client360DataSource(
                id=str(uuid4()),
                workspace_id=workspace.id,
                source_type="periodicity",
                label="Wear part periodicity",
                status="ready",
                meta_data={
                    "records": [
                        {
                            "technology": "JETLACE",
                            "part_reference": "BELT-1",
                            "part_family": "wear belts",
                            "recommended_quantity": 2,
                            "periodicity_weeks": 4,
                            "delivery_time_weeks": 6,
                        }
                    ]
                },
            ),
            Client360DataSource(
                id=str(uuid4()),
                workspace_id=workspace.id,
                source_type="sap_sales_history",
                label="SAP pilot sales",
                status="ready",
                meta_data={
                    "records": [
                        {
                            "customer_name": "Septona",
                            "technology": "JETLACE",
                            "part_reference": "BELT-1",
                            "part_family": "wear belts",
                            "sales_known_qty": 8,
                            "sales_known_value": 1200,
                            "currency": "EUR",
                        }
                    ]
                },
            ),
        ]
    )
    db_session.commit()


def test_opportunity_engine_values_gap_and_weights_addressable(db_session) -> None:
    workspace = _seed_workspace(db_session)
    _seed_valuation_sources(db_session, workspace)

    run_opportunity_engine(db_session, workspace)
    db_session.commit()

    opportunity = db_session.query(Client360Opportunity).one()
    assert opportunity.potential_gap_qty == 252
    assert opportunity.potential_gap_value == 37800.0
    # base 0.4 + hub 0.2 + purchase history 0.25 + conversion 0.15 * 0 = 0.85
    assert opportunity.potential_addressable == 214.2
    pricing = opportunity.meta_data["pricing"]
    assert pricing["source"] == "direct"
    assert pricing["unit_price"] == 150.0
    factors = opportunity.meta_data["addressable_factors"]
    assert factors["factor"] == 0.85
    assert factors["hub_present"] is True
    assert factors["existing_purchase_history"] is True
    assert factors["observed_conversion_rate"] == 0.0


def test_addressable_weights_are_configurable(db_session) -> None:
    workspace = _seed_workspace(
        db_session,
        settings={
            "client360_pdr_scope": {
                "addressable_weights": {
                    "base": 1.0,
                    "hub_present": 0.0,
                    "existing_purchase_history": 0.0,
                    "observed_conversion": 0.0,
                }
            }
        },
    )
    _seed_valuation_sources(db_session, workspace)

    run_opportunity_engine(db_session, workspace)
    db_session.commit()

    opportunity = db_session.query(Client360Opportunity).one()
    assert opportunity.meta_data["addressable_factors"]["factor"] == 1.0
    assert opportunity.potential_addressable == opportunity.potential_gap_qty


def test_estimate_unit_price_falls_back_to_purchase_cost_average() -> None:
    purchase_records = [
        {
            "part_reference": "BELT-9",
            "part_family": "wear belts",
            "unit_cost": 80.0,
            "role": "purchase_history",
        },
        {
            "part_reference": "BELT-9",
            "part_family": "wear belts",
            "unit_cost": 120.0,
            "role": "purchase_history",
        },
    ]
    pricing_index = {
        "family": {},
        "family_technology": {},
        "purchase_cost": _index_purchase_costs(purchase_records),
    }
    price, meta = _estimate_unit_price(
        {
            "part_reference": "BELT-9",
            "part_family": "wear belts",
            "currency": "EUR",
        },
        pricing_index,
    )
    assert price == 100.0
    assert meta["source"] == "purchase_cost_average"


def test_estimate_unit_price_prefers_installed_base_purchase_price() -> None:
    price, meta = _estimate_unit_price(
        {
            "source_type": "installed_base",
            "part_family": "o-rings",
            "purchase_unit_price": 0.74,
            "sales_known_qty": 12,
            "sales_known_value": 399.1,
            "currency": "EUR",
        },
        {
            "family": {"o rings": {"value": 399.1, "qty": 12.0}},
            "family_technology": {},
            "purchase_cost": {},
        },
    )
    assert price == pytest.approx(0.74)
    assert meta["source"] == "installed_base_purchase_price"


def test_estimate_unit_price_skips_direct_when_sample_too_small() -> None:
    price, meta = _estimate_unit_price(
        {
            "part_family": "wear belts",
            "sales_known_qty": 4.0,
            "sales_known_value": 200.0,
            "currency": "EUR",
        },
        {
            "family": {"wear belts": {"value": 1000.0, "qty": 10.0}},
            "family_technology": {},
            "purchase_cost": {},
        },
    )
    assert price == pytest.approx(100.0)
    assert meta["source"] == "family_average"


def test_index_reference_prices_by_ref_and_family_park_mix() -> None:
    """Explicit VA05 "Net Price" indexed per reference, then per family
    weighted by the installed park mix (the Septona O'ring case)."""
    records = [
        # VA05 customer × material aggregates with explicit listed prices.
        {
            "part_reference": "131978144",
            "sales_unit_price": 0.74,
            "sales_known_qty": 4.0,
            "role": "sales_orders",
        },
        {
            "part_reference": "132081816",
            "sales_unit_price": 381.81,
            "sales_known_qty": 8.0,
            "role": "sales_orders",
        },
        # Installed base park: mostly cheap O-rings, a few premium seals.
        {"part_reference": "131978144", "installed_quantity": 480.0, "role": "spc"},
        {"part_reference": "132081816", "installed_quantity": 10.0, "role": "spc"},
    ]
    material_families = {
        "131978144": {"O'ring Dia 47.22 X 3.53"},
        "132081816": {"O'ring Dia 47.22 X 3.53"},
    }
    index = _index_reference_prices(records, material_families)

    o_ring = index["by_ref"]["131978144"]
    assert o_ring["value"] / o_ring["qty"] == pytest.approx(0.74)

    family_bucket = index["by_family"][_mapping_key("O'ring Dia 47.22 X 3.53")]
    park_mix = family_bucket["value"] / family_bucket["qty"]
    # (0.74 × 480 + 381.81 × 10) / 490 ≈ 8.52 € — not 399.10 €.
    assert park_mix == pytest.approx((0.74 * 480 + 381.81 * 10) / 490.0)


def test_estimate_unit_price_prefers_explicit_reference_price() -> None:
    price, meta = _estimate_unit_price(
        {
            "part_reference": "131978144",
            "part_family": "O'ring Dia 47.22 X 3.53",
            "sales_known_qty": 4.0,
            "sales_known_value": 1596.4,
            "currency": "EUR",
        },
        {
            "family": {},
            "family_technology": {},
            "purchase_cost": {},
            "reference_sales": {
                "by_ref": {"131978144": {"value": 0.74 * 4, "qty": 4.0}},
                "by_family": {},
            },
        },
    )
    assert price == pytest.approx(0.74)
    assert meta["source"] == "reference_sales_price"


def test_estimate_unit_price_family_park_mix_for_family_level_record() -> None:
    """A family-level pilot record (no part_reference) is valued at the park
    mix of its member references' explicit prices, not at the tiny direct
    sample (4 pcs of a premium seal → 399.10 €)."""
    family = "O'ring Dia 47.22 X 3.53"
    price, meta = _estimate_unit_price(
        {
            "part_family": family,
            "sales_known_qty": 4.0,
            "sales_known_value": 1596.4,
            "currency": "EUR",
        },
        {
            "family": {_mapping_key(family): {"value": 1596.4, "qty": 4.0}},
            "family_technology": {},
            "purchase_cost": {},
            "reference_sales": {
                "by_ref": {},
                "by_family": {_mapping_key(family): {"value": 4173.3, "qty": 490.0}},
            },
        },
    )
    assert price == pytest.approx(4173.3 / 490.0, abs=1e-3)
    assert meta["source"] == "family_installed_mix_price"


def test_index_purchase_lead_times_median_by_part_reference() -> None:
    index = _index_purchase_lead_times(
        [
            {
                "part_reference": "MAT-1",
                "unit_cost": 10,
                "delivery_time_weeks": 4,
                "role": "purchase_history",
            },
            {
                "part_reference": "MAT-1",
                "unit_cost": 10,
                "delivery_time_weeks": 8,
                "role": "purchase_history",
            },
            {
                "part_reference": "MAT-1",
                "unit_cost": 10,
                "delivery_time_weeks": 6,
                "role": "purchase_history",
            },
        ]
    )
    assert index["mat 1"] == 6.0


def test_opportunity_engine_uses_purchase_cost_and_lead_time(db_session) -> None:
    workspace = _seed_workspace(db_session)
    db_session.add_all(
        [
            Client360DataSource(
                id=str(uuid4()),
                workspace_id=workspace.id,
                source_type="installed_base",
                label="Installed base pilot",
                status="ready",
                meta_data={
                    "records": [
                        {
                            "customer_name": "Septona",
                            "country": "Greece",
                            "hub": "EMEA",
                            "technology": "JETLACE",
                            "part_reference": "BELT-PH",
                            "part_family": "wear belts",
                            "installed_quantity": 10,
                        }
                    ]
                },
            ),
            Client360DataSource(
                id=str(uuid4()),
                workspace_id=workspace.id,
                source_type="periodicity",
                label="Wear part periodicity",
                status="ready",
                meta_data={
                    "records": [
                        {
                            "technology": "JETLACE",
                            "part_family": "wear belts",
                            "recommended_quantity": 2,
                            "periodicity_weeks": 4,
                        }
                    ]
                },
            ),
            Client360DataSource(
                id=str(uuid4()),
                workspace_id=workspace.id,
                source_type="other",
                label="Histo_Achat_Pieces_Machines_Montbonnot.xlsx",
                status="ready",
                meta_data={
                    "role": "purchase_history",
                    "aggregation": "by_material",
                    "records": [
                        {
                            "part_reference": "BELT-PH",
                            "part_description": "Wear belt",
                            "unit_cost": 50.0,
                            "currency": "EUR",
                            "delivery_time_weeks": 7,
                            "role": "purchase_history",
                        }
                    ],
                },
            ),
        ]
    )
    db_session.commit()

    result = run_opportunity_engine(db_session, workspace)
    db_session.commit()

    opportunity = db_session.query(Client360Opportunity).one()
    assert opportunity.meta_data["pricing"]["source"] == "purchase_cost_average"
    assert opportunity.meta_data["pricing"]["unit_price"] == 50.0
    assert opportunity.delivery_time_weeks == 7
    # annual = 10 * 2 * 52 / 4 = 260 ; no sales → gap uses sales_qty None → gap_qty None
    # Actually looking at code: gap_qty requires sales_qty is not None
    # So gap_value may be None. Pricing source is what we care about.


def test_opportunity_engine_deduplicates_same_role_and_basename_sources(db_session) -> None:
    workspace = _seed_workspace(db_session)
    db_session.add_all(
        [
            Client360DataSource(
                id=str(uuid4()),
                workspace_id=workspace.id,
                source_type="installed_base",
                filename="Installed_base_SPL/Installed base - SPC.xlsx",
                label="SPC",
                status="ready",
                meta_data={
                    "role": "spc",
                    "records": [
                        {
                            "customer_name": "Septona",
                            "country": "GR",
                            "part_reference": "OR-1",
                            "part_family": "wear belts",
                            "installed_quantity": 10,
                        }
                    ],
                },
            ),
            Client360DataSource(
                id=str(uuid4()),
                workspace_id=workspace.id,
                source_type="periodicity",
                filename="Installed_base_SPL/Family - Opportunity.xlsx",
                label="Family",
                status="ready",
                meta_data={
                    "records": [
                        {
                                "part_family": "wear belts",
                            "recommended_quantity": 1,
                            "periodicity_weeks": 4,
                        }
                    ]
                },
            ),
            Client360DataSource(
                id=str(uuid4()),
                workspace_id=workspace.id,
                source_type="sap_sales_history",
                filename="Installed_base_SPL/Liste Sales Orders D800 MNT SPL 2011_2026 VA05.xlsx",
                label="sales old",
                status="ready",
                updated_at=datetime(2026, 1, 1, 9, 0, 0),
                meta_data={
                    "role": "sales_orders",
                    "records": [
                        {
                            "customer_name": "Septona",
                            "part_reference": "OR-1",
                                "part_family": "wear belts",
                            "sales_known_qty": 4.0,
                            "sales_known_value": 400.0,
                            "currency": "EUR",
                        }
                    ],
                },
            ),
            Client360DataSource(
                id=str(uuid4()),
                workspace_id=workspace.id,
                source_type="sap_sales_history",
                filename="Installed_base_SPL__Liste Sales Orders D800 MNT SPL 2011_2026 VA05.xlsx",
                label="sales new",
                status="ready",
                updated_at=datetime(2026, 2, 1, 9, 0, 0),
                meta_data={
                    "role": "sales_orders",
                    "records": [
                        {
                            "customer_name": "Septona",
                            "part_reference": "OR-1",
                                "part_family": "wear belts",
                            "sales_known_qty": 1.0,
                            "sales_known_value": 100.0,
                            "currency": "EUR",
                        }
                    ],
                },
            ),
        ]
    )
    db_session.commit()

    run_opportunity_engine(db_session, workspace)
    db_session.commit()

    opp = (
        db_session.query(Client360Opportunity)
        .filter(
            Client360Opportunity.customer_key == "septona",
            Client360Opportunity.part_reference == "OR-1",
        )
        .one()
    )
    assert opp.sales_known_qty == pytest.approx(1.0)
    assert opp.potential_gap_qty == pytest.approx(129.0)


def test_opportunity_engine_falls_back_to_family_average_price(db_session) -> None:
    workspace = _seed_workspace(db_session)
    db_session.add_all(
        [
            Client360DataSource(
                id=str(uuid4()),
                workspace_id=workspace.id,
                source_type="installed_base",
                label="Installed base pilot",
                status="ready",
                meta_data={
                    "records": [
                        {
                            "customer_name": "Septona",
                            "country": "Greece",
                            "hub": "EMEA",
                            "technology": "JETLACE",
                            "part_reference": "BELT-1",
                            "part_family": "wear belts",
                            "installed_quantity": 10,
                        },
                        {
                            "customer_name": "CustomerB",
                            "country": "Greece",
                            "hub": "EMEA",
                            "technology": "JETLACE",
                            "part_reference": "BELT-2",
                            "part_family": "wear belts",
                            "installed_quantity": 5,
                        },
                    ]
                },
            ),
            Client360DataSource(
                id=str(uuid4()),
                workspace_id=workspace.id,
                source_type="periodicity",
                label="Wear part periodicity",
                status="ready",
                meta_data={
                    "records": [
                        {
                            "technology": "JETLACE",
                            "part_family": "wear belts",
                            "recommended_quantity": 2,
                            "periodicity_weeks": 4,
                            "delivery_time_weeks": 6,
                        }
                    ]
                },
            ),
            Client360DataSource(
                id=str(uuid4()),
                workspace_id=workspace.id,
                source_type="sap_sales_history",
                label="SAP pilot sales",
                status="ready",
                meta_data={
                    "records": [
                        {
                            "customer_name": "Septona",
                            "technology": "JETLACE",
                            "part_reference": "BELT-1",
                            "part_family": "wear belts",
                            "sales_known_qty": 8,
                            "sales_known_value": 1200,
                            "currency": "EUR",
                        },
                        {
                            "customer_name": "CustomerB",
                            "technology": "JETLACE",
                            "part_reference": "BELT-2",
                            "part_family": "wear belts",
                            "sales_known_qty": 4,
                        },
                    ]
                },
            ),
        ]
    )
    db_session.commit()

    run_opportunity_engine(db_session, workspace)
    db_session.commit()

    other = (
        db_session.query(Client360Opportunity)
        .filter(Client360Opportunity.customer_key == "customerb")
        .one()
    )
    # No direct price for CustomerB -> fallback to pooled family+technology price.
    assert other.meta_data["pricing"]["source"] == "family_technology_average"
    assert other.meta_data["pricing"]["unit_price"] == 150.0
    # annual = 5 * 2 * 52 / 4 = 130 ; gap = 130 - 4 = 126 ; value = 126 * 150
    assert other.potential_gap_qty == 126
    assert other.potential_gap_value == 18900.0


def test_opportunity_engine_dry_run_does_not_persist(db_session) -> None:
    workspace = _seed_workspace(db_session)
    db_session.add(
        Client360DataSource(
            id=str(uuid4()),
            workspace_id=workspace.id,
            source_type="installed_base",
            label="Installed base pilot",
            status="ready",
            meta_data={
                "records": [
                    {
                        "customer_name": "Septona",
                        "country": "Greece",
                        "technology": "JETLACE",
                        "part_family": "wear belts",
                        "installed_quantity": 1,
                    }
                ]
            },
        )
    )
    db_session.commit()

    result = run_opportunity_engine(db_session, workspace, dry_run=True)

    assert result["dry_run"] is True
    assert result["created"] == 0
    assert db_session.query(Client360Opportunity).count() == 0
    assert db_session.query(Client360MappingRule).count() == 0


def _seed_campaign_opportunity(
    db_session, workspace, *, customer_key, email="buyer@example.test", **overrides
):
    meta_data = {"contact": {"email": email}} if email else {}
    return _seed_opportunity(
        db_session,
        workspace,
        customer_key=customer_key,
        customer_name=customer_key.title(),
        confidence_label="high",
        meta_data=meta_data,
        **overrides,
    )


def test_create_campaign_persists_selection_filters(db_session) -> None:
    workspace = _seed_workspace(db_session)
    user = _seed_user(db_session)

    campaign = create_campaign(
        db_session,
        workspace,
        user,
        name="Premier remplacement JETLACE",
        campaign_type="first_replacement",
        selection_criteria={"technology": "JETLACE", "confidence": "high", "unknown": "drop"},
        description="Cible haute confiance",
    )
    db_session.commit()

    assert campaign.status == "draft"
    assert campaign.campaign_type == "first_replacement"
    assert campaign.selection_criteria == {"technology": "JETLACE", "confidence": "high"}
    assert campaign.targeted_count == 0
    assert campaign.created_by_user_id == user.id


def test_create_campaign_rejects_invalid_type(db_session) -> None:
    workspace = _seed_workspace(db_session)
    user = _seed_user(db_session)

    try:
        create_campaign(db_session, workspace, user, name="X", campaign_type="not_a_type")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_generate_campaign_drafts_dedups_missing_email(db_session) -> None:
    workspace = _seed_workspace(db_session, settings={"client360_pdr_mail": {"ai_enabled": False}})
    user = _seed_user(db_session)
    _seed_campaign_opportunity(db_session, workspace, customer_key="withemail")
    _seed_campaign_opportunity(db_session, workspace, customer_key="noemail", email=None)

    campaign = create_campaign(db_session, workspace, user, name="Batch", campaign_type="free")
    result = generate_campaign_drafts(db_session, workspace, user, campaign.id)
    db_session.commit()

    assert result["created"] == 1
    assert result["skipped"].get("missing_contact_email") == 1
    draft = (
        db_session.query(Client360MailDraft)
        .filter(Client360MailDraft.campaign_id == campaign.id)
        .one()
    )
    assert draft.status == "draft_generated"
    assert draft.meta_data["campaign_id"] == campaign.id
    db_session.refresh(campaign)
    assert campaign.status == "active"
    assert campaign.drafts_count == 1
    assert campaign.targeted_count == 2


def test_generate_campaign_drafts_dedups_active_campaign(db_session) -> None:
    workspace = _seed_workspace(db_session, settings={"client360_pdr_mail": {"ai_enabled": False}})
    user = _seed_user(db_session)
    _seed_campaign_opportunity(db_session, workspace, customer_key="shared")

    first = create_campaign(db_session, workspace, user, name="First", campaign_type="free")
    generate_campaign_drafts(db_session, workspace, user, first.id)
    db_session.commit()

    second = create_campaign(db_session, workspace, user, name="Second", campaign_type="renewal")
    result = generate_campaign_drafts(db_session, workspace, user, second.id)
    db_session.commit()

    assert result["created"] == 0
    assert result["skipped"].get("active_campaign_conflict") == 1
    assert (
        db_session.query(Client360MailDraft)
        .filter(Client360MailDraft.campaign_id == second.id)
        .count()
        == 0
    )


def test_create_campaign_persists_customer_keys_targeting(db_session) -> None:
    workspace = _seed_workspace(db_session)
    user = _seed_user(db_session)

    campaign = create_campaign(
        db_session,
        workspace,
        user,
        name="Selection annuaire",
        campaign_type="renewal",
        selection_criteria={
            "customer_keys": ["Septona", "septona", " Mogul ", ""],
            "due_within_weeks": "12",
            "unknown": "drop",
        },
    )
    db_session.commit()

    # Duplicate keys (same normalized customer) and empty entries are dropped.
    assert campaign.selection_criteria == {
        "customer_keys": ["Septona", "Mogul"],
        "due_within_weeks": 12,
    }


def test_generate_campaign_drafts_targets_explicit_customer_selection(db_session) -> None:
    workspace = _seed_workspace(db_session, settings={"client360_pdr_mail": {"ai_enabled": False}})
    user = _seed_user(db_session)
    _seed_campaign_opportunity(db_session, workspace, customer_key="alpha")
    _seed_campaign_opportunity(db_session, workspace, customer_key="beta", email=None)
    _seed_campaign_opportunity(db_session, workspace, customer_key="gamma")

    campaign = create_campaign(
        db_session,
        workspace,
        user,
        name="Annuaire",
        campaign_type="free",
        selection_criteria={"customer_keys": ["Alpha", "beta"]},
    )
    result = generate_campaign_drafts(db_session, workspace, user, campaign.id)
    db_session.commit()

    # gamma stays out of the selection; beta is selected but lacks a contact email.
    assert result["created"] == 1
    assert result["skipped"].get("missing_contact_email") == 1
    drafts = (
        db_session.query(Client360MailDraft)
        .filter(Client360MailDraft.campaign_id == campaign.id)
        .all()
    )
    drafted_customers = {
        db_session.query(Client360Opportunity)
        .filter(Client360Opportunity.id == draft.opportunity_id)
        .one()
        .customer_key
        for draft in drafts
    }
    assert drafted_customers == {"alpha"}
    db_session.refresh(campaign)
    assert campaign.targeted_count == 2


def test_generate_campaign_drafts_customer_selection_keeps_active_campaign_dedup(
    db_session,
) -> None:
    workspace = _seed_workspace(db_session, settings={"client360_pdr_mail": {"ai_enabled": False}})
    user = _seed_user(db_session)
    _seed_campaign_opportunity(db_session, workspace, customer_key="shared")

    first = create_campaign(db_session, workspace, user, name="First", campaign_type="free")
    generate_campaign_drafts(db_session, workspace, user, first.id)
    db_session.commit()

    second = create_campaign(
        db_session,
        workspace,
        user,
        name="Second",
        campaign_type="renewal",
        selection_criteria={"customer_keys": ["shared"]},
    )
    result = generate_campaign_drafts(db_session, workspace, user, second.id)
    db_session.commit()

    assert result["created"] == 0
    assert result["skipped"].get("active_campaign_conflict") == 1


def test_generate_campaign_drafts_due_within_weeks_targets_due_soon_only(db_session) -> None:
    workspace = _seed_workspace(db_session, settings={"client360_pdr_mail": {"ai_enabled": False}})
    user = _seed_user(db_session)
    now = datetime(2026, 7, 1, 9, 0, 0)
    _seed_campaign_opportunity(
        db_session, workspace, customer_key="duesoon", next_due_at=datetime(2026, 8, 1, 9, 0, 0)
    )
    _seed_campaign_opportunity(
        db_session, workspace, customer_key="duelater", next_due_at=datetime(2027, 7, 1, 9, 0, 0)
    )

    campaign = create_campaign(
        db_session,
        workspace,
        user,
        name="Echeances",
        campaign_type="renewal",
        selection_criteria={"customer_keys": ["duesoon", "duelater"], "due_within_weeks": 8},
    )
    result = generate_campaign_drafts(db_session, workspace, user, campaign.id, now=now)
    db_session.commit()

    assert result["created"] == 1
    draft = (
        db_session.query(Client360MailDraft)
        .filter(Client360MailDraft.campaign_id == campaign.id)
        .one()
    )
    opportunity = (
        db_session.query(Client360Opportunity)
        .filter(Client360Opportunity.id == draft.opportunity_id)
        .one()
    )
    assert opportunity.customer_key == "duesoon"
    db_session.refresh(campaign)
    assert campaign.targeted_count == 1


def test_campaign_stats_scopes_potential_to_customer_selection(db_session) -> None:
    workspace = _seed_workspace(db_session, settings={"client360_pdr_mail": {"ai_enabled": False}})
    user = _seed_user(db_session)
    _seed_campaign_opportunity(db_session, workspace, customer_key="alpha")
    _seed_campaign_opportunity(db_session, workspace, customer_key="gamma")

    campaign = create_campaign(
        db_session,
        workspace,
        user,
        name="Cible",
        campaign_type="free",
        selection_criteria={"customer_keys": ["alpha"]},
    )
    db_session.commit()

    stats = campaign_stats(db_session, workspace, campaign.id)["stats"]
    assert stats["targeted_customers"] == 1
    assert stats["targeted_opportunities"] == 1


def test_campaign_stats_reports_transformation_and_potential(db_session) -> None:
    workspace = _seed_workspace(db_session, settings={"client360_pdr_mail": {"ai_enabled": False}})
    user = _seed_user(db_session)
    opportunity = _seed_campaign_opportunity(db_session, workspace, customer_key="septona")

    campaign = create_campaign(
        db_session, workspace, user, name="Transfo", campaign_type="first_replacement"
    )
    generate_campaign_drafts(db_session, workspace, user, campaign.id)
    db_session.commit()

    draft = (
        db_session.query(Client360MailDraft)
        .filter(Client360MailDraft.campaign_id == campaign.id)
        .one()
    )
    draft.status = "sent"
    draft.sent_at = datetime(2026, 7, 1, 9, 0, 0)
    db_session.flush()

    record_impact(
        db_session,
        workspace,
        user,
        draft.action_item_id,
        impact_type="order",
        attribution="direct",
        reason="timing",
        mail_draft_id=draft.id,
        order_value=5000,
        currency="EUR",
    )
    db_session.commit()

    stats = campaign_stats(db_session, workspace, campaign.id)["stats"]
    assert stats["drafts"] == 1
    assert stats["sent"] == 1
    assert stats["orders"] == 1
    assert stats["won_value"] == 5000.0
    assert stats["responses"] == 0
    # potential CA reuses potential_gap_value (gap 252 * unit price 150 = 37800)
    assert stats["potential_gap_value"] == 37800.0
    assert stats["targeted_customers"] == 1
    # Observed impacts (1 order / 1 signal) → conversion_proxy 1.0
    assert stats["conversion_proxy"] == 1.0
    assert stats["conversion_proxy_source"] == "observed_impacts"
    assert stats["expected_value"] == 37800.0
    assert "estimation deterministe" in stats["expected_value_disclaimer"]
    # impact event is linked to the campaign through the draft.
    event = db_session.query(Client360Campaign).filter(Client360Campaign.id == campaign.id).one()
    assert event.drafts_count == 1


def _seed_draft(db_session, workspace, opportunity, **overrides) -> Client360MailDraft:
    payload = {
        "id": str(uuid4()),
        "workspace_id": workspace.id,
        "opportunity_id": opportunity.id,
        "subject": "Sujet PDR",
        "generated_body": "Bonjour,\n\nContenu.",
        "status": "draft_generated",
    }
    payload.update(overrides)
    row = Client360MailDraft(**payload)
    db_session.add(row)
    db_session.flush()
    return row


def _seed_impact(db_session, workspace, opportunity, **overrides) -> Client360ImpactEvent:
    payload = {
        "id": str(uuid4()),
        "workspace_id": workspace.id,
        "opportunity_id": opportunity.id,
        "impact_type": "order",
        "attribution": "direct",
        "reason": "timing",
        "summary": "Commande recue.",
    }
    payload.update(overrides)
    row = Client360ImpactEvent(**payload)
    db_session.add(row)
    db_session.flush()
    return row


def test_installed_base_tree_aggregates_by_tech_line_machine() -> None:
    opportunities = [
        {
            "id": "o1",
            "technology": "JETLACE",
            "line_label": "Line 1",
            "machine_label": "Needlepunch",
            "part_family": "wear belts",
            "part_reference": "BELT-1",
            "potential_gap_qty": 252,
            "potential_gap_value": 37800.0,
        },
        {
            "id": "o2",
            "technology": "JETLACE",
            "line_label": "Line 1",
            "machine_label": "Calender",
            "part_family": "rolls",
            "part_reference": "ROLL-1",
            "potential_gap_qty": 100,
            "potential_gap_value": 5000.0,
        },
        {
            "id": "o3",
            "technology": "HFR200",
            "line_label": None,
            "machine_label": None,
            "part_family": "seals",
            "potential_gap_qty": 10,
            "potential_gap_value": 900.0,
        },
    ]

    tree = build_installed_base_tree(opportunities)

    # Ordered by descending potential gap value: JETLACE (42800) before HFR200 (900).
    assert [node["technology"] for node in tree] == ["JETLACE", "HFR200"]
    jetlace = tree[0]
    assert jetlace["opportunity_count"] == 2
    assert jetlace["potential_gap_value"] == 42800.0
    assert len(jetlace["lines"]) == 1
    line = jetlace["lines"][0]
    assert line["line_label"] == "Line 1"
    machines = {m["machine_label"]: m for m in line["machines"]}
    assert set(machines) == {"Needlepunch", "Calender"}
    assert machines["Needlepunch"]["parts"][0]["part_reference"] == "BELT-1"
    # Missing line/machine labels collapse into a single placeholder node.
    hfr = tree[1]
    assert hfr["lines"][0]["line_label"] == "Non renseigne"
    assert hfr["lines"][0]["machines"][0]["machine_label"] == "Non renseigne"


def test_customer_timeline_merges_and_sorts_desc() -> None:
    opportunities = [
        {
            "id": "o1",
            "part_family": "wear belts",
            "status": "detected",
            "updated_at": "2026-02-10T09:00:00",
            "created_at": "2026-01-01T09:00:00",
        },
    ]
    drafts = [
        {
            "id": "d1",
            "opportunity_id": "o1",
            "subject": "Brouillon",
            "created_at": "2026-01-15T09:00:00",
            "sent_at": None,
        },
        {
            "id": "d2",
            "opportunity_id": "o1",
            "subject": "Envoye",
            "created_at": "2026-01-20T09:00:00",
            "sent_at": "2026-03-01T09:00:00",
        },
    ]
    impacts = [
        {
            "id": "i1",
            "opportunity_id": "o1",
            "impact_type": "order",
            "summary": "Commande",
            "occurred_at": "2026-02-01T09:00:00",
        },
    ]

    timeline = build_customer_timeline(opportunities, drafts, impacts)

    ats = [event["at"] for event in timeline]
    assert ats == sorted(ats, reverse=True)
    kinds = [event["kind"] for event in timeline]
    assert kinds[0] == "mail_sent"  # 2026-03-01 is the most recent
    assert "mail_draft" in kinds
    assert "impact_order" in kinds
    assert "opportunity_update" in kinds


def test_customer_payload_enriches_summary_tree_and_timeline(db_session) -> None:
    workspace = _seed_workspace(db_session, settings={"client360_pdr_mail": {"ai_enabled": False}})
    opportunity = _seed_opportunity(
        db_session,
        workspace,
        technology="JETLACE",
        line_label="Line 1",
        machine_label="Needlepunch",
    )
    _seed_draft(db_session, workspace, opportunity, created_at=datetime(2026, 1, 15, 9, 0, 0))
    _seed_impact(db_session, workspace, opportunity, occurred_at=datetime(2026, 2, 1, 9, 0, 0))
    db_session.commit()

    payload = customer_payload(db_session, workspace, "septona")

    # New keys are additive; legacy keys remain present.
    for key in (
        "customer",
        "opportunities",
        "mail_drafts",
        "impact_events",
        "market_signals",
        "data_gaps",
        "projects",
        "machines",
        "purchases",
        "next_due",
    ):
        assert key in payload
    assert isinstance(payload["next_due"], list)
    # Seeded opportunity carries next_due_at; forecast module surfaces it when present.
    assert any(item.get("part_reference") == "PDR-001" for item in payload["next_due"])
    assert payload["installed_base"][0]["technology"] == "JETLACE"
    assert {event["kind"] for event in payload["timeline"]} >= {"mail_draft", "impact_order"}

    summary = payload["ai_summary"]
    assert summary["generation_mode"] == "deterministic_template"
    assert summary["provider"] is None
    assert summary["model"] is None
    assert summary["route_id"] == "client360_pdr_customer_summary"
    assert summary["fallback_reason"] == "ai_disabled"
    assert "Septona" in summary["text"]
    # gap 252 * unit price 150 = 37800 is surfaced in the deterministic summary.
    assert "37800" in summary["text"]


def test_customer_payload_skips_ai_summary_on_demand(db_session) -> None:
    workspace = _seed_workspace(db_session, settings={"client360_pdr_mail": {"ai_enabled": False}})
    _seed_opportunity(db_session, workspace)
    db_session.commit()

    payload = customer_payload(db_session, workspace, "septona", include_ai_summary=False)

    assert payload["ai_summary"] is None
    # The rest of the fiche stays fully populated on the fast path.
    assert payload["customer"]["name"]
    assert payload["opportunities"]


def test_customer_payload_summary_uses_llm_when_configured(monkeypatch, db_session) -> None:
    workspace = _seed_workspace(
        db_session,
        settings={
            "client360_pdr_mail": {
                "ai_enabled": True,
                "provider": "openai",
                "model": "test-summary-model",
            }
        },
    )
    _seed_opportunity(db_session, workspace)
    db_session.commit()
    monkeypatch.setattr(client360_module.settings, "openai_api_key", "test-key")

    async def fake_complete(**kwargs):
        assert kwargs["provider"] == "openai"
        assert kwargs["model"] == "test-summary-model"
        assert "Septona" in kwargs["user_prompt"]
        return '{"summary":"Septona presente un potentiel PDR eleve.","highlights":["Confiance haute"]}'

    monkeypatch.setattr(client360_module, "_complete_client360_summary_ai", fake_complete)

    payload = customer_payload(db_session, workspace, "septona")
    summary = payload["ai_summary"]

    assert summary["generation_mode"] == "ai_assisted"
    assert summary["model"] == "test-summary-model"
    assert summary["route_id"] == "client360_pdr_customer_summary"
    assert summary["prompt_version"] == "client360_pdr_customer_summary_v1"
    assert summary["highlights"] == ["Confiance haute"]


def _seed_client360_source(db_session, workspace: Workspace, *, source_type: str, role: str, records: list[dict]) -> Client360DataSource:
    row = Client360DataSource(
        id=str(uuid4()),
        workspace_id=workspace.id,
        source_type=source_type,
        label=f"{role} fixture",
        status="ready",
        meta_data={"role": role, "records": records},
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_list_customers_merges_registry_and_opportunities_sorted_by_potential(db_session) -> None:
    workspace = _seed_workspace(db_session)
    _seed_client360_source(
        db_session,
        workspace,
        source_type="contact_hub",
        role="project_registry",
        records=[
            {
                "project_code": "SEP100",
                "customer_name": "Septona",
                "customer_key": "septona",
                "sap_reference": "SAP-SEP",
                "country": "Greece",
                "role": "project_registry",
            },
            {
                "project_code": "MOG100",
                "customer_name": "Mogul",
                "customer_key": "mogul",
                "sap_reference": "SAP-MOG",
                "country": "Turkey",
                "role": "project_registry",
            },
        ],
    )
    _seed_opportunity(
        db_session,
        workspace,
        customer_key="septona",
        customer_name="Septona",
        country="Greece",
        technology="JETLACE",
        potential_gap_value=50000,
        potential_gap_qty=100,
    )
    _seed_opportunity(
        db_session,
        workspace,
        customer_key="mogul",
        customer_name="Mogul",
        country="Turkey",
        technology="HFR200",
        potential_gap_value=12000,
        potential_gap_qty=40,
        part_reference="PDR-MOG",
    )
    db_session.commit()

    payload = list_customers(db_session, workspace)

    assert payload["total"] == 2
    assert [item["customer_key"] for item in payload["items"]] == ["septona", "mogul"]
    septona = payload["items"][0]
    assert septona["project_count"] == 1
    assert septona["projects"][0]["project_code"] == "SEP100"
    assert septona["opportunity_count"] == 1
    assert septona["potential_gap_value"] == 50000
    assert "Greece" in payload["facets"]["countries"]
    assert "JETLACE" in payload["facets"]["technologies"]

    filtered = list_customers(db_session, workspace, country="Turkey")
    assert filtered["total"] == 1
    assert filtered["items"][0]["customer_key"] == "mogul"

    searched = list_customers(db_session, workspace, q="sep")
    assert searched["total"] == 1
    assert searched["items"][0]["customer_name"] == "Septona"


def test_list_opportunities_country_filter_matches_iso_aliases(db_session) -> None:
    workspace = _seed_workspace(db_session)
    _seed_opportunity(
        db_session,
        workspace,
        customer_key="sep-gr",
        customer_name="Septona GR",
        country="GR",
        part_reference="PDR-GR",
    )
    _seed_opportunity(
        db_session,
        workspace,
        customer_key="sep-greece",
        customer_name="Septona Greece",
        country="Greece",
        part_reference="PDR-GR2",
    )
    db_session.commit()

    by_name = list_opportunities(db_session, workspace, country="Greece", limit=50)
    by_code = list_opportunities(db_session, workspace, country="GR", limit=50)

    assert len(by_name) == 2
    assert len(by_code) == 2


def test_customer_payload_enriches_projects_machines_purchases_and_next_due(
    monkeypatch, db_session
) -> None:
    workspace = _seed_workspace(db_session, settings={"client360_pdr_mail": {"ai_enabled": False}})
    _seed_client360_source(
        db_session,
        workspace,
        source_type="contact_hub",
        role="project_registry",
        records=[
            {
                "project_code": "SEP100",
                "customer_name": "Septona",
                "customer_key": "septona",
                "sap_reference": "SAP-SEP",
                "country": "Greece",
                "role": "project_registry",
            }
        ],
    )
    _seed_client360_source(
        db_session,
        workspace,
        source_type="installed_base",
        role="machine",
        records=[
            {
                "customer_name": "Septona",
                "customer_key": "septona",
                "machine_label": "Jetlace A",
                "technology": "JETLACE",
                "line_label": "Line 1",
                "project_code": "SEP100",
                "construction_year": "2018",
                "country": "Greece",
                "role": "machine",
            }
        ],
    )
    _seed_client360_source(
        db_session,
        workspace,
        source_type="sap_sales_history",
        role="sales_orders",
        records=[
            {
                "customer_name": "Septona",
                "customer_key": "septona",
                "part_reference": "BELT-1",
                "part_description": "Wear belt",
                "sales_known_qty": 12,
                "sales_known_value": 1800,
                "currency": "EUR",
                "last_document_date": "2025-11-01",
                "order_line_count": 3,
                "role": "sales_orders",
            }
        ],
    )
    _seed_client360_source(
        db_session,
        workspace,
        source_type="other",
        role="purchase_history",
        records=[
            {
                "part_reference": "BELT-1",
                "unit_cost": 140,
                "delivery_time_weeks": 8,
                "po_count": 2,
                "currency": "EUR",
                "role": "purchase_history",
            }
        ],
    )
    _seed_opportunity(
        db_session,
        workspace,
        technology="JETLACE",
        line_label="Line 1",
        machine_label="Needlepunch",
        part_reference="BELT-1",
    )
    db_session.commit()

    import sys
    import types

    fake_forecast = types.ModuleType("app.services.client360_forecast")

    def customer_next_due(db, workspace, *, customer_key=None, customer_name=None):
        return [
            {
                "part_reference": "BELT-1",
                "next_due_at": "2026-09-01T00:00:00",
                "customer_key": customer_key,
                "customer_name": customer_name,
            }
        ]

    fake_forecast.customer_next_due = customer_next_due
    monkeypatch.setitem(sys.modules, "app.services.client360_forecast", fake_forecast)

    payload = customer_payload(db_session, workspace, "septona")

    assert payload["projects"][0]["project_code"] == "SEP100"
    assert payload["projects"][0]["sap_reference"] == "SAP-SEP"
    assert payload["machines"][0]["machine_label"] == "Jetlace A"
    assert payload["purchases"][0]["part_reference"] == "BELT-1"
    assert payload["purchases"][0]["sales_known_qty"] == 12
    assert payload["purchases"][0]["unit_cost"] == 140
    assert payload["purchases"][0]["delivery_time_weeks"] == 8
    assert payload["purchases"][0]["po_count"] == 2
    assert payload["next_due"][0]["part_reference"] == "BELT-1"
    assert "Greece" in payload["customer"]["countries"]
    assert "JETLACE" in payload["customer"]["technologies"]


def test_customer_payload_next_due_empty_without_forecast_module(
    monkeypatch, db_session
) -> None:
    workspace = _seed_workspace(db_session, settings={"client360_pdr_mail": {"ai_enabled": False}})
    _seed_opportunity(db_session, workspace, next_due_at=None)
    db_session.commit()

    import builtins

    real_import = builtins.__import__

    def _block_forecast(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "app.services.client360_forecast" or (
            name == "app.services" and fromlist and "client360_forecast" in fromlist
        ):
            raise ImportError("forecast deferred")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _block_forecast)

    payload = customer_payload(db_session, workspace, "septona")
    assert payload["next_due"] == []
    assert payload["projects"] == []
    assert payload["machines"] == []
    assert payload["purchases"] == []
