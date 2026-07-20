"""Focused tests for FSE CaptureTemplate rails (Phase A / C-2)."""
from __future__ import annotations

from app.models.context import Context
from app.models.system import System
from app.models.workspace import Workspace
from app.services.capture_templates import (
    FSE_INTERVENTION_TEMPLATE_ID,
    get_capture_template,
    missing_required_fields,
    plan_seed_to_provided_text,
    publication_defaults_from_template,
    required_field_open_questions,
    template_id_from_system_settings,
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
    assert len(template["required_fields"]) == 7
    seed = plan_seed_to_provided_text(template)
    assert "# Contexte et objet" in seed
    assert "## Constat" in seed
    assert "## Échéance" in seed


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
    questions = required_field_open_questions(template, {"customer": "ACME"})
    assert all(item.get("blocking") for item in questions)
    assert any(item.get("required_field_key") == "reference" for item in questions)


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
        header_fields={"customer": "Septona", "country": "GR"},
    )

    assert session.plan["mode"] == "provided_plan"
    assert session.metrics["capture_template_id"] == FSE_INTERVENTION_TEMPLATE_ID
    assert session.plan["capture_template"]["id"] == FSE_INTERVENTION_TEMPLATE_ID
    assert session.plan["header_fields"]["customer"] == "Septona"
    assert session.plan["topics"]
    assert any("Contexte" in str(topic.get("title") or "") for topic in session.plan["topics"])
    gap_slugs = {gap.get("slug") for gap in (session.knowledge_gaps or [])}
    assert "required_field_reference" in gap_slugs


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
        header_fields={"customer": "ACME"},
    )
    payload = structure_capture_payload(session)
    assert payload["finalize_checklist"]["required_fields_complete"] is False
    assert payload["finalize_checklist"]["missing_required_fields"]
    assert any(q.get("blocking") for q in payload["open_questions"])
    assert payload["knowledge_sheet_template"] == "fse_intervention_report_v1"
    assert "En-tête" in payload["report_markdown"]
    assert "ACME" in payload["report_markdown"]

    proposal = create_update_proposal(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        complete_session=False,
    )
    publication = proposal.proposal["publication"]
    assert publication["destination"] == "andritz-fse-reports"
    assert publication["source_type"] == "fse_report"
    assert proposal.proposal["recommended_ingestion"]["metadata"]["source_type"] == "fse_report"
    assert proposal.proposal["recommended_ingestion"]["metadata"]["fse_customer"] == "ACME"


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
