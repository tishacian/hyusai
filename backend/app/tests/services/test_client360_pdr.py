from __future__ import annotations

from datetime import datetime
from uuid import uuid4

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
    build_customer_timeline,
    build_installed_base_tree,
    calculate_annual_theoretical_qty,
    campaign_stats,
    client360_mail_settings_payload,
    create_campaign,
    create_mail_draft,
    customer_payload,
    generate_campaign_drafts,
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
    assert draft.meta_data["human_validation_required"] is True
    assert action.meta_data["client360"]["generation_mode"] == "ai_assisted"


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
    # No direct price for CustomerB -> family average = 1200 / 8 = 150
    assert other.meta_data["pricing"]["source"] == "family_average"
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
    ):
        assert key in payload
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
