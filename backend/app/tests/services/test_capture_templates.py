"""Focused tests for FSE CaptureTemplate rails (Phase A / C-1)."""
from __future__ import annotations

from app.models.capability import Capability
from app.models.context import Context
from app.models.expert_capture import ExpertCaptureSession, KnowledgeUpdateProposal
from app.models.system import System
from app.models.workspace import Workspace
from app.services.capture_templates import (
    DEFAULT_FSE_INTERVENTION_TYPE,
    FSE_INTERVENTION_TEMPLATE_ID,
    HSE_SAFETY_DEFAULT,
    apply_intervention_type_to_template,
    get_capture_template,
    missing_required_fields,
    plan_seed_to_provided_text,
    publication_defaults_from_template,
    publication_filename_from_header,
    required_field_open_questions,
    site_modification_consistency_question,
    template_id_from_system_settings,
    tracking_metadata_from_header,
)
from app.services.knowledge_capture import (
    create_capture_plan,
    create_update_proposal,
    structure_capture_payload,
)
from app.services.skills_registry.seed import seed_skills_and_capabilities
from app.services.systems.bootstrap import (
    FSE_REPORT_SYSTEM_NAME,
    FSE_REPORT_TEMPLATE_ID,
    ensure_expert_capture_system_default,
    ensure_fse_report_system,
    ensure_fse_report_system_for_andritz,
)


def test_fse_template_resolution_and_plan_seed_shape():
    template = get_capture_template(FSE_INTERVENTION_TEMPLATE_ID)
    assert template is not None
    assert template["id"] == FSE_INTERVENTION_TEMPLATE_ID
    assert template["publication"]["collection"] == "andritz-fse-reports"
    assert template["publication"]["source_type"] == "fse_report"
    assert template["ui"]["lock_plan"] is True
    assert template["ui"]["hide_free_mode"] is True
    # Cartouche + HSE + progress + mods + distribution + optional week/issued_by.
    assert len(template["required_fields"]) == 12
    keys = {field["key"] for field in template["required_fields"]}
    assert {"week", "issued_by", "site_modifications", "distribution"}.issubset(keys)
    assert len(template["intervention_types"]) == 3
    type_ids = {item["id"] for item in template["intervention_types"]}
    assert type_ids == {"weekly_site", "field_service", "process"}
    seed = plan_seed_to_provided_text(template)
    assert "# HSE" in seed
    assert "# Executive Summary" in seed
    assert "# Customer Feedback" in seed


def test_intervention_types_plan_seeds():
    template = get_capture_template(FSE_INTERVENTION_TEMPLATE_ID)
    assert template is not None
    weekly = apply_intervention_type_to_template(template, intervention_type="weekly_site")
    field = apply_intervention_type_to_template(template, intervention_type="field_service")
    process = apply_intervention_type_to_template(template, intervention_type="process")
    weekly_seed = plan_seed_to_provided_text(weekly)
    field_seed = plan_seed_to_provided_text(field)
    process_seed = plan_seed_to_provided_text(process)
    assert "Livraisons matériel" in weekly_seed
    assert "Situation sur site" in field_seed
    assert "## Constat" in field_seed
    assert "Process Schedule" in process_seed
    assert "Tâches semaine suivante" in process_seed
    assert weekly["selected_intervention_type"] == "weekly_site"
    assert field["selected_intervention_type"] == "field_service"


def test_template_id_from_system_settings():
    assert template_id_from_system_settings({"capture": {"template_id": "fse_intervention_v1"}}) == (
        "fse_intervention_v1"
    )
    assert template_id_from_system_settings({}) is None
    assert template_id_from_system_settings(None) is None


def test_missing_required_fields_and_blocking_questions():
    template = get_capture_template(FSE_INTERVENTION_TEMPLATE_ID)
    assert template is not None
    missing = missing_required_fields(template, {"customer": "ACME"})
    keys = {field["key"] for field in missing}
    assert "customer" not in keys
    assert "reference" in keys
    assert "hse_safety" in keys
    assert "site_modifications" in keys
    assert "distribution" in keys
    assert "progress" in keys  # weekly_site default
    questions = required_field_open_questions(template, {"customer": "ACME"})
    assert all(item.get("blocking") for item in questions)
    assert any(item.get("required_field_key") == "reference" for item in questions)


def test_structured_field_validation_equipment_progress_and_site_mods():
    template = get_capture_template(FSE_INTERVENTION_TEMPLATE_ID)
    assert template is not None
    base = {
        "customer": "ACME",
        "country": "FR",
        "site_or_machine": "Line 1",
        "reference": "PO-12",
        "participants": "J. Dupont",
        "intervention_date": "2026-07-14",
        "hse_safety": HSE_SAFETY_DEFAULT,
        "distribution": ["project_manager", "quality"],
        "intervention_type": "weekly_site",
    }
    missing = missing_required_fields(
        template,
        {
            **base,
            "progress": [{"equipment": "Dryer", "percent": ""}],
            "site_modifications": {"selected": ["plc_hmi"], "description": ""},
        },
    )
    keys = {field["key"] for field in missing}
    assert "progress" in keys
    assert "site_modifications" in keys

    complete = missing_required_fields(
        template,
        {
            **base,
            "progress": [
                {
                    "equipment": "Dryer",
                    "percent": 80,
                    "problem_risk": "retard câblage",
                    "measure": "renfort",
                    "responsible": "Automation",
                }
            ],
            "site_modifications": {
                "selected": ["plc_hmi"],
                "description": "Mise à jour programme Jetlace",
            },
        },
    )
    assert complete == []

    field_service_missing = missing_required_fields(
        template,
        {
            **base,
            "intervention_type": "field_service",
            "site_modifications": {"selected": ["none"]},
            # progress optional for field_service
        },
    )
    assert "progress" not in {field["key"] for field in field_service_missing}


def test_hse_default_and_site_mod_consistency_rule():
    assert HSE_SAFETY_DEFAULT.startswith("None")
    question = site_modification_consistency_question(
        {"site_modifications": {"selected": ["none"]}},
        "On a modifié le programme PLC du Jetlace hier soir.",
    )
    assert question is not None
    assert question["source"] == "capture_template_consistency"
    assert question["priority"] >= 0.9
    assert (
        site_modification_consistency_question(
            {
                "site_modifications": {
                    "selected": ["plc_hmi"],
                    "description": "OK",
                }
            },
            "On a modifié le programme PLC du Jetlace hier soir.",
        )
        is None
    )


def test_publication_filename_and_tracking_metadata():
    header = {
        "reference": "SEPTONA",
        "issued_by": "J. Dupont",
        "week": "W28",
        "customer": "Septona",
        "site_or_machine": "Line 1",
        "country": "GR",
        "intervention_date": "2026-07-14",
        "intervention_type": "process",
    }
    assert publication_filename_from_header(header) == "SEPTONA-J.-Dupont-W28.md"
    tracking = tracking_metadata_from_header(header)
    assert tracking["fse_intervention_type"] == "process"
    assert tracking["fse_week"] == "W28"
    assert tracking["fse_reference"] == "SEPTONA"


def test_ensure_fse_report_system_distinct_from_expert_capture(db_session):
    workspace = Workspace(id="ws-fse-seed", name="FSE Seed", slug="fse-seed")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    capture = ensure_expert_capture_system_default(db_session, workspace.id)
    fse = ensure_fse_report_system(db_session, workspace.id)
    again = ensure_fse_report_system(db_session, workspace.id)

    assert capture is not None
    assert fse is not None
    assert fse.id == again.id
    assert fse.id != capture.id
    assert fse.name == FSE_REPORT_SYSTEM_NAME
    assert (fse.settings or {}).get("capture", {}).get("template_id") == FSE_REPORT_TEMPLATE_ID

    # Classic capture seed must not adopt / retire the FSE system.
    adopted = ensure_expert_capture_system_default(db_session, workspace.id)
    assert adopted.id == capture.id
    db_session.refresh(fse)
    assert fse.status == "active"


def test_fse_report_seed_targets_workspace_family_not_slug(db_session):
    branded_alias = Workspace(
        id="ws-fse-andritz-family",
        name="Andritz Field Service",
        slug="andritz-field-service",
        settings={"family": "andritz"},
    )
    unrelated = Workspace(
        id="ws-fse-unrelated",
        name="Unrelated",
        slug="unrelated",
        settings={"family": "standard"},
    )
    db_session.add_all([branded_alias, unrelated])
    seed_skills_and_capabilities(db_session)

    report = ensure_fse_report_system_for_andritz(db_session)

    assert report == {"created": 1, "skipped": 1, "already": 0}
    assert (
        db_session.query(System)
        .filter(
            System.workspace_id == branded_alias.id,
            System.name == FSE_REPORT_SYSTEM_NAME,
        )
        .count()
        == 1
    )
    assert db_session.query(System).filter(System.workspace_id == unrelated.id).count() == 0


def test_fse_report_seed_hydrates_migration_placeholder_graph(db_session):
    workspace = Workspace(
        id="ws-fse-migration-placeholder",
        name="Andritz migration placeholder",
        slug="andritz-migration-placeholder",
        settings={"family": "andritz"},
    )
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)
    capability = (
        db_session.query(Capability)
        .filter(Capability.slug == "expert_knowledge_capture")
        .one()
    )
    placeholder = System(
        workspace_id=workspace.id,
        name=FSE_REPORT_SYSTEM_NAME,
        objective="Migration placeholder",
        capability_id=capability.id,
        skill_ids=[],
        flow_definition={
            "schema_version": 3,
            "variant": "expert_knowledge_capture",
            "source": "migration_060",
            "nodes": [],
            "edges": [],
        },
        settings={"capture": {"template_id": FSE_REPORT_TEMPLATE_ID}},
        status="active",
        created_by="system:fse_report_seed",
    )
    db_session.add(placeholder)
    db_session.commit()

    hydrated = ensure_fse_report_system(db_session, workspace.id)

    assert hydrated is not None
    assert hydrated.id == placeholder.id
    assert hydrated.flow_definition.get("nodes")
    assert hydrated.flow_definition.get("edges")
    assert hydrated.skill_ids


def test_create_capture_plan_applies_template_from_system(db_session):
    workspace = Workspace(id="ws-fse-plan", name="FSE Plan", slug="fse-plan")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)
    fse = ensure_fse_report_system(db_session, workspace.id)
    assert fse is not None

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title=None,
        objective="Intervention pompe P-12",
        expert_profile="Technicien FSE",
        duration_minutes=30,
        context_id=None,
        system_id=fse.id,
        knowledge_refs=[],
        plan_mode="free_conversation",  # must be overridden by template
        header_fields={
            "customer": "Septona",
            "country": "GR",
            "intervention_type": "field_service",
        },
    )

    assert session.plan["mode"] == "provided_plan"
    assert session.metrics["capture_template_id"] == FSE_INTERVENTION_TEMPLATE_ID
    assert session.plan["capture_template"]["id"] == FSE_INTERVENTION_TEMPLATE_ID
    assert session.plan["capture_template"]["intervention_type"] == "field_service"
    assert session.plan["header_fields"]["customer"] == "Septona"
    assert session.plan["header_fields"]["hse_safety"] == HSE_SAFETY_DEFAULT
    assert session.plan["header_fields"]["intervention_type"] == "field_service"
    assert session.plan["topics"]
    assert any("Situation sur site" in str(topic.get("title") or "") for topic in session.plan["topics"])
    gap_slugs = {gap.get("slug") for gap in (session.knowledge_gaps or [])}
    assert "required_field_reference" in gap_slugs
    # progress optional for field_service
    assert "required_field_progress" not in gap_slugs


def test_n1_previous_report_open_items_injected(db_session):
    workspace = Workspace(id="ws-fse-n1", name="FSE N1", slug="fse-n1")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)
    fse = ensure_fse_report_system(db_session, workspace.id)
    assert fse is not None

    prior_session = ExpertCaptureSession(
        id="sess-fse-n1-prior",
        workspace_id=workspace.id,
        system_id=fse.id,
        title="Prior report",
        objective="Prior",
        expert_profile="Expert",
        duration_minutes=20,
        status="completed",
        plan={
            "header_fields": {
                "customer": "Septona",
                "site_or_machine": "Line 1",
                "reference": "PO-99",
            },
            "capture_template": {"id": FSE_INTERVENTION_TEMPLATE_ID},
        },
        metrics={"capture_template_id": FSE_INTERVENTION_TEMPLATE_ID},
    )
    db_session.add(prior_session)
    db_session.flush()
    prior_proposal = KnowledgeUpdateProposal(
        id="prop-fse-n1-prior",
        workspace_id=workspace.id,
        session_id=prior_session.id,
        status="published",
        proposal={
            "open_questions": [
                {
                    "id": "oq-open-cable",
                    "text": "Câble Jetlace toujours manquant ?",
                    "status": "open",
                    "priority": 0.8,
                },
                {
                    "id": "oq-closed",
                    "text": "Already done",
                    "status": "resolved",
                },
            ],
            "publication": {
                "tracking": {
                    "fse_reference": "PO-99",
                    "fse_customer": "Septona",
                    "fse_machine": "Line 1",
                }
            },
        },
    )
    db_session.add(prior_proposal)
    db_session.commit()

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Suivi",
        objective="Reprise",
        expert_profile="Expert",
        duration_minutes=20,
        context_id=None,
        system_id=fse.id,
        knowledge_refs=[],
        header_fields={
            "customer": "Septona",
            "site_or_machine": "Line 1",
            "reference": "PO-99",
            "country": "GR",
        },
    )
    meta = session.plan.get("previous_report_open_items") or {}
    assert meta.get("count") == 1
    assert meta.get("source_proposal_id") == prior_proposal.id
    live = session.plan.get("live_open_questions") or []
    assert any(item.get("source") == "previous_report" for item in live)
    assert any("Câble Jetlace" in str(item.get("text") or "") for item in live)


def test_structure_capture_payload_required_fields_and_publication_defaults(db_session):
    workspace = Workspace(id="ws-fse-finalize", name="FSE Finalize", slug="fse-finalize")
    context = Context(
        id="ctx-fse-finalize",
        workspace_id=workspace.id,
        name="FSE ctx",
        environment_state={"collection": "legacy-capture-knowledge"},
    )
    db_session.add_all([workspace, context])
    seed_skills_and_capabilities(db_session)
    fse = ensure_fse_report_system(db_session, workspace.id)
    assert fse is not None

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Rapport site",
        objective="Intervention",
        expert_profile="Expert",
        duration_minutes=20,
        context_id=context.id,
        system_id=fse.id,
        knowledge_refs=[],
        header_fields={
            "customer": "ACME",
            "reference": "ACME-REF",
            "issued_by": "Marie Curie",
            "week": "W29",
        },
    )
    payload = structure_capture_payload(session)
    assert payload["finalize_checklist"]["required_fields_complete"] is False
    assert payload["finalize_checklist"]["missing_required_fields"]
    assert any(q.get("blocking") for q in payload["open_questions"])
    assert payload["knowledge_sheet_template"] == "fse_intervention_report_v1"
    assert "Cartouche" in payload["report_markdown"]
    assert "ACME" in payload["report_markdown"]
    assert "HSE" in payload["report_markdown"]

    proposal = create_update_proposal(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        complete_session=False,
    )
    publication = proposal.proposal["publication"]
    assert publication["destination"] == "andritz-fse-reports"
    assert publication["source_type"] == "fse_report"
    assert publication["filename"] == "ACME-REF-Marie-Curie-W29.md"
    assert proposal.proposal["recommended_ingestion"]["metadata"]["source_type"] == "fse_report"
    assert proposal.proposal["recommended_ingestion"]["metadata"]["fse_customer"] == "ACME"
    assert proposal.proposal["recommended_ingestion"]["metadata"]["fse_week"] == "W29"
    assert proposal.proposal["recommended_ingestion"]["metadata"]["fse_intervention_type"] == (
        DEFAULT_FSE_INTERVENTION_TYPE
    )


def test_publication_defaults_helper():
    template = get_capture_template(FSE_INTERVENTION_TEMPLATE_ID)
    assert publication_defaults_from_template(template) == {
        "destination": "andritz-fse-reports",
        "destination_scope": "andritz-fse-reports",
        "source_type": "fse_report",
    }


def test_untemplated_capture_unchanged(db_session):
    workspace = Workspace(id="ws-capture-plain", name="Plain Capture", slug="capture-plain")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)
    system = ensure_expert_capture_system_default(db_session, workspace.id)
    assert system is not None
    assert not (system.settings or {}).get("capture", {}).get("template_id")

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Libre",
        objective="Capture libre",
        expert_profile="Expert",
        duration_minutes=20,
        context_id=None,
        system_id=system.id,
        knowledge_refs=[],
        plan_mode="free_conversation",
    )
    assert session.plan["mode"] == "free_conversation"
    assert "capture_template" not in (session.plan or {})
    assert not (session.metrics or {}).get("capture_template_id")
