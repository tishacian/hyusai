from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from app.models.action_plan import WorkspaceActionItem
from app.models.capability import Capability
from app.models.client360 import (
    Client360DataSource,
    Client360ImpactEvent,
    Client360MappingRule,
    Client360MailDraft,
    Client360Opportunity,
)
from app.models.knowledge_collection import KnowledgeCollection, KnowledgeCollectionSource
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services import client360_pdr as client360_module
from app.services.client360_pdr import (
    calculate_annual_theoretical_qty,
    create_mail_draft,
    patch_opportunity,
    record_impact,
    run_opportunity_engine,
    serialize_opportunity,
    summary_payload,
)
from app.services.systems.bootstrap import (
    CLIENT360_PDR_CAPABILITY_SLUG,
    CLIENT360_PDR_SYSTEM_NAME,
    CLIENT360_PDR_VARIANT,
    ensure_client360_pdr_system_default,
)


def _seed_workspace(db_session, *, slug: str = "andritz", settings: dict | None = None) -> Workspace:
    workspace = Workspace(id=str(uuid4()), name=slug.title(), slug=slug, settings=settings or {})
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
    assert any(reason["code"] == "sap_sales_history" and reason["met"] for reason in serialized["score_reasons"])
    assert serialized["recommended_action"] in {"prepare_inspection_or_spa", "draft_expertise_email"}
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
        slug="andritz-client360-pilot",
        name="Andritz Client360 Pilot",
        status="ready",
        document_names=["SEPTONA - Client 360 periodicite.xlsx"],
        vector_collection_name="andritz_client360_pilot",
        artifact_prefix="knowledge/andritz-client360-pilot/",
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
    assert payload["data_sources"][0]["origin"] == "knowledge_collection_source"
    assert payload["data_sources"][0]["collection_slug"] == "andritz-client360-pilot"
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
    assert system.settings["surface_routes"] == ["/client360"]
    assert system.execution_mode == "human_augmented"
    assert "sap_pdr_mapping" in system.flow_definition["runtime_contract"]["engines"]
    assert "POST /api/v1/client360/engines/opportunities/run" in system.flow_definition["runtime_contract"]["entrypoints"]
    db_session.refresh(workspace)
    assert workspace.settings["navigation_profile"]["primary_surfaces"] == [
        "chat",
        "client360-pdr",
        "knowledge-capture",
    ]
    capability = db_session.query(Capability).filter(Capability.id == system.capability_id).one()
    assert capability.slug == CLIENT360_PDR_CAPABILITY_SLUG

    other = _seed_workspace(db_session, slug="other-workspace")
    assert ensure_client360_pdr_system_default(db_session, other.id) is None


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


def test_mail_draft_uses_ai_generation_when_available(monkeypatch, db_session) -> None:
    workspace = _seed_workspace(
        db_session,
        settings={"client360_pdr_mail": {"ai_enabled": True, "provider": "openai", "model": "test-mail-model"}},
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
