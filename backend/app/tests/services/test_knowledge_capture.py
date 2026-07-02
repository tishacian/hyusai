import asyncio
import base64
import json
import pytest

from app.models.audit import AuditLog
from app.models.capability import Capability
from app.models.context import Context
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.knowledge_capture import (
    amend_capture_event,
    amend_capture_plan,
    apply_proposal_report_instruction,
    apply_session_closure_action,
    build_session_closure_sheet,
    create_capture_plan,
    approve_capture_plan,
    append_turn,
    build_open_questions,
    build_quality_backlog,
    classify_conversation_intent,
    create_update_proposal,
    defer_quality_item,
    extend_capture_session,
    finalize_capture,
    finalize_capture_section,
    answer_proposal_open_question,
    set_active_capture_section,
    get_session,
    list_capture_events,
    list_published_fiches,
    prefetch_capture_retrieval,
    process_conversation_step,
    publish_proposal_to_knowledge,
    review_proposal,
    serialize_session,
    start_session,
    structure_capture_payload,
    update_oracle_question_statuses,
    update_proposal_open_question_statuses,
    update_capture_session_flags,
    _filter_retrieval_by_min_score,
    _normalized_relevance_score,
)
from app.services.capture_report_templates import (
    ANDRITZ_TEMPLATE_ID,
    INDUSTRIAL_TEMPLATE_ID,
    build_andritz_knowledge_sheet,
    build_knowledge_sheet_content,
    resolve_knowledge_sheet_template,
)
from app.services.chains.dag_validator import validate_flow
from app.services.skills_registry.seed import seed_skills_and_capabilities
from app.services.skills_registry.wrappers import runtime_status
from app.services.systems.bootstrap import (
    EXPERT_CAPTURE_CAPABILITY_SLUG,
    EXPERT_CAPTURE_SYSTEM_NAME,
    ensure_expert_capture_system_default,
)


_WEBM_HEADER_CHUNK = b"\x1a\x45\xdf\xa3" + b"\x00" * 8


def _approve(db_session, workspace: Workspace, session):
    return approve_capture_plan(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        actor_user_id="test-user",
    )


def _guided_plan_kwargs() -> dict:
    """Topic-plan sessions require explicit admin-style AI plan permission in tests."""
    return {"plan_mode": "ai_plan", "allow_ai_plan": True}


def test_seeded_expert_capture_capability_and_bound_skills(db_session):
    report = seed_skills_and_capabilities(db_session)

    assert report["skills_added"] >= 1
    assert runtime_status("semantic_search_v1") == "bound"
    assert runtime_status("voice_transcribe_v1") == "bound"
    assert runtime_status("voice_tts_v1") == "bound"
    assert runtime_status("voice_realtime_session_v1") == "bound"
    assert runtime_status("voice_oracle_turn_v1") == "bound"
    assert runtime_status("voice_tandem_oracle_v1") == "bound"
    assert runtime_status("knowledge_gap_analysis_v1") == "bound"
    assert runtime_status("expert_interview_plan_v1") == "bound"


def _capture_capability(db_session) -> Capability:
    return (
        db_session.query(Capability)
        .filter(Capability.slug == EXPERT_CAPTURE_CAPABILITY_SLUG)
        .one()
    )


def test_expert_capture_seed_adopts_existing_capability_system(db_session):
    """A blueprint/manual capture system must be adopted, not duplicated by name."""
    workspace = Workspace(id="ws-capture-adopt", name="Capture Adopt", slug="capture-adopt")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)
    capability = _capture_capability(db_session)
    branded = System(
        workspace_id=workspace.id,
        name="Andritz Expert Knowledge Capture System",
        objective="Branded capture",
        capability_id=capability.id,
        status="active",
        created_by="alice@acme.test",
    )
    db_session.add(branded)
    db_session.commit()

    adopted = ensure_expert_capture_system_default(db_session, workspace.id)

    assert adopted.id == branded.id
    assert adopted.name == "Andritz Expert Knowledge Capture System"
    active = (
        db_session.query(System)
        .filter(
            System.workspace_id == workspace.id,
            System.capability_id == capability.id,
            System.status != "retired",
        )
        .all()
    )
    assert len(active) == 1
    assert not any(s.name == EXPERT_CAPTURE_SYSTEM_NAME for s in active)


def test_expert_capture_seed_retires_redundant_generic(db_session):
    """An already-seeded generic is archived once a branded capture system exists."""
    workspace = Workspace(id="ws-capture-dedupe", name="Capture Dedupe", slug="capture-dedupe")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)
    capability = _capture_capability(db_session)

    generic = ensure_expert_capture_system_default(db_session, workspace.id)
    assert generic.name == EXPERT_CAPTURE_SYSTEM_NAME

    branded = System(
        workspace_id=workspace.id,
        name="Andritz Expert Knowledge Capture System",
        objective="Branded capture",
        capability_id=capability.id,
        status="active",
        created_by="alice@acme.test",
    )
    db_session.add(branded)
    db_session.commit()

    adopted = ensure_expert_capture_system_default(db_session, workspace.id)

    assert adopted.id == branded.id
    db_session.refresh(generic)
    assert generic.status == "retired"
    active = (
        db_session.query(System)
        .filter(
            System.workspace_id == workspace.id,
            System.capability_id == capability.id,
            System.status != "retired",
        )
        .all()
    )
    assert [s.id for s in active] == [branded.id]


def test_expert_capture_system_seed_populates_flow_and_session_binding(db_session):
    workspace = Workspace(id="ws-capture-system", name="Capture System", slug="capture-system")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    system = ensure_expert_capture_system_default(db_session, workspace.id)

    assert system is not None
    assert system.name == "Expert Knowledge Capture"
    assert system.execution_mode == "human_augmented"
    assert system.retrieval_mode_default == "chah"
    assert len(system.skill_ids) == 13
    assert system.flow_definition["variant"] == "expert_knowledge_capture"
    assert system.flow_definition["ui"]["type"] == "knowledge_capture"
    assert system.flow_definition["ui"]["entry_route"] == "capture"
    assert [issue for issue in validate_flow(system.flow_definition) if issue.level == "error"] == []
    node_ids = {node["id"] for node in system.flow_definition["nodes"]}
    assert "skill.semantic_search_prefetch" in node_ids
    assert "skill.voice_tandem_oracle" in node_ids
    assert "hitl.proposal_review" in node_ids

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Expert Knowledge Capture",
        objective="Capture expert maintenance decisions.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
    )
    assert session.system_id == system.id


def test_capture_plan_asks_business_question_for_runtime_objective(db_session):
    workspace = Workspace(id="ws-capture-runtime-objective", name="Capture Runtime", slug="capture-runtime")
    context = Context(
        id="ctx-andritz-runtime-objective",
        workspace_id=workspace.id,
        name="Andritz MVP Knowledge Context",
        environment_state={"collection": "andritz-mvp-knowledge"},
    )
    db_session.add_all([workspace, context])
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Expert Knowledge Capture",
        objective=(
            "Run guided voice-to-voice expert interviews, retrieve live Knowledge context, "
            "evaluate each answer, and produce HITL-reviewable knowledge update proposals."
        ),
        **_guided_plan_kwargs(),
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=context.id,
        system_id=None,
        knowledge_refs=[],
    )

    first_question = session.plan["questions"][0]["question"]
    assert "Run guided voice-to-voice" not in first_question
    assert "HITL-reviewable" not in first_question
    assert "décision métier ou terrain" in first_question
    assert "andritz-mvp-knowledge" in first_question


def test_capture_plan_builds_topic_tree_with_flat_projection(db_session):
    workspace = Workspace(id="ws-capture-topic-plan", name="Capture Topic Plan", slug="capture-topic-plan")
    context = Context(
        id="ctx-topic-plan",
        workspace_id=workspace.id,
        name="BBA120 manuals pilot",
        data_refs=["Manual_BBA120.zip"],
        environment_state={"collection": "andritz-manuals-bba120-pilot"},
    )
    db_session.add_all([workspace, context])
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Topic capture",
        objective="Capture expert troubleshooting decisions for BBA120 manuals.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=context.id,
        system_id=None,
        knowledge_refs=[],
        **_guided_plan_kwargs(),
    )

    assert session.plan["schema_version"] == "topic_plan_v1"
    assert session.plan["review"]["status"] == "draft"
    assert session.plan["topics"]
    assert session.plan["questions"]
    first_topic = session.plan["topics"][0]
    first_question = session.plan["questions"][0]
    assert first_topic["knowledge_refs"][0]["ref"] == "andritz-manuals-bba120-pilot"
    assert first_question["topic_id"] == first_topic["id"]
    assert " / " in first_question["path_label"]


def test_topic_plan_edit_and_start_without_approval_gate(db_session):
    workspace = Workspace(id="ws-capture-topic-edit", name="Capture Topic Edit", slug="capture-topic-edit")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Editable topic capture",
        objective="Capture expert troubleshooting decisions.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        **_guided_plan_kwargs(),
    )
    edited_plan = dict(session.plan)
    edited_plan["topics"] = [dict(topic) for topic in session.plan["topics"]]
    edited_plan["topics"][0] = {
        **edited_plan["topics"][0],
        "title": "Décisions terrain validées",
        "subtopics": [dict(subtopic) for subtopic in edited_plan["topics"][0]["subtopics"]],
    }
    edited_plan["topics"][0]["subtopics"][0] = {
        **edited_plan["topics"][0]["subtopics"][0],
        "questions": [dict(question) for question in edited_plan["topics"][0]["subtopics"][0]["questions"]],
    }
    edited_plan["topics"][0]["subtopics"][0]["questions"][0]["question"] = (
        "Quelle décision terrain BBA120 doit être explicitée avant validation Knowledge ?"
    )

    amended = amend_capture_plan(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        plan=edited_plan,
        actor_user_id="operator-1",
    )
    assert amended.plan["review"]["status"] == "edited"
    assert amended.plan["topics"][0]["title"] == "Décisions terrain validées"
    assert amended.plan["questions"][0]["question"].startswith("Quelle décision terrain")

    turn_result = append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        question_id=amended.plan["questions"][0]["id"],
        text=(
            "Quand la ligne dérive après redémarrage, je vérifie le rapport et "
            "les réglages parce que ce contexte explique la décision terrain."
        ),
    )
    assert turn_result["session"]["status"] == "active"
    assert turn_result["turn"]["topic_path"]
    assert turn_result["evaluation"]["topic_path"] == turn_result["turn"]["topic_path"]


def test_free_conversation_plan_starts_without_questions(db_session):
    workspace = Workspace(id="ws-free-capture", name="Free Capture", slug="free-capture")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Capture libre paliers hydro",
        objective="Capturer les décisions terrain liées aux paliers hydro.",
        expert_profile="Responsable maintenance",
        duration_minutes=45,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        plan_mode="free_conversation",
    )

    assert session.plan["schema_version"] == "free_conversation_v1"
    assert session.plan["questions"] == []
    assert session.plan["capture_policy"]["planned_questions"] is False
    assert session.metrics["coverage"] is None

    turn_result = append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        question_id=None,
        text=(
            "Sur les paliers hydro, je priorise le bruit, la température et la tendance vibratoire. "
            "Si la température monte lentement avec une vibration stable, je traite d'abord la lubrification."
        ),
    )

    assert turn_result["session"]["status"] == "active"
    assert turn_result["session"]["metrics"]["coverage"] is None
    assert turn_result["next_question_id"] is None


def test_written_capture_turn_keeps_document_context_off_the_stt_path(db_session):
    workspace = Workspace(id="ws-text-doc-capture", name="Text Doc Capture", slug="text-doc-capture")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Capture écrite documentée",
        objective="Capturer les observations d'un expert sur une page de manuel.",
        expert_profile="Responsable maintenance",
        duration_minutes=30,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        plan_mode="free_conversation",
    )
    visual_context = {
        "document_id": "manual-pdf",
        "collection": "capture-session-text-doc",
        "filename": "manuel.pdf",
        "title": "Manuel ligne BBA",
        "page": 7,
        "association_mode": "active_view",
    }

    result = append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        question_id=None,
        text="Sur cette page, le schéma montre que le capteur doit rester avant la vanne de bypass.",
        input_modality="text",
        document_refs=[visual_context],
        visual_context=visual_context,
        compute_evaluation=False,
    )

    assert result["turn"]["input_modality"] == "text"
    assert result["turn"]["document_refs"][0]["document_id"] == "manual-pdf"
    assert result["turn"]["document_refs"][0]["page"] == 7

    events = list_capture_events(db_session, workspace_id=workspace.id, session_id=session.id)
    assert not any(event.event_type == "stt_final" for event in events)
    finalized = next(event for event in events if event.event_type == "expert_turn_finalized")
    assert finalized.source == "expert_text"
    assert finalized.meta_data["document_refs"][0]["filename"] == "manuel.pdf"

    loaded = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    payload = structure_capture_payload(loaded, events)
    fact = payload["captured_facts"][0]
    assert fact["input_modality"] == "text"
    assert fact["document_refs"][0]["page"] == 7
    topic = payload["plan_structure"]["topics"][0]
    assert topic["title"] == "Synthèse de la capture"
    assert topic["sources"][0]["kind"] == "capture_document_ref"
    assert topic["sources"][0]["page"] == 7


def test_capture_plan_turn_and_review_proposal(db_session):
    workspace = Workspace(id="ws-capture", name="Capture", slug="capture")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Maintenance expert capture",
        objective="Capture tacit troubleshooting knowledge for industrial maintenance.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=["crm-export.csv"],
        **_guided_plan_kwargs(),
    )

    assert session.status == "planned"
    assert session.plan["duration_minutes"] == 20
    assert len(session.plan["questions"]) >= 2
    assert session.knowledge_gaps[0]["status"] == "open"
    session = _approve(db_session, workspace, session)

    question_id = session.plan["questions"][0]["id"]
    turn_result = append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        question_id=question_id,
        text=(
            "Quand la machine vibre après maintenance, je vérifie d'abord le rapport "
            "d'intervention et l'historique CRM parce que le contexte client indique "
            "souvent si le problème vient d'un réglage récent. Par exemple, sur une "
            "ligne calandre, un changement de rouleau modifie le diagnostic."
        ),
    )

    assert turn_result["evaluation"]["verdict"] in {"sufficient", "partial"}
    assert turn_result["session"]["metrics"]["answers_evaluated"] == 1
    assert "machine vibre" in turn_result["session"]["metrics"]["summary_short"]
    assert isinstance(turn_result["session"]["metrics"]["open_questions_count"], int)
    assert turn_result["session"]["metrics"]["last_activity"]
    source_event_id = turn_result["turn"]["source_event_id"]

    events = list_capture_events(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
    )
    assert any(event.event_type == "capture_plan_created" for event in events)
    assert any(event.id == source_event_id for event in events)

    amended = amend_capture_event(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        event_id=source_event_id,
        text_amended=(
            "Quand la machine vibre après maintenance, je vérifie le rapport "
            "d'intervention, l'historique CRM et la température du rouleau parce "
            "que ces trois signaux expliquent souvent le défaut."
        ),
        actor="operator@datategy.local",
        reason="Précision ajoutée après relecture HITL.",
    )
    assert amended["event"]["status"] == "amended"
    assert amended["event"]["text_amended"]
    assert amended["amendment"]["event_type"] == "transcript_amended"

    proposal = create_update_proposal(db_session, workspace_id=workspace.id, session_id=session.id)
    payload = proposal.proposal
    assert proposal.status == "pending_review"
    assert payload["review"]["required"] is True
    assert payload["recommended_ingestion"]["metadata"]["source"] == "expert_capture_session"
    assert payload["recommended_ingestion"]["metadata"]["amendment_count"] >= 1
    assert "température du rouleau" in payload["recommended_ingestion"]["content"]
    assert payload["amendments"]
    assert payload["transcript_segments"]
    amended_segments = [segment for segment in payload["transcript_segments"] if segment["status"] == "amended"]
    assert amended_segments
    assert "historique CRM" in (amended_segments[0]["raw_segment"] or "")
    assert "température du rouleau" in (amended_segments[0]["amended_segment"] or "")
    assert payload["audit"]["source_of_truth"] == "expert_capture_events"

    reviewed = review_proposal(
        db_session,
        workspace_id=workspace.id,
        proposal_id=proposal.id,
        status="accepted",
        reviewer="operator@datategy.local",
        review_notes="Validé pour démo.",
    )
    assert reviewed.status == "accepted"
    assert reviewed.reviewed_at is not None


def test_capture_attribution_persists_user_ids(db_session):
    workspace = Workspace(id="ws-capture-attribution", name="Capture Attribution", slug="capture-attribution")
    user = User(id="user-capture-author", username="author@datategy.local", email="author@datategy.local")
    reviewer = User(id="user-capture-reviewer", username="reviewer@datategy.local", email="reviewer@datategy.local")
    db_session.add_all([workspace, user, reviewer])
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Attributed capture",
        objective="Capture tacit troubleshooting knowledge for attribution tests.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        created_by_user_id=user.id,
        **_guided_plan_kwargs(),
    )
    assert session.created_by_user_id == user.id
    assert db_session.query(Run).filter(Run.id == session.run_id).first().initiated_by_user_id == user.id
    session = _approve(db_session, workspace, session)

    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        question_id=session.plan["questions"][0]["id"],
        text=(
            "Quand la machine vibre après maintenance, je vérifie le rapport "
            "d'intervention parce que le changement récent explique souvent le diagnostic."
        ),
        actor_user_id=user.id,
    )
    proposal = create_update_proposal(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        created_by_user_id=user.id,
    )
    assert proposal.created_by_user_id == user.id

    reviewed = review_proposal(
        db_session,
        workspace_id=workspace.id,
        proposal_id=proposal.id,
        status="accepted",
        reviewer=reviewer.email,
        review_notes="Validated.",
        reviewer_user_id=reviewer.id,
    )
    assert reviewed.reviewer_user_id == reviewer.id


def test_proposal_open_question_statuses_are_persisted(db_session):
    workspace = Workspace(id="ws-proposal-questions", name="Proposal Questions", slug="proposal-questions")
    user = User(id="user-proposal-question", username="reviewer@datategy.local", email="reviewer@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Proposal question capture",
        objective="Capture tacit troubleshooting knowledge for report review.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        created_by_user_id=user.id,
        **_guided_plan_kwargs(),
    )
    session = _approve(db_session, workspace, session)
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        question_id=session.plan["questions"][0]["id"],
        text="Je contrôle toujours la pompe avant de valider la procédure terrain.",
        actor_user_id=user.id,
    )
    proposal = create_update_proposal(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        created_by_user_id=user.id,
    )
    payload = dict(proposal.proposal or {})
    payload["open_questions"] = [
        {
            "gap_id": "validation-owner",
            "follow_up": "Qui valide la procédure terrain ?",
            "reason": "Le responsable de validation n'est pas précisé.",
            "priority": 3,
        }
    ]
    proposal.proposal = payload
    db_session.commit()

    deferred = update_proposal_open_question_statuses(
        db_session,
        workspace_id=workspace.id,
        proposal_id=proposal.id,
        items=[
            {
                "question_key": "validation-owner",
                "question_text": "Qui valide la procédure terrain ?",
                "status": "deferred",
            }
        ],
        actor_user_id=user.id,
        actor_label=user.email,
    )
    assert deferred.proposal["open_questions"][0]["status"] == "deferred"
    assert deferred.proposal["open_questions"][0]["status_updated_by_user_id"] == user.id
    deferred_session = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    assert deferred_session.metrics["open_questions_count"] == 0
    assert deferred_session.metrics["proposal_open_questions_count"] == 0

    restored = update_proposal_open_question_statuses(
        db_session,
        workspace_id=workspace.id,
        proposal_id=proposal.id,
        items=[
            {
                "question_key": "validation-owner",
                "question_text": "Qui valide la procédure terrain ?",
                "status": "open",
            }
        ],
        actor_user_id=user.id,
        actor_label=user.email,
    )
    assert restored.proposal["open_questions"][0]["status"] == "open"
    restored_session = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    assert restored_session.metrics["open_questions_count"] == 1
    events = list_capture_events(db_session, workspace_id=workspace.id, session_id=proposal.session_id)
    assert any(event.event_type == "proposal_open_question_status_updated" for event in events)

    # Unified lifecycle (c3): "invalid" is the new delete/exclude status.
    invalidated = update_proposal_open_question_statuses(
        db_session,
        workspace_id=workspace.id,
        proposal_id=proposal.id,
        items=[{"question_key": "validation-owner", "status": "invalid"}],
        actor_user_id=user.id,
    )
    assert invalidated.proposal["open_questions"][0]["status"] == "invalid"
    invalidated_session = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    assert invalidated_session.metrics["open_questions_count"] == 0

    # Legacy "dismissed" is still accepted and normalized to "invalid".
    legacy = update_proposal_open_question_statuses(
        db_session,
        workspace_id=workspace.id,
        proposal_id=proposal.id,
        items=[{"question_key": "validation-owner", "status": "dismissed"}],
        actor_user_id=user.id,
    )
    assert legacy.proposal["open_questions"][0]["status"] == "invalid"

    # "answered" is a valid terminal status too.
    answered = update_proposal_open_question_statuses(
        db_session,
        workspace_id=workspace.id,
        proposal_id=proposal.id,
        items=[{"question_key": "validation-owner", "status": "answered"}],
        actor_user_id=user.id,
    )
    assert answered.proposal["open_questions"][0]["status"] == "answered"


def test_proposal_open_question_invalidate_rebuilds_report(db_session):
    workspace = Workspace(id="ws-proposal-q-report", name="Proposal Q Report", slug="proposal-q-report")
    user = User(id="user-proposal-q-report", username="qr@datategy.local", email="qr@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Report rebuild capture",
        objective="Verify open-question lifecycle updates the persisted report.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        created_by_user_id=user.id,
        **_guided_plan_kwargs(),
    )
    session = _approve(db_session, workspace, session)
    proposal = create_update_proposal(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        created_by_user_id=user.id,
    )
    question_text = "Qui valide la procédure terrain ?"
    payload = dict(proposal.proposal or {})
    payload["open_questions"] = [
        {
            "gap_id": "validation-owner",
            "follow_up": question_text,
            "reason": "Le responsable de validation n'est pas précisé.",
            "status": "open",
        }
    ]
    payload["plan_structure"] = {
        "topics": [
            {
                "topic_id": "topic-1",
                "title": "Validation",
                "synthesis": "La procédure terrain est contrôlée avant validation.",
                "open_questions": [
                    {
                        "id": "validation-owner",
                        "text": question_text,
                        "status": "open",
                    }
                ],
                "subtopics": [],
            }
        ],
        "unassigned": [],
    }
    payload["report_markdown"] = (
        "# Report rebuild capture\n\n## Validation\nContenu.\n\n## Questions ouvertes\n- "
        f"{question_text}\n"
    )
    payload["recommended_ingestion"] = {"content": payload["report_markdown"]}
    proposal.proposal = payload
    db_session.commit()

    invalidated = update_proposal_open_question_statuses(
        db_session,
        workspace_id=workspace.id,
        proposal_id=proposal.id,
        items=[{"question_key": "validation-owner", "status": "invalid"}],
        actor_user_id=user.id,
    )
    report = invalidated.proposal["report_markdown"]
    assert question_text not in report
    assert "## Questions ouvertes" not in report
    node_questions = invalidated.proposal["plan_structure"]["topics"][0]["open_questions"]
    assert node_questions[0]["status"] == "invalid"


def test_normalized_relevance_score_prefers_cross_encoder_then_dense():
    # Cross-encoder sigmoid score wins when present.
    assert _normalized_relevance_score(
        {"cross_encoder_score": 0.91, "dense_score": 0.40}
    ) == pytest.approx(0.91)
    # Falls back to the dense cosine when no cross-encoder score is present.
    assert _normalized_relevance_score({"dense_score": 0.367}) == pytest.approx(0.367)
    # Sparse-only / missing-score chunk → no normalized signal.
    assert _normalized_relevance_score({"document_id": "sparse-only"}) is None
    assert _normalized_relevance_score(None) is None


def test_filter_retrieval_by_min_score_thresholds_on_normalized_score():
    # The fusion ``scores`` are tiny client-weighted RRF weights and must NOT
    # drive the filter; only the per-chunk normalized signal (dense cosine /
    # cross-encoder) does.
    chunks = ["strong dense", "weak dense", "cross-encoder hit", "sparse only"]
    metadatas = [
        {"document_id": "doc-a", "title": "Doc A", "dense_score": 0.626},
        {"document_id": "doc-b", "title": "Doc B", "dense_score": 0.12},
        {"document_id": "doc-c", "title": "Doc C", "cross_encoder_score": 0.88, "dense_score": 0.05},
        {"document_id": "doc-d", "title": "Doc D"},
    ]
    scores = [0.0048, 0.0224, 0.0091, 0.0007]
    filtered_chunks, filtered_meta, _filtered_scores = _filter_retrieval_by_min_score(
        chunks,
        metadatas,
        scores,
        0.35,
    )
    # Strong dense kept, weak dense dropped, cross-encoder hit kept (its high
    # cross-encoder score overrides its low dense_score), sparse-only kept.
    assert filtered_chunks == ["strong dense", "cross-encoder hit", "sparse only"]
    assert [meta["document_id"] for meta in filtered_meta] == ["doc-a", "doc-c", "doc-d"]


def test_filter_retrieval_keeps_high_dense_despite_low_fusion_score():
    # Regression: the analysis observed dense_score=0.626 with fusion
    # scores=[0.0048, 0.0224, ...] on the client_weighted path → previously ALL
    # sources were dropped. They must now be kept.
    chunks = ["genuinely relevant"]
    metadatas = [{"document_id": "tech-vocab", "title": "Tech Vocab", "dense_score": 0.626}]
    scores = [0.0048]
    kept_chunks, kept_meta, _kept_scores = _filter_retrieval_by_min_score(
        chunks, metadatas, scores, 0.35
    )
    assert kept_chunks == ["genuinely relevant"]
    assert kept_meta[0]["document_id"] == "tech-vocab"


def test_filter_retrieval_drops_low_dense_score():
    chunks = ["banana noise"]
    metadatas = [{"document_id": "noise", "title": "Noise", "dense_score": 0.04}]
    kept_chunks, kept_meta, _kept_scores = _filter_retrieval_by_min_score(
        chunks, metadatas, [12.5], 0.35
    )
    assert kept_chunks == []
    assert kept_meta == []


def test_filter_retrieval_keeps_missing_normalized_score_chunk():
    # Sparse-only chunk: no dense_score, no cross_encoder_score, tiny fusion
    # weight. Must be kept (its evidence would otherwise be lost).
    chunks = ["sparse exact match"]
    metadatas = [{"document_id": "sparse-1", "title": "Sparse"}]
    kept_chunks, kept_meta, _kept_scores = _filter_retrieval_by_min_score(
        chunks, metadatas, [0.0011], 0.35
    )
    assert kept_chunks == ["sparse exact match"]
    assert kept_meta[0]["document_id"] == "sparse-1"


@pytest.mark.asyncio
async def test_finalize_capture_section_filters_low_score_sources(db_session, monkeypatch):
    import app.services.knowledge_capture as kc

    async def _scored_retrieval(*_a, **_k):
        # Both chunks have tiny client-weighted RRF fusion scores; the dense
        # cosine in metadata is the real relevance signal driving the filter.
        return (
            ["Andritz unrelated doc", "Relevant section note"],
            [
                {"document_id": "andritz-1", "title": "Andritz KB", "dense_score": 0.18},
                {"document_id": "relevant-1", "title": "Process manual", "dense_score": 0.71},
            ],
            [0.0042, 0.0071],
        )

    monkeypatch.setattr(kc, "_retrieve_context_chunks_async", _scored_retrieval)
    monkeypatch.setattr(kc, "_resolve_capture_report_source_min_score", lambda: 0.35)

    workspace = Workspace(id="ws-src-filter", name="Src Filter", slug="src-filter")
    user = User(id="user-src-filter", username="sf@datategy.local", email="sf@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session, topic_id, subtopic_id = _final_phase_session(db_session, workspace, user)
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        text="La pression hydraulique est réglée à 12 bar avant démarrage.",
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        actor_user_id=user.id,
    )

    entry = await finalize_capture_section(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        workspace_slug=workspace.slug,
    )

    source_titles = [src.get("title") for src in entry.get("sources") or []]
    assert "Andritz KB" not in source_titles
    assert "Process manual" in source_titles


@pytest.mark.asyncio
async def test_finalize_capture_section_keeps_high_dense_low_fusion_sources(db_session, monkeypatch):
    # Regression: long capture queries route to the client_weighted fusion path
    # whose scores (~0.005-0.02) sit far below any cosine threshold. A section
    # whose chunks have tiny fusion scores but high dense relevance (and a
    # sparse-only chunk with no normalized signal) must keep ALL its sources.
    import app.services.knowledge_capture as kc

    async def _scored_retrieval(*_a, **_k):
        return (
            ["Strong KB note", "Sparse exact match"],
            [
                {"document_id": "kb-strong", "title": "Hydraulic Manual", "dense_score": 0.626},
                {"document_id": "kb-sparse", "title": "Spare Parts Index"},
            ],
            [0.0048, 0.0011],
        )

    monkeypatch.setattr(kc, "_retrieve_context_chunks_async", _scored_retrieval)
    monkeypatch.setattr(kc, "_resolve_capture_report_source_min_score", lambda: 0.35)

    workspace = Workspace(id="ws-src-keep", name="Src Keep", slug="src-keep")
    user = User(id="user-src-keep", username="sk@datategy.local", email="sk@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session, topic_id, subtopic_id = _final_phase_session(db_session, workspace, user)
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        text="La pression hydraulique est réglée à 12 bar avant démarrage.",
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        actor_user_id=user.id,
    )

    entry = await finalize_capture_section(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        workspace_slug=workspace.slug,
    )

    source_titles = [src.get("title") for src in entry.get("sources") or []]
    assert "Hydraulic Manual" in source_titles
    assert "Spare Parts Index" in source_titles


@pytest.mark.asyncio
async def test_apply_report_instruction_updates_current_report_without_llm(db_session):
    workspace, user, proposal = _report_instruction_fixture(db_session)

    updated = await apply_proposal_report_instruction(
        db_session,
        workspace_id=workspace.id,
        proposal_id=proposal.id,
        instruction="Ajoute une mention sur le contrôle visuel terrain.",
        current_content="# Rapport\n\nContenu initial.",
        actor_user_id=user.id,
        actor_label=user.email,
        use_llm=False,
    )

    payload = updated.proposal
    assert "Modification demandée" in payload["report_markdown"]
    assert "contrôle visuel terrain" in payload["report_markdown"]
    assert payload["recommended_ingestion"]["content"] == payload["report_markdown"]
    assert payload["recommended_ingestion"]["metadata"]["last_instruction_status"] == "instruction_recorded_fallback"
    assert payload["report_edit"]["status"] == "instruction_recorded_fallback"
    events = list_capture_events(db_session, workspace_id=workspace.id, session_id=proposal.session_id)
    assert any(event.event_type == "proposal_report_instruction_applied" for event in events)


def _report_instruction_fixture(db_session, *, suffix: str = ""):
    suffix = suffix or "default"
    workspace = Workspace(id="ws-capture-report-instruction", name="Capture Report Instruction", slug="capture-report-instruction")
    if suffix != "default":
        workspace = Workspace(
            id=f"ws-capture-report-instruction-{suffix}",
            name=f"Capture Report Instruction {suffix}",
            slug=f"capture-report-instruction-{suffix}",
        )
    user = User(
        id=f"user-report-editor-{suffix}",
        username=f"editor-{suffix}@datategy.local",
        email=f"editor-{suffix}@datategy.local",
    )
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Instruction capture",
        objective="Capture tacit troubleshooting knowledge for report editing.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        created_by_user_id=user.id,
        **_guided_plan_kwargs(),
    )
    session = _approve(db_session, workspace, session)
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        question_id=session.plan["questions"][0]["id"],
        text="Je valide toujours le contrôle visuel avant de publier une procédure de maintenance.",
        actor_user_id=user.id,
    )
    proposal = create_update_proposal(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        created_by_user_id=user.id,
    )
    return workspace, user, proposal


@pytest.mark.asyncio
async def test_apply_report_instruction_rejects_blank_without_mutation(db_session):
    workspace, user, proposal = _report_instruction_fixture(db_session, suffix="blank")
    before_payload = json.loads(json.dumps(proposal.proposal))

    with pytest.raises(ValueError, match="Report instruction cannot be empty"):
        await apply_proposal_report_instruction(
            db_session,
            workspace_id=workspace.id,
            proposal_id=proposal.id,
            instruction=" \n\t ",
            current_content="# Rapport\n\nContenu initial.",
            actor_user_id=user.id,
            actor_label=user.email,
            use_llm=False,
        )

    db_session.refresh(proposal)
    assert proposal.proposal == before_payload
    events = list_capture_events(db_session, workspace_id=workspace.id, session_id=proposal.session_id)
    assert not any(event.event_type == "proposal_report_instruction_applied" for event in events)


@pytest.mark.asyncio
async def test_apply_report_instruction_llm_failure_falls_back_with_audit(db_session, monkeypatch):
    workspace, user, proposal = _report_instruction_fixture(db_session, suffix="llm-failure")

    monkeypatch.setattr(
        "app.services.knowledge_capture._resolve_llm_config",
        lambda workspace_id=None: ("test-key", "gpt-test"),
    )

    class FakeCompletions:
        async def create(self, **kwargs):
            raise RuntimeError("simulated rewrite failure")

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr("openai.AsyncOpenAI", lambda api_key=None: FakeClient())

    original_report = "# Rapport\n\nContenu initial avec une source terrain."
    updated = await apply_proposal_report_instruction(
        db_session,
        workspace_id=workspace.id,
        proposal_id=proposal.id,
        instruction="Ajoute une précision sur les conditions de validation.",
        current_content=original_report,
        actor_user_id=user.id,
        actor_label=user.email,
        use_llm=True,
    )

    payload = updated.proposal
    assert original_report in payload["report_markdown"]
    assert "Modification demandée" in payload["report_markdown"]
    assert "conditions de validation" in payload["report_markdown"]
    assert payload["recommended_ingestion"]["content"] == payload["report_markdown"]
    assert payload["recommended_ingestion"]["metadata"]["last_instruction_status"] == "instruction_recorded_fallback"
    assert payload["recommended_ingestion"]["metadata"]["last_instruction_provider"] == "deterministic"
    assert payload["report_edit"]["status"] == "instruction_recorded_fallback"
    assert payload["report_edit"]["provider"] == "deterministic"
    events = list_capture_events(db_session, workspace_id=workspace.id, session_id=proposal.session_id)
    edit_events = [event for event in events if event.event_type == "proposal_report_instruction_applied"]
    assert len(edit_events) == 1
    assert edit_events[0].status == "instruction_recorded_fallback"


def test_update_proposal_adds_publication_defaults_and_preserves_editor_choices(db_session):
    workspace = Workspace(id="ws-capture-publication-defaults", name="Capture Publication Defaults", slug="capture-publication-defaults")
    context = Context(
        id="ctx-capture-publication-defaults",
        workspace_id=workspace.id,
        name="Maintenance Knowledge",
        environment_state={"collection": "maintenance-capture-knowledge"},
    )
    db_session.add_all([workspace, context])
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Maintenance vacuum",
        objective="Capture maintenance decisions for vacuum inspection and troubleshooting.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=context.id,
        system_id=None,
        knowledge_refs=[],
        **_guided_plan_kwargs(),
    )
    session = _approve(db_session, workspace, session)
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        question_id=session.plan["questions"][0]["id"],
        text="Pour la maintenance vacuum, je contrôle les fuites et l'état du filtre avant remise en route.",
    )

    proposal = create_update_proposal(db_session, workspace_id=workspace.id, session_id=session.id)
    publication = proposal.proposal["publication"]
    assert publication["category"] == "maintenance"
    assert publication["destination"] == "maintenance-capture-knowledge"
    assert publication["destination_scope"] == "maintenance-capture-knowledge"
    assert publication["final_title"] == proposal.proposal["recommended_ingestion"]["title"]
    assert publication["include_unresolved_questions"] is True
    assert proposal.proposal["recommended_ingestion"]["metadata"]["publication_category_suggested"] == "maintenance"
    assert (
        proposal.proposal["recommended_ingestion"]["metadata"]["publication_destination_scope_suggested"]
        == "maintenance-capture-knowledge"
    )

    payload = dict(proposal.proposal)
    payload["publication"] = {**publication, "category": "commercial", "destination": "custom-destination"}
    proposal.proposal = payload
    db_session.commit()

    regenerated = create_update_proposal(db_session, workspace_id=workspace.id, session_id=session.id)
    assert regenerated.proposal["publication"]["category"] == "commercial"
    assert regenerated.proposal["publication"]["destination"] == "custom-destination"
    assert regenerated.proposal["publication"]["destination_scope"] == "custom-destination"


def test_plan_framed_report_labels_unassigned_facts_as_out_of_plan(db_session):
    workspace = Workspace(id="ws-capture-out-of-plan", name="Capture Out Of Plan", slug="capture-out-of-plan")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Capture structurée",
        objective="Capturer une procédure terrain.",
        expert_profile="Responsable maintenance",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        plan_mode="provided_plan",
        provided_plan_text="Maintenance vacuum\n- Inspection filtre",
        capture_domain="technical",
        allow_ai_plan=False,
    )
    markdown = build_andritz_knowledge_sheet(
        session,
        [
            {
                "text": "Hors plan, l'équipe note aussi la disponibilité des pièces critiques.",
                "topic_id": "outside-plan",
            }
        ],
    )

    assert "### Points hors plan" in markdown
    assert "Compléments à classer" not in markdown


def test_andritz_report_appends_unresolved_questions_at_the_end(db_session):
    workspace = Workspace(
        id="ws-capture-report-open-questions",
        name="Capture Report Open Questions",
        slug="capture-report-open-questions",
    )
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Fiche maintenance",
        objective="Clarifier la procédure de maintenance terrain.",
        expert_profile="Responsable maintenance",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        plan_mode="free_conversation",
        capture_domain="technical",
    )
    markdown = build_andritz_knowledge_sheet(
        session,
        [{"text": "Décision : conserver la procédure actuelle si le filtre est propre."}],
        open_questions=[
            {
                "gap_id": "validation-owner",
                "follow_up": "Qui valide la procédure finale côté maintenance ?",
                "status": "open",
            },
            {
                "gap_id": "already-answered",
                "follow_up": "Question déjà traitée.",
                "status": "answered",
            },
        ],
    )

    assert "## Questions ouvertes" in markdown
    assert "- Qui valide la procédure finale côté maintenance ?" in markdown
    assert "Question déjà traitée" not in markdown
    assert markdown.rstrip().endswith("- Qui valide la procédure finale côté maintenance ?")


@pytest.mark.asyncio
async def test_publish_persists_export_urls(db_session, monkeypatch):
    workspace = Workspace(id="ws-capture-publish-export", name="Capture Publish Export", slug="capture-publish-export")
    context = Context(
        id="ctx-capture-publish-export",
        workspace_id=workspace.id,
        name="Capture export",
        environment_state={"collection": "capture-export-knowledge"},
    )
    db_session.add_all([workspace, context])
    seed_skills_and_capabilities(db_session)

    class FakeDocumentService:
        def __init__(self, **_: object) -> None:
            pass

        async def ingest_document(self, *_: object, **__: object) -> dict:
            return {"document_id": "doc published/id", "chunks_processed": 1, "status": "success"}

    monkeypatch.setattr("app.services.rag.document_service.DocumentService", FakeDocumentService)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Publication export",
        objective="Publier une capture test.",
        expert_profile="Responsable maintenance",
        duration_minutes=20,
        context_id=context.id,
        system_id=None,
        knowledge_refs=[],
        **_guided_plan_kwargs(),
    )
    session = _approve(db_session, workspace, session)
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        question_id=session.plan["questions"][0]["id"],
        text="La procédure publiée doit rester téléchargeable après validation.",
    )
    proposal = create_update_proposal(db_session, workspace_id=workspace.id, session_id=session.id)
    reviewed = review_proposal(
        db_session,
        workspace_id=workspace.id,
        proposal_id=proposal.id,
        status="accepted",
        reviewer="operator@datategy.local",
        review_notes="Validé pour publication.",
    )

    result = await publish_proposal_to_knowledge(
        db_session,
        workspace=workspace,
        proposal_id=reviewed.id,
        actor_label="operator@datategy.local",
        category="technical",
        destination="capture-export-knowledge",
        final_title="Publication export validée",
    )

    expected_url = "/api/v1/documents/doc%20published%2Fid/raw"
    assert result["export_urls"] == {"download_url": expected_url, "raw_url": expected_url}
    assert result["destination"] == "capture-export-knowledge"
    assert result["destination_scope"] == "capture-export-knowledge"
    assert result["collection"] == "capture-export-knowledge"
    db_session.refresh(reviewed)
    assert reviewed.status == "published"
    assert reviewed.proposal["publication"]["export_urls"] == result["export_urls"]
    assert reviewed.proposal["publication"]["destination_scope"] == "capture-export-knowledge"
    assert reviewed.proposal["publication"]["published_at"]
    assert reviewed.proposal["recommended_ingestion"]["metadata"]["proposal_id"] == reviewed.id
    assert reviewed.proposal["recommended_ingestion"]["metadata"]["capture_session_id"] == session.id


@pytest.mark.asyncio
async def test_publish_defaults_to_chat_expert_fiche_collection(db_session, monkeypatch):
    """Without an explicit destination, publish lands in the same collection
    chat corrections use (resolve_expert_fiche_collection over the chat
    source_policy), with the expert-fiche pin metadata."""
    workspace = Workspace(
        id="ws-capture-publish-default",
        name="Capture Publish Default",
        slug="capture-publish-default",
        settings={
            "source_policy": {
                "expert_fiche_correction_enabled": True,
                "expert_fiche_collection": "validated-fiches",
            }
        },
    )
    context = Context(
        id="ctx-capture-publish-default",
        workspace_id=workspace.id,
        name="Capture default",
        environment_state={"collection": "capture-context-knowledge"},
    )
    db_session.add_all([workspace, context])
    seed_skills_and_capabilities(db_session)

    captured_metadata: dict = {}

    class FakeDocumentService:
        def __init__(self, **_: object) -> None:
            pass

        async def ingest_document(self, *_: object, **kwargs: object) -> dict:
            captured_metadata.update(kwargs.get("document_metadata") or {})
            return {"document_id": "doc-default", "chunks_processed": 1, "status": "success"}

    monkeypatch.setattr("app.services.rag.document_service.DocumentService", FakeDocumentService)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Publication défaut",
        objective="Publier sans destination explicite.",
        expert_profile="Responsable maintenance",
        duration_minutes=20,
        context_id=context.id,
        system_id=None,
        knowledge_refs=[],
        **_guided_plan_kwargs(),
    )
    session = _approve(db_session, workspace, session)
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        question_id=session.plan["questions"][0]["id"],
        text="La procédure doit rejoindre la base interrogée par le chat recherche.",
    )
    proposal = create_update_proposal(db_session, workspace_id=workspace.id, session_id=session.id)
    # The suggested default already targets the chat expert-fiche collection.
    assert proposal.proposal["publication"]["destination"] == "validated-fiches"
    reviewed = review_proposal(
        db_session,
        workspace_id=workspace.id,
        proposal_id=proposal.id,
        status="accepted",
        reviewer="operator@datategy.local",
        review_notes="Validé.",
    )

    result = await publish_proposal_to_knowledge(
        db_session,
        workspace=workspace,
        proposal_id=reviewed.id,
        actor_label="operator@datategy.local",
    )

    assert result["destination"] == "validated-fiches"
    assert result["destination_scope"] == "validated-fiches"
    assert result["collection"] == "validated-fiches"
    # Pin parity with chat corrections: is_expert_fiche_metadata keys on this.
    assert captured_metadata["source_type"] == "expert_fiche"


@pytest.mark.asyncio
async def test_publish_promotes_referenced_capture_documents(db_session, monkeypatch):
    from app.services.knowledge_collections import (
        create_or_get_collection,
        get_collection_or_404,
        original_key,
        update_collection_status,
        upsert_collection_source,
    )
    from app.services.object_store import get_object_store

    workspace = Workspace(id="ws-capture-publish-docs", name="Capture Publish Docs", slug="capture-publish-docs")
    context = Context(
        id="ctx-capture-publish-docs",
        workspace_id=workspace.id,
        name="Capture docs export",
        environment_state={"collection": "capture-export-knowledge"},
    )
    db_session.add_all([workspace, context])
    seed_skills_and_capabilities(db_session)

    source_collection = create_or_get_collection(
        db_session,
        workspace=workspace,
        slug="capture-session-source",
        name="Capture session source",
    )
    store = get_object_store()
    source_filename = "support-technique.pdf"
    content = b"%PDF-1.4\ncapture support\n"
    store.write_bytes(original_key(source_collection, source_filename), content)
    upsert_collection_source(
        db_session,
        collection=source_collection,
        filename=source_filename,
        status="ready",
        origin="capture_session_upload",
        size_bytes=len(content),
        source_metadata={"document_id": source_filename},
    )
    update_collection_status(
        db_session,
        source_collection.id,
        status="ready",
        document_names=[source_filename],
        document_count=1,
    )
    db_session.commit()

    class FakeDocumentService:
        def __init__(self, **_: object) -> None:
            pass

        async def ingest_document(self, *_: object, **__: object) -> dict:
            return {"document_id": "published-fiche", "chunks_processed": 1, "status": "success"}

    dispatched: list[tuple[str, bool]] = []

    def fake_dispatch(db, job, *, allow_inline_fallback=True):  # noqa: ANN001
        dispatched.append((job.id, allow_inline_fallback))
        return f"task-{job.id}"

    monkeypatch.setattr("app.services.rag.document_service.DocumentService", FakeDocumentService)
    monkeypatch.setattr("app.services.worker_dispatch.dispatch_worker_job", fake_dispatch)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Publication avec support",
        objective="Capturer une règle liée à un support documentaire.",
        expert_profile="Responsable maintenance",
        duration_minutes=20,
        context_id=context.id,
        system_id=None,
        knowledge_refs=[],
        plan_mode="free_conversation",
    )
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        text="Sur cette page, la procédure impose de purger avant redémarrage.",
        input_modality="text",
        document_refs=[
            {
                "kind": "capture_document_ref",
                "document_id": source_filename,
                "collection": source_collection.slug,
                "filename": source_filename,
                "title": "Support technique",
                "page": 4,
            }
        ],
        compute_evaluation=False,
    )
    proposal = create_update_proposal(db_session, workspace_id=workspace.id, session_id=session.id)
    reviewed = review_proposal(
        db_session,
        workspace_id=workspace.id,
        proposal_id=proposal.id,
        status="accepted",
        reviewer="operator@datategy.local",
        review_notes="Validé.",
    )

    result = await publish_proposal_to_knowledge(
        db_session,
        workspace=workspace,
        proposal_id=reviewed.id,
        actor_label="operator@datategy.local",
        destination="capture-export-knowledge",
    )

    promoted = result["promoted_documents"]
    assert promoted
    assert promoted[0]["collection"] == "capture-export-knowledge"
    assert promoted[0]["page"] == 4
    assert dispatched
    assert dispatched[0][1] is False

    destination_collection = get_collection_or_404(
        db_session,
        workspace_id=workspace.id,
        collection_ref="capture-export-knowledge",
    )
    assert store.exists(original_key(destination_collection, promoted[0]["filename"]))
    db_session.refresh(reviewed)
    publication = reviewed.proposal["publication"]
    assert publication["promoted_documents"][0]["filename"] == promoted[0]["filename"]
    report_source = reviewed.proposal["plan_structure"]["topics"][0]["sources"][0]
    assert report_source["collection"] == "capture-export-knowledge"
    assert report_source["publication_promoted"] is True


@pytest.mark.asyncio
async def test_list_published_fiches_reads_proposal_publication_metadata(db_session, monkeypatch):
    workspace = Workspace(id="ws-capture-fiches-list", name="Capture Fiches List", slug="capture-fiches-list")
    context = Context(
        id="ctx-capture-fiches-list",
        workspace_id=workspace.id,
        name="Capture fiches",
        environment_state={"collection": "capture-fiches-knowledge"},
    )
    db_session.add_all([workspace, context])
    seed_skills_and_capabilities(db_session)

    class FakeDocumentService:
        def __init__(self, **_: object) -> None:
            pass

        async def ingest_document(self, *_: object, **__: object) -> dict:
            return {"document_id": "doc-fiche-list", "chunks_processed": 3, "status": "success"}

    monkeypatch.setattr("app.services.rag.document_service.DocumentService", FakeDocumentService)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Fiche list session",
        objective="Lister les fiches publiées.",
        expert_profile="Expert",
        duration_minutes=20,
        context_id=context.id,
        system_id=None,
        knowledge_refs=[],
        **_guided_plan_kwargs(),
    )
    session = _approve(db_session, workspace, session)
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        question_id=session.plan["questions"][0]["id"],
        text="La procédure est validée pour la ligne pilote.",
    )
    proposal = create_update_proposal(db_session, workspace_id=workspace.id, session_id=session.id)
    reviewed = review_proposal(
        db_session,
        workspace_id=workspace.id,
        proposal_id=proposal.id,
        status="accepted",
        reviewer="reviewer@datategy.local",
        review_notes="Validé.",
    )

    await publish_proposal_to_knowledge(
        db_session,
        workspace=workspace,
        proposal_id=reviewed.id,
        actor_label="reviewer@datategy.local",
        category="maintenance",
        destination="capture-fiches-knowledge",
        final_title="Fiche maintenance validée",
    )

    payload = list_published_fiches(db_session, workspace_id=workspace.id, q="maintenance")
    assert payload["total"] == 1
    fiche = payload["fiches"][0]
    assert fiche["title"] == "Fiche maintenance validée"
    assert fiche["category"] == "maintenance"
    assert fiche["destination"] == "capture-fiches-knowledge"
    assert fiche["document_id"] == "doc-fiche-list"
    assert fiche["chunks_processed"] == 3
    assert fiche["capture_session_id"] == session.id


def test_conversation_only_step_flow_requires_voice_confirmation(db_session):
    workspace = Workspace(id="ws-capture-conv", name="Capture Conv", slug="capture-conv")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Conversation only capture",
        objective="Capture tacit troubleshooting knowledge for industrial maintenance.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        **_guided_plan_kwargs(),
    )
    question_id = session.plan["questions"][0]["id"]
    session = _approve(db_session, workspace, session)

    answer_step = process_conversation_step(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        client_turn_id="conv-turn-1",
        question_id=question_id,
        retrieval_event_id=None,
        interruption_of_event_id=None,
        last_proposal_id=None,
        text=(
            "Quand la machine vibre après maintenance, je vérifie le rapport "
            "d'intervention et le CRM parce que le changement de rouleau explique "
            "souvent la dérive."
        ),
    )
    assert answer_step["intent"] == "answer_ready"
    assert answer_step["action_taken"] == "turn_appended"
    assert answer_step["session"]["metrics"]["answers_evaluated"] == 1

    correction_step = process_conversation_step(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        client_turn_id="conv-turn-2",
        question_id=question_id,
        retrieval_event_id=None,
        interruption_of_event_id=answer_step["system_prompt_event_id"],
        last_proposal_id=None,
        text="En fait je corrige, il faut surtout vérifier les basses fréquences du régime vibratoire.",
    )
    assert correction_step["intent"] == "correction"
    assert correction_step["turn"]["turn_kind"] == "correction"

    proposal_step = process_conversation_step(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        client_turn_id="conv-turn-3",
        question_id=question_id,
        retrieval_event_id=None,
        interruption_of_event_id=None,
        last_proposal_id=None,
        text="Crée la proposition de synthèse.",
    )
    assert proposal_step["intent"] == "proposal_requested"
    assert proposal_step["requires_confirmation"] is True
    proposal_id = proposal_step["proposal"]["id"]

    confirm_step = process_conversation_step(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        client_turn_id="conv-turn-4",
        question_id=question_id,
        retrieval_event_id=None,
        interruption_of_event_id=None,
        last_proposal_id=None,
        text="Oui je confirme.",
    )
    assert confirm_step["intent"] == "proposal_confirmed"
    assert confirm_step["proposal"]["status"] == "pending_review"
    assert confirm_step["proposal"]["id"] == proposal_id
    assert confirm_step["requires_confirmation"] is True
    assert confirm_step["confirmation_target"] == "acceptance"

    ambiguous_confirm_step = process_conversation_step(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        client_turn_id="conv-turn-4b",
        question_id=question_id,
        retrieval_event_id=None,
        interruption_of_event_id=None,
        last_proposal_id=None,
        text="Oui.",
    )
    assert ambiguous_confirm_step["intent"] == "proposal_confirmed"
    assert ambiguous_confirm_step["proposal"]["status"] == "pending_review"

    accept_step = process_conversation_step(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        client_turn_id="conv-turn-5",
        question_id=question_id,
        retrieval_event_id=None,
        interruption_of_event_id=None,
        last_proposal_id=None,
        text="Oui valide.",
    )
    assert accept_step["intent"] == "accept_confirmed"
    assert accept_step["proposal"]["status"] == "accepted"

    next_answer_step = process_conversation_step(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        client_turn_id="conv-turn-6",
        question_id=question_id,
        retrieval_event_id=None,
        interruption_of_event_id=None,
        last_proposal_id=proposal_id,
        text="Oui, pour la question suivante il faut vérifier les seuils de vibration avant recalage.",
    )
    assert next_answer_step["intent"] == "answer_ready"

    events = list_capture_events(db_session, workspace_id=workspace.id, session_id=session.id)
    intent_events = [event for event in events if event.event_type == "conversation_intent_detected"]
    assert [event.meta_data["intent"] for event in intent_events] == [
        "answer_ready",
        "correction",
        "proposal_requested",
        "proposal_confirmed",
        "proposal_confirmed",
        "accept_confirmed",
        "answer_ready",
    ]


def test_conversation_only_defers_empty_proposal_request(db_session):
    workspace = Workspace(id="ws-capture-empty-prop", name="Capture Empty Prop", slug="capture-empty-prop")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Empty proposal guard",
        objective="Capture tacit troubleshooting knowledge.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        **_guided_plan_kwargs(),
    )
    session = _approve(db_session, workspace, session)

    step = process_conversation_step(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        client_turn_id="conv-empty-prop-1",
        question_id=session.plan["questions"][0]["id"],
        retrieval_event_id=None,
        interruption_of_event_id=None,
        last_proposal_id=None,
        text="Crée la proposition.",
    )

    assert step["intent"] == "proposal_requested"
    assert step["action_taken"] == "proposal_deferred_insufficient_facts"
    assert step["proposal"] is None
    assert step["requires_confirmation"] is False
    assert "pas encore assez de matière" in step["next_prompt"]


def test_conversation_only_proposal_strips_voice_control_noise(db_session):
    workspace = Workspace(id="ws-capture-noise", name="Capture Noise", slug="capture-noise")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Noisy conversation capture",
        objective="Capture tacit troubleshooting knowledge.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        **_guided_plan_kwargs(),
    )
    question_id = session.plan["questions"][0]["id"]
    session = _approve(db_session, workspace, session)

    step = process_conversation_step(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        client_turn_id="conv-noise-1",
        question_id=question_id,
        retrieval_event_id=None,
        interruption_of_event_id=None,
        last_proposal_id=None,
        text=(
            "Attends, attends, je ne comprends pas ce que tu fais là. Arrête-toi. "
            "OK, donc euh pour la décision experte, ce qui est difficile à retrouver "
            "dans la documentation, c'est l'utilisation du régime vibratoire de la machine. "
            "Maintenant, je pense qu'on peut rajouter cette connaissance, on peut faire "
            "une proposition là-dessus."
        ),
    )

    assert step["intent"] == "proposal_requested"
    content = step["proposal"]["proposal"]["recommended_ingestion"]["content"]
    assert "régime vibratoire de la machine" in content
    assert "Attends" not in content
    assert "Arrête-toi" not in content
    assert "proposition là-dessus" not in content


@pytest.mark.asyncio
async def test_retrieval_prefetch_and_interruption_are_audited(db_session, monkeypatch):
    workspace = Workspace(id="ws-capture-rt", name="Capture RT", slug="capture-rt")
    context = Context(
        id="ctx-capture-rt",
        workspace_id=workspace.id,
        name="Demo collection",
        environment_state={"collection": "demo-knowledge"},
    )
    db_session.add_all([workspace, context])
    seed_skills_and_capabilities(db_session)

    seen_retrieval: dict = {}

    async def fake_retrieve_rag_context(request):
        seen_retrieval.update(request)
        return {
            "chunks": ["Le rapport CRM indique que la machine vibre après maintenance suite à un changement de rouleau."],
            "scores": [0.91],
            "metadatas": [{"title": "CRM maintenance", "source": "crm"}],
            "pipeline": "fast_scoped_dense",
            "label": "Planner bounded retrieval",
            "reason": "fake retrieval",
            "detail": "demo-knowledge:auto",
            "metrics": {
                "vector_db_type": "qdrant",
                "dense_policy": "fast_scoped_dense",
                "scope_confidence": 0.8,
            },
        }

    monkeypatch.setattr("app.services.rag.context.retrieve_rag_context", fake_retrieve_rag_context)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Realtime capture",
        objective="Capture live troubleshooting knowledge for vibration diagnosis.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=context.id,
        system_id=None,
        knowledge_refs=[],
        **_guided_plan_kwargs(),
    )

    prefetch = await prefetch_capture_retrieval(
        db_session,
        workspace_id=workspace.id,
        workspace_slug=workspace.slug,
        session_id=session.id,
        client_turn_id="turn-live-1",
        question_id=session.plan["questions"][0]["id"],
        partial_text="Quand la machine vibre après maintenance je vérifie le CRM et le rapport",
        top_k=4,
    )
    assert prefetch["status"] == "completed"
    assert prefetch["event_id"]
    assert prefetch["chunks"]
    assert prefetch["collection_name"] == "demo-knowledge"
    assert seen_retrieval["context_collection"] == "demo-knowledge"
    assert seen_retrieval["retrieval_profile"] == "oracle_fast"
    assert seen_retrieval["latency_profile"] == "fast"
    assert seen_retrieval["candidate_pool_k"] == 20
    assert prefetch["oracle_exact_match_count"] >= 1
    assert prefetch["oracle_exact_matches"][0]["backend"] == "sparse_exact"

    partial_event = next(
        event
        for event in list_capture_events(
            db_session,
            workspace_id=workspace.id,
            session_id=session.id,
        )
        if event.event_type == "stt_partial"
    )
    amend_capture_event(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        event_id=partial_event.id,
        text_amended=(
            "Quand la machine vibre, il faut considérer les basses fréquences "
            "absentes de la documentation."
        ),
        actor="operator@datategy.local",
        reason="Correction écrite de la captation live.",
    )

    event_only_proposal = create_update_proposal(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        complete_session=False,
    )
    assert "basses fréquences" in event_only_proposal.proposal["recommended_ingestion"]["content"]
    assert event_only_proposal.proposal["captured_facts"][0]["amended"] is True
    session = _approve(db_session, workspace, session)

    turn = append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        question_id=session.plan["questions"][0]["id"],
        text=(
            "Correction: quand la machine vibre après maintenance, je vérifie le CRM "
            "et le rapport parce que le changement de rouleau est souvent la cause."
        ),
        client_turn_id="turn-live-1",
        retrieval_event_id=prefetch["event_id"],
        interruption_of_event_id="prompt-event-1",
        turn_kind="correction",
        input_modality="voice",
    )
    # New non-blocking model: the expert drives, so no forced system prompt / advance.
    assert turn["system_prompt_event_id"] is None
    assert turn["next_prompt"] is None
    assert turn["next_question_id"] is None
    assert turn["suggestions"] == [] or all("kind" in s and "text" in s for s in turn["suggestions"])
    assert isinstance(turn["open_questions"], list)
    assert turn["turn"]["retrieval_refs"][0]["title"] == "CRM maintenance"
    assert turn["turn"]["turn_kind"] == "correction"

    events = list_capture_events(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
    )
    event_types = {event.event_type for event in events}
    assert "stt_partial" in event_types
    assert "retrieval_prefetch_completed" in event_types
    prefetch_event = next(event for event in events if event.event_type == "retrieval_prefetch_completed")
    assert prefetch_event.meta_data["oracle_exact_match_count"] >= 1
    assert prefetch_event.meta_data["oracle_exact_matches"][0]["backend"] == "sparse_exact"
    assert "stt_final" in event_types
    assert "ai_speech_interrupted" in event_types
    # The AI no longer prepares a forced next prompt — it listens without interrupting.
    assert "system_prompt_prepared" not in event_types

    later_events = list_capture_events(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        after_sequence=events[0].sequence,
    )
    assert len(later_events) == len(events) - 1

    proposal = create_update_proposal(db_session, workspace_id=workspace.id, session_id=session.id)
    fact = proposal.proposal["captured_facts"][0]
    assert fact["retrieval_event_id"] == prefetch["event_id"]
    assert fact["retrieval_refs"][0]["source"] == "crm"

    regenerated = create_update_proposal(db_session, workspace_id=workspace.id, session_id=session.id)
    assert regenerated.id == proposal.id
    assert regenerated.proposal["captured_facts"][0]["retrieval_event_id"] == prefetch["event_id"]

    business_events = list_capture_events(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        business_only=True,
    )
    assert business_events
    assert all(event.event_type not in {"stt_partial", "retrieval_prefetch_started"} for event in business_events)


@pytest.mark.asyncio
async def test_free_conversation_prefetch_weak_evidence_is_passive(db_session, monkeypatch):
    workspace = Workspace(id="ws-free-passive", name="Free Passive", slug="free-passive")
    context = Context(
        id="ctx-free-passive",
        workspace_id=workspace.id,
        name="Passive collection",
        environment_state={"collection": "passive-knowledge"},
    )
    db_session.add_all([workspace, context])
    seed_skills_and_capabilities(db_session)

    async def fake_retrieve_rag_context(_request):
        return {
            "chunks": ["Parent context: DCC parameter glossary and unrelated motor maintenance table."],
            "scores": [0.42],
            "metadatas": [
                {
                    "title": "Unrelated manual",
                    "source": "manual",
                    "retrieval_evidence_coverage": 0.05,
                    "retrieval_policy_score": 1,
                    "retrieval_exact_terms_matched": [],
                }
            ],
            "pipeline": "hybrid",
            "metrics": {"retrieval_profile": "oracle_fast"},
        }

    def fail_hints(*_args, **_kwargs):
        raise AssertionError("weak free-conversation retrieval must not push live hints")

    monkeypatch.setattr("app.services.rag.context.retrieve_rag_context", fake_retrieve_rag_context)
    monkeypatch.setattr("app.services.knowledge_capture.process_capture_partial_hints", fail_hints)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Capture libre",
        objective="Tester la capture sans plan.",
        expert_profile="Expert métier",
        duration_minutes=20,
        context_id=context.id,
        system_id=None,
        knowledge_refs=[],
        plan_mode="free_conversation",
    )

    prefetch = await prefetch_capture_retrieval(
        db_session,
        workspace_id=workspace.id,
        workspace_slug=workspace.slug,
        session_id=session.id,
        client_turn_id="turn-free-passive",
        question_id=None,
        partial_text="Donc je suis en mode robuste et je teste la latence de transcription.",
        top_k=4,
    )

    assert prefetch["status"] == "completed"
    assert prefetch["passive"] is True
    assert prefetch["passive_reason"] == "weak_evidence"
    assert prefetch["chunks"] == []
    assert prefetch["hints"] == []
    assert prefetch["active_section_confidence"] == 0.0

    events = list_capture_events(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
    )
    prefetch_event = next(event for event in events if event.event_type == "retrieval_prefetch_completed")
    assert prefetch_event.meta_data["passive"] is True
    assert prefetch_event.meta_data["passive_reason"] == "weak_evidence"
    assert prefetch_event.meta_data["chunks"], "audit keeps the raw retrieval evidence"


def test_oracle_detects_rpm_contradiction_and_hint():
    from app.services.capture_knowledge_oracle import (
        CaptureSessionContext,
        analyze_plan_oracle,
        detect_rpm_contradiction,
        evaluate_capture_partial,
        session_context_from_capture,
    )

    kb_chunks = ["La vitesse nominale des rouleaux est de 120/min selon le manuel BBA120."]
    contradiction = detect_rpm_contradiction("En cas X on monte à 180/min", kb_chunks)
    assert contradiction is not None
    assert "180" in contradiction["suggested_hint"]

    context = CaptureSessionContext(
        title="Capture rouleaux",
        objective="Capturer les réglages vitesse rouleaux BBA120",
        domain="technical",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        unlimited_duration=False,
        elapsed_minutes=None,
        workspace_id="ws-oracle",
        context_snapshot={"environment_state": {"collection": "andritz-manuals-bba120-pilot"}},
        dialogue_turns=[{"text": "Réglages ligne et vitesse rouleaux 180/min en cas exceptionnel"}],
        active_subtopic_id="st-01",
        recent_transcript=[],
    )
    oracle = analyze_plan_oracle(
        context,
        rag_chunks=kb_chunks,
        rag_metadatas=[{"title": "Manuel BBA120", "source": "manual-bba120"}],
        base_gaps=[],
    )
    assert oracle["topic_proposals"]
    assert oracle["topic_proposals"][0]["title"] == "Réglages ligne"
    assert oracle["topic_proposals"][0]["kb_refs"]
    assert oracle["dialogue_probe"]
    assert oracle["oracle_exact_matches"]
    assert oracle["contradiction_candidates"][0]["exact_match_backend"] == "sparse_exact"
    assert oracle["contradiction_candidates"][0]["oracle_exact_matches"][0]["backend"] == "sparse_exact"

    live = evaluate_capture_partial(
        context,
        "En cas X on monte à 180/min pour stabiliser la ligne",
        kb_chunks,
        plan_topics=oracle["topic_proposals"],
    )
    assert live["hints"]
    assert live["hints"][0]["priority"] == 100
    assert "180" in live["hints"][0]["hint"]
    assert live["oracle_exact_matches"]
    assert live["contradiction_candidates"][0]["exact_match_backend"] == "sparse_exact"
    assert live["hints"][0]["oracle_exact_matches"][0]["backend"] == "sparse_exact"


def test_plan_oracle_outline_strictly_grounded_in_expert_statements():
    """The fallback outline must contain only the subjects the expert expressed and
    must NOT invent complementary topics (e.g. a test-protocol section)."""
    from app.services.capture_knowledge_oracle import (
        CaptureSessionContext,
        analyze_plan_oracle,
    )

    context = CaptureSessionContext(
        title="Cadrage ligne",
        objective="Capture ligne de production",
        domain="technical",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        unlimited_duration=False,
        elapsed_minutes=None,
        workspace_id="ws-oracle-grounded",
        context_snapshot={},
        dialogue_turns=[{"text": "on va décrire la ligne de production, et ensuite ses limitations."}],
        active_subtopic_id=None,
        recent_transcript=[],
    )
    oracle = analyze_plan_oracle(
        context,
        rag_chunks=["Document mentionnant un protocole d'essais et des résultats."],
        rag_metadatas=[{"title": "Manuel", "source": "manual"}],
        base_gaps=[
            {"slug": "test_protocol", "title": "Protocole d'essais", "description": "Essais et résultats"}
        ],
    )
    titles = [topic["title"] for topic in oracle["topic_proposals"]]
    assert titles == ["Ligne de production", "Limitations"]
    blob = " ".join(titles + [
        sub.get("title", "")
        for topic in oracle["topic_proposals"]
        for sub in topic.get("subtopics") or []
    ]).lower()
    assert "essais" not in blob
    assert "protocole" not in blob
    assert "résultat" not in blob and "resultat" not in blob


def test_plan_oracle_outline_grows_as_expert_adds_subjects():
    """Constraint is 'nothing beyond what was expressed', not 'frozen after turn 1':
    when the expert adds a subject, the outline grows accordingly."""
    from app.services.capture_knowledge_oracle import (
        CaptureSessionContext,
        analyze_plan_oracle,
    )

    def _context(turns):
        return CaptureSessionContext(
            title="Cadrage",
            objective="Capture",
            domain="technical",
            expert_profile="Expert",
            duration_minutes=20,
            unlimited_duration=False,
            elapsed_minutes=None,
            workspace_id="ws-oracle-grow",
            context_snapshot={},
            dialogue_turns=turns,
            active_subtopic_id=None,
            recent_transcript=[],
        )

    first = analyze_plan_oracle(_context([{"text": "la ligne de production et ses limitations"}]))
    assert [t["title"] for t in first["topic_proposals"]] == ["Ligne de production", "Limitations"]

    grown = analyze_plan_oracle(
        _context(
            [
                {"text": "la ligne de production et ses limitations"},
                {"text": "ensuite la maintenance préventive"},
            ]
        )
    )
    grown_titles = [t["title"] for t in grown["topic_proposals"]]
    assert "Ligne de production" in grown_titles
    assert "Limitations" in grown_titles
    assert "Maintenance préventive" in grown_titles
    assert len(grown_titles) == 3


def test_outline_traversal_opens_with_broad_topic_prompt_before_subtopics():
    """A topic-with-subtopics must open with its broad, topic-level presentation
    prompt BEFORE any subtopic prompt; advancement then descends into subtopics."""
    from app.services.knowledge_capture import _flatten_plan_questions, _next_plan_question

    plan = {
        "topics": [
            {
                "id": "t-01",
                "title": "Ligne de production",
                "prompt": "Présentez globalement ce que vous savez de « Ligne de production ».",
                "subtopics": [
                    {
                        "id": "st-01",
                        "title": "Vitesse de production",
                        "prompt": "Présentez ce que vous savez du point « Vitesse de production ».",
                    },
                    {"id": "st-02", "title": "Limitations"},
                ],
            },
            {"id": "t-02", "title": "Maintenance", "subtopics": [{"id": "st-03", "title": "Préventif"}]},
        ]
    }

    flat = _flatten_plan_questions(plan)
    # First emitted item for the topic is the broad topic-level prompt (no subtopic).
    assert flat[0]["level"] == "topic"
    assert flat[0]["topic_id"] == "t-01"
    assert flat[0]["subtopic_id"] is None
    assert flat[0]["prompt"] == "Présentez globalement ce que vous savez de « Ligne de production »."
    # It precedes every subtopic of that topic.
    first_subtopic_index = next(i for i, q in enumerate(flat) if q.get("subtopic_id") == "st-01")
    assert first_subtopic_index > 0
    assert flat[1]["subtopic_id"] == "st-01"
    assert flat[2]["subtopic_id"] == "st-02"
    # Each top-level topic opens broad: the second topic also leads with its overview.
    t2_overview = next(q for q in flat if q.get("topic_id") == "t-02")
    assert t2_overview["level"] == "topic"
    # A topic without an explicit prompt gets a synthesized broad prompt.
    assert flat[flat.index(t2_overview)]["prompt"].startswith("Présentez globalement ce que vous savez de « Maintenance »")

    # Opening point is the broad topic entry; once answered, advance to first subtopic.
    opening = _next_plan_question(plan, [])
    assert opening["prompt"] == "Présentez globalement ce que vous savez de « Ligne de production »."
    after_overview = _next_plan_question(plan, [{"question_id": "t-01-overview", "verdict": "sufficient"}])
    assert after_overview["subtopic_id"] == "st-01"


def test_capture_turn_is_non_blocking_and_exposes_sorted_open_questions(db_session):
    """New model: the plan stops driving the session. A turn never forces an answer
    or auto-advances; relance is surfaced only as optional, non-blocking suggestions,
    and the oracle exposes its OWN open_questions sorted by priority desc."""
    workspace = Workspace(id="ws-capture-nonblock", name="Capture NonBlock", slug="capture-nonblock")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Capture libre experte",
        objective="Capturer les décisions terrain sur la ligne de production.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        **_guided_plan_kwargs(),
    )
    session = _approve(db_session, workspace, session)

    result = append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        question_id=session.plan["questions"][0]["id"],
        text=(
            "Sur la ligne, je règle d'abord la vitesse selon le grade de papier, "
            "puis je surveille la température et la vibration avant de valider."
        ),
    )

    # The expert drives: nothing forces an answer or auto-advances the outline.
    assert result["next_prompt"] is None
    assert result["next_question_id"] is None
    assert result["system_prompt_event_id"] is None

    # Relance kept for backward compat, but only delivered as optional suggestions.
    assert isinstance(result["relance"], dict)
    for suggestion in result["suggestions"]:
        assert set(suggestion.keys()) == {"kind", "text"}
        assert suggestion["text"]

    # The oracle exposes its OWN open questions, sorted by priority descending.
    open_questions = result["open_questions"]
    assert open_questions
    for item in open_questions:
        assert set(item.keys()) == {"id", "text", "topic_id", "priority", "status"}
        assert item["status"] in {"open", "addressed"}
    priorities = [item["priority"] for item in open_questions]
    assert priorities == sorted(priorities, reverse=True)

    # A detected contradiction is surfaced as the highest-priority open question.
    reloaded = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    with_contradiction = build_open_questions(
        reloaded,
        contradiction_candidates=[
            {"suggested_hint": "Dans quel cas précis viser 180/min au lieu de 160/min ?"}
        ],
    )
    assert with_contradiction[0]["priority"] == 2.0
    assert "180/min" in with_contradiction[0]["text"]


@pytest.mark.asyncio
async def test_voice_gateway_barge_in_is_audited_and_metriced(db_session):
    from app.services import voice_session_gateway as gw

    workspace = Workspace(id="ws-gw-barge", name="GW Barge", slug="gw-barge")
    user = User(id="user-gw-barge", username="barge@datategy.local", email="barge@datategy.local")
    db_session.add_all([workspace, user])

    sent: list[tuple] = []

    class FakeWebSocket:
        async def send_json(self, message):
            sent.append((message.get("type"), message.get("payload")))

    gateway = gw.VoiceSessionGateway()
    state = gw.VoiceSessionState(session_id="capture-barge", transport="livekit")
    state.client_turn_id = "turn-before-barge"
    state.interruption_of_event_id = "prompt-before-barge"
    state.last_partial_text = "ancien partiel"
    state.last_partial_chunk_count = 3
    state.partial_stt_in_flight = True

    await gateway._handle_event(
        FakeWebSocket(),
        db_session,
        user=user,
        workspace=workspace,
        state=state,
        event={
            "type": "barge_in",
            "payload": {
                "turn_id": "turn-barge",
                "prompt_event_id": "prompt-livekit-1",
                "source": "livekit_control",
            },
        },
    )

    assert state.last_partial_text == ""
    assert state.last_partial_chunk_count == 0
    assert state.partial_stt_in_flight is False
    assert [event_type for event_type, _ in sent] == ["runtime.metric", "barge_in"]
    assert sent[0][1]["metric"] == "barge_in"
    assert sent[0][1]["transport"] == "livekit"
    assert sent[0][1]["turn_id"] == "turn-barge"
    assert sent[0][1]["prompt_event_id"] == "prompt-livekit-1"
    assert sent[1][1]["status"] == "accepted"

    audit = db_session.query(AuditLog).filter_by(event_type="voice.barge_in").one()
    assert audit.workspace_id == workspace.id
    assert audit.actor == "barge@datategy.local"
    assert audit.details["session_id"] == "capture-barge"
    assert audit.details["transport"] == "livekit"
    assert audit.details["prompt_event_id"] == "prompt-livekit-1"


@pytest.mark.asyncio
async def test_voice_gateway_client_metric_is_sanitized_and_reemitted(db_session):
    from app.services import voice_session_gateway as gw

    workspace = Workspace(id="ws-gw-client-metric", name="GW Client Metric", slug="gw-client-metric")
    user = User(id="user-gw-client-metric", username="metric@datategy.local", email="metric@datategy.local")
    db_session.add_all([workspace, user])

    sent: list[tuple] = []

    class FakeWebSocket:
        async def send_json(self, message):
            sent.append((message.get("type"), message.get("payload")))

    gateway = gw.VoiceSessionGateway()
    state = gw.VoiceSessionState(session_id="capture-client-metric", transport="backend_ws")
    state.client_turn_id = "turn-client-metric"

    await gateway._handle_event(
        FakeWebSocket(),
        db_session,
        user=user,
        workspace=workspace,
        state=state,
        event={"type": "client.metric", "payload": {"metric": "unknown_metric", "value_ms": 12}},
    )
    assert sent == []

    await gateway._handle_event(
        FakeWebSocket(),
        db_session,
        user=user,
        workspace=workspace,
        state=state,
        event={
            "type": "client.metric",
            "payload": {
                "metric": "endpoint_candidate",
                "capture_mode": "robust",
                "endpoint_reason": "silence",
                "value_ms": 650,
                "threshold": 0.012,
                "rms": 0.004,
                "unexpected_large": "x" * 500,
            },
        },
    )

    assert [event_type for event_type, _ in sent] == ["runtime.metric"]
    payload = sent[0][1]
    assert payload["metric"] == "endpoint_candidate"
    assert payload["source"] == "client_capture"
    assert payload["turn_id"] == "turn-client-metric"
    assert payload["capture_mode"] == "robust"
    assert payload["endpoint_reason"] == "silence"
    assert payload["threshold"] == 0.012
    assert "unexpected_large" not in payload

    audit = db_session.query(AuditLog).filter_by(event_type="voice.client_metric").one()
    assert audit.workspace_id == workspace.id
    assert audit.details["session_id"] == "capture-client-metric"
    assert audit.details["source"] == "client_capture"


@pytest.mark.asyncio
async def test_voice_gateway_client_metric_burst_is_throttled(db_session, monkeypatch):
    from app.services import voice_session_gateway as gw

    workspace = Workspace(id="ws-gw-client-metric-burst", name="GW Client Metric Burst", slug="gw-client-metric-burst")
    user = User(
        id="user-gw-client-metric-burst",
        username="metric-burst@datategy.local",
        email="metric-burst@datategy.local",
    )
    db_session.add_all([workspace, user])

    sent: list[tuple] = []

    class FakeWebSocket:
        async def send_json(self, message):
            sent.append((message.get("type"), message.get("payload")))

    gateway = gw.VoiceSessionGateway()
    state = gw.VoiceSessionState(session_id="capture-client-metric-burst", transport="backend_ws")
    state.client_turn_id = "turn-client-metric-burst"
    clock = {"now": 100.0}
    monkeypatch.setattr(gw.time, "perf_counter", lambda: clock["now"])

    for index in range(8):
        await gateway._handle_event(
            FakeWebSocket(),
            db_session,
            user=user,
            workspace=workspace,
            state=state,
            event={
                "type": "client.metric",
                "payload": {
                    "metric": "chunk_gap_ms",
                    "chunk_gap_ms": 40 + index,
                    "capture_mode": "robust",
                },
            },
        )
        clock["now"] += gw._CLIENT_METRIC_MIN_INTERVAL_S / 10

    forwarded = [payload for event_type, payload in sent if event_type == "runtime.metric"]
    assert len(forwarded) == 1
    assert forwarded[0]["metric"] == "chunk_gap_ms"
    assert forwarded[0]["chunk_gap_ms"] == 40

    clock["now"] += gw._CLIENT_METRIC_MIN_INTERVAL_S
    await gateway._handle_event(
        FakeWebSocket(),
        db_session,
        user=user,
        workspace=workspace,
        state=state,
        event={
            "type": "client.metric",
            "payload": {
                "metric": "chunk_gap_ms",
                "chunk_gap_ms": 120,
                "capture_mode": "robust",
            },
        },
    )

    forwarded = [payload for event_type, payload in sent if event_type == "runtime.metric"]
    assert len(forwarded) == 2
    assert forwarded[1]["chunk_gap_ms"] == 120
    audits = (
        db_session.query(AuditLog)
        .filter_by(event_type="voice.client_metric", workspace_id=workspace.id)
        .order_by(AuditLog.timestamp.asc())
        .all()
    )
    assert len(audits) == 2
    assert [audit.details["chunk_gap_ms"] for audit in audits] == [40, 120]


@pytest.mark.asyncio
async def test_gateway_streams_partials_and_oracle_before_endpoint(db_session, monkeypatch):
    """Server-side incremental transcription: several audio.frame messages must emit
    live transcript.partial + oracle analysis BEFORE any audio.endpoint, while
    transcript.improved / text.final / fact-extraction happen only at the endpoint."""
    from app.services import voice_session_gateway as gw

    workspace = Workspace(id="ws-gw-live", name="GW Live", slug="gw-live")
    user = User(id="user-gw-live", username="gw@datategy.local", email="gw@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Live capture",
        objective="Capturer les réglages de vitesse sur la ligne.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        **_guided_plan_kwargs(),
    )
    session = _approve(db_session, workspace, session)
    session = start_session(db_session, workspace_id=workspace.id, session_id=session.id)
    question_id = session.plan["questions"][0]["id"]

    class FakeProvider:
        def __init__(self) -> None:
            self.transcribe_calls = 0

        async def transcribe(self, audio_bytes, *, filename=None, content_type=None, language=None):
            self.transcribe_calls += 1
            return {
                "text": f"je règle la vitesse selon le grade de papier numéro {self.transcribe_calls}",
                "provider": "fake",
                "model": "fake-stt",
            }

    fake_provider = FakeProvider()
    monkeypatch.setattr(gw, "get_voice_runtime_provider", lambda *a, **k: fake_provider)
    # Keep the live retrieval deterministic (no real vector store in unit tests).
    monkeypatch.setattr(gw, "_retrieve_context_chunks", lambda *a, **k: ([], [], []))
    # Remove the real-time cadence so each frame triggers an incremental partial.
    monkeypatch.setattr(gw, "_PARTIAL_STT_MIN_INTERVAL_MS", 0)

    sent: list[tuple] = []

    class FakeWebSocket:
        async def send_json(self, message):
            sent.append((message.get("type"), message.get("payload")))

    websocket = FakeWebSocket()
    gateway = gw.VoiceSessionGateway()
    state = gw.VoiceSessionState(session_id=session.id, mode="guided", tandem_oracle_enabled=True)
    state.oracle = gw.VoiceTandemOracle(min_interval_ms=0, min_delta_chars=0)

    frame_payload = {
        "bytes_b64": base64.b64encode(_WEBM_HEADER_CHUNK).decode(),
        "turn_id": "seg-live-1",
        "question_id": question_id,
        "content_type": "audio/webm",
    }
    for _ in range(3):
        await gateway._handle_event(
            websocket,
            db_session,
            user=user,
            workspace=workspace,
            state=state,
            event={"type": "audio.frame", "payload": frame_payload},
        )
        # The incremental STT is offloaded (fire-and-forget) so the receive loop
        # never blocks on it; drain it here to keep the per-frame assertions.
        await asyncio.gather(*list(state.partial_stt_tasks))

    types_before = [t for t, _ in sent]
    # Live partial transcription + oracle analysis happened mid-utterance.
    assert fake_provider.transcribe_calls >= 2
    assert types_before.count("transcript.partial") >= 2
    assert any(t == "oracle.delta" for t in types_before)
    partial_texts = [p.get("text") for t, p in sent if t == "transcript.partial"]
    assert all("numéro" in (text or "") for text in partial_texts)
    assert all(p.get("segment_id") == "seg-live-1" for t, p in sent if t == "transcript.partial")
    # The final stage must NOT have run yet (and transcript.improved is gone for good).
    assert "transcript.improved" not in types_before
    assert "text.final" not in types_before
    reloaded = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    assert not [turn for turn in (reloaded.transcript or []) if turn.get("speaker") == "expert"]

    # Natural pause: the authoritative segment end must REUSE the last full-buffer
    # partial (no new audio arrived since), so it does NOT spend another STT call.
    calls_before_endpoint = fake_provider.transcribe_calls
    await gateway._handle_event(
        websocket,
        db_session,
        user=user,
        workspace=workspace,
        state=state,
        event={"type": "audio.endpoint", "payload": {"turn_id": "seg-live-1"}},
    )

    types_after = [t for t, _ in sent]
    # TASK 1: the endpoint reused the latest partial instead of re-transcribing the
    # whole buffer — one redundant round-trip saved.
    assert fake_provider.transcribe_calls == calls_before_endpoint
    # text.final ships; the reframed transcript.improved stage stays removed.
    assert "text.final" in types_after
    assert "transcript.improved" not in types_after
    final = next(p for t, p in sent if t == "text.final")
    assert final.get("reframed") is False
    assert final.get("endpoint_stt_source") == "reused_partial"
    # TASK 2: the committed live text stays RAW (no glossary substitution live); it is
    # exactly the latest partial text.
    last_partial = [p.get("text") for t, p in sent if t == "transcript.partial"][-1]
    assert final.get("text") == last_partial
    endpoint_metric = next(p for t, p in sent if t == "runtime.metric" and p.get("metric") == "endpoint_stt")
    assert endpoint_metric["source"] == "reused_partial"
    # B2: no content relance / next prompt / proposal during capture (timeline only).
    assert "prompt.next" not in types_after
    assert "conversation.step" not in types_after
    # The turn is still persisted SILENTLY so the FINAL phase has the content.
    reloaded = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    assert [turn for turn in (reloaded.transcript or []) if turn.get("speaker") == "expert"]
    # The incremental path never cleared/corrupted the buffer used at endpoint.
    assert state.audio_chunks == []
    assert state.partial_stt_in_flight is False
    assert state.last_partial_text == ""


@pytest.mark.asyncio
async def test_gateway_metrics_empty_incremental_stt(db_session, monkeypatch):
    from app.services import voice_session_gateway as gw

    workspace = Workspace(id="ws-gw-empty-partial", name="GW Empty Partial", slug="gw-empty-partial")
    user = User(id="user-gw-empty-partial", username="empty@datategy.local", email="empty@datategy.local")
    db_session.add_all([workspace, user])

    class FakeProvider:
        async def transcribe(self, audio_bytes, *, filename=None, content_type=None, language=None):
            return {"text": "", "provider": "fake", "model": "fake-stt"}

    monkeypatch.setattr(gw, "get_voice_runtime_provider", lambda *a, **k: FakeProvider())
    monkeypatch.setattr(gw, "_PARTIAL_STT_MIN_INTERVAL_MS", 0)

    sent: list[tuple] = []

    class FakeWebSocket:
        async def send_json(self, message):
            sent.append((message.get("type"), message.get("payload")))

    websocket = FakeWebSocket()
    gateway = gw.VoiceSessionGateway()
    state = gw.VoiceSessionState(session_id="capture-empty-partial", tandem_oracle_enabled=False)

    await gateway._handle_event(
        websocket,
        db_session,
        user=user,
        workspace=workspace,
        state=state,
        event={
            "type": "audio.frame",
            "payload": {
                "bytes_b64": base64.b64encode(_WEBM_HEADER_CHUNK).decode(),
                "turn_id": "seg-empty-partial",
                "content_type": "audio/webm",
            },
        },
    )
    await asyncio.gather(*list(state.partial_stt_tasks))

    assert "transcript.partial" not in [event_type for event_type, _ in sent]
    partial_metric = next(
        payload
        for event_type, payload in sent
        if event_type == "runtime.metric" and payload.get("metric") == "partial_stt"
    )
    assert partial_metric["status"] == "empty"
    assert partial_metric["reason"] == "empty_text"
    assert partial_metric["turn_id"] == "seg-empty-partial"
    assert partial_metric["text_len"] == 0
    assert state.partial_stt_in_flight is False


@pytest.mark.asyncio
async def test_gateway_endpoint_stt_metric_excludes_capture_duration(db_session, monkeypatch):
    from app.services import voice_session_gateway as gw

    workspace = Workspace(id="ws-gw-stt-metric", name="GW STT Metric", slug="gw-stt-metric")
    user = User(id="user-gw-stt-metric", username="metric@datategy.local", email="metric@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="STT metric",
        objective="Mesurer la latence endpoint STT.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        **_guided_plan_kwargs(),
    )
    session = _approve(db_session, workspace, session)
    session = start_session(db_session, workspace_id=workspace.id, session_id=session.id)

    class FakeProvider:
        async def transcribe(self, audio_bytes, *, filename=None, content_type=None, language=None):
            await asyncio.sleep(0.02)
            return {
                "text": "la transcription finale arrive apres l endpoint",
                "provider": "fake",
                "model": "fake-stt",
            }

    monkeypatch.setattr(gw, "get_voice_runtime_provider", lambda *a, **k: FakeProvider())

    sent: list[tuple] = []

    class FakeWebSocket:
        async def send_json(self, message):
            sent.append((message.get("type"), message.get("payload")))

    gateway = gw.VoiceSessionGateway()
    state = gw.VoiceSessionState(session_id=session.id, tandem_oracle_enabled=False, live_partial_stt_enabled=False)

    await gateway._handle_event(
        FakeWebSocket(),
        db_session,
        user=user,
        workspace=workspace,
        state=state,
        event={
            "type": "audio.frame",
            "payload": {
                "bytes_b64": base64.b64encode(_WEBM_HEADER_CHUNK).decode(),
                "turn_id": "seg-metric-1",
                "content_type": "audio/webm",
                "incremental_transcription": False,
            },
        },
    )
    assert state.turn_started_at is not None
    state.turn_started_at -= 5.0

    await gateway._handle_event(
        FakeWebSocket(),
        db_session,
        user=user,
        workspace=workspace,
        state=state,
        event={
            "type": "audio.endpoint.auto",
            "payload": {
                "turn_id": "seg-metric-1",
                "reason": "silence",
                "capture_mode": "robust",
                "silence_ms": 2200,
                "min_speech_ms": 700,
                "endpoint_grace_ms": 650,
                "rms_threshold": 0.012,
            },
        },
    )

    final = next(p for t, p in sent if t == "text.final")
    assert final["endpoint_stt_source"] == "provider"
    assert final["turn_audio_capture_ms"] >= 4900
    assert final["endpoint_stt_ms"] < final["text_final_total_ms"]
    assert final["endpoint_reason"] == "silence"
    assert final["capture_mode"] == "robust"

    endpoint_metric = next(p for t, p in sent if t == "runtime.metric" and p.get("metric") == "endpoint_stt")
    assert endpoint_metric["value_ms"] == final["endpoint_stt_ms"]
    assert endpoint_metric["turn_audio_capture_ms"] == final["turn_audio_capture_ms"]
    assert endpoint_metric["endpoint_reason"] == "silence"
    assert endpoint_metric["capture_mode"] == "robust"

    reloaded = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    turn = next(item for item in reloaded.transcript or [] if item.get("client_turn_id") == "seg-metric-1")
    latency = turn["latency_ms"]
    assert latency["endpoint_stt_source"] == "provider"
    assert latency["endpoint_stt_ms"] == final["endpoint_stt_ms"]
    assert latency["turn_audio_capture_ms"] == final["turn_audio_capture_ms"]
    assert latency["endpoint_reason"] == "silence"
    assert latency["capture_mode"] == "robust"
    assert latency["silence_ms"] == 2200
    assert latency["endpoint_grace_ms"] == 650
    assert latency["rms_threshold"] == 0.012
    assert reloaded.metrics["voice_stream"]["last_latency_ms"]["endpoint_stt_ms"] == final["endpoint_stt_ms"]


@pytest.mark.asyncio
async def test_gateway_live_questions_are_after_text_final_and_grounded(db_session, monkeypatch):
    from app.services import voice_session_gateway as gw

    workspace = Workspace(id="ws-gw-live-q", name="GW Live Questions", slug="gw-live-q")
    user = User(id="user-gw-live-q", username="liveq@datategy.local", email="liveq@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Questions live",
        objective="Verifier que les questions sont asynchrones.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        **_guided_plan_kwargs(),
    )
    session = _approve(db_session, workspace, session)
    session = start_session(db_session, workspace_id=workspace.id, session_id=session.id)

    class FakeProvider:
        async def transcribe(self, audio_bytes, *, filename=None, content_type=None, language=None):
            return {
                "text": "la vitesse est reglee selon le grade papier et la temperature machine",
                "provider": "fake",
                "model": "fake-stt",
            }

    async def fake_retrieve(*_args, **_kwargs):
        return (
            ["Le manuel indique une correction de vitesse selon le grade papier."],
            [{"title": "Manuel SPL", "document_id": "doc-spl"}],
            [0.93],
        )

    async def fake_questions(*_args, **_kwargs):
        await asyncio.sleep(0.01)
        return [{"text": "Quelle correction appliquez-vous quand la temperature depasse le seuil ?", "priority": 0.9}]

    monkeypatch.setattr(gw, "get_voice_runtime_provider", lambda *a, **k: FakeProvider())
    monkeypatch.setattr(gw, "_retrieve_context_chunks_async", fake_retrieve)
    monkeypatch.setattr(
        "app.services.capture_knowledge_oracle.generate_grounded_open_questions_async",
        fake_questions,
    )

    sent: list[tuple] = []

    class FakeWebSocket:
        async def send_json(self, message):
            sent.append((message.get("type"), message.get("payload")))

    websocket = FakeWebSocket()
    gateway = gw.VoiceSessionGateway()
    state = gw.VoiceSessionState(
        session_id=session.id,
        mode="guided",
        tandem_oracle_enabled=True,
        live_partial_stt_enabled=False,
        live_questions_enabled=True,
    )
    state.oracle = gw.VoiceTandemOracle(min_interval_ms=0, min_delta_chars=0)

    await gateway._handle_event(
        websocket,
        db_session,
        user=user,
        workspace=workspace,
        state=state,
        event={
            "type": "audio.frame",
            "payload": {
                "bytes_b64": base64.b64encode(_WEBM_HEADER_CHUNK).decode(),
                "turn_id": "seg-live-q-1",
                "content_type": "audio/webm",
                "incremental_transcription": False,
            },
        },
    )
    await gateway._handle_event(
        websocket,
        db_session,
        user=user,
        workspace=workspace,
        state=state,
        event={"type": "audio.endpoint", "payload": {"turn_id": "seg-live-q-1"}},
    )

    types_before_questions = [t for t, _ in sent]
    assert "text.final" in types_before_questions
    assert "oracle.questions" not in types_before_questions

    await asyncio.gather(*list(state.live_questions_tasks))

    types = [t for t, _ in sent]
    assert types.index("text.final") < types.index("oracle.questions")
    questions_payload = next(p for t, p in sent if t == "oracle.questions")
    question = questions_payload["open_questions"][0]
    assert question["grounding_status"] == "kb_grounded"
    assert question["source"] == "oracle_live"


@pytest.mark.asyncio
async def test_gateway_live_questions_retrieval_timeout_emits_no_grounded_questions(db_session, monkeypatch):
    from app.services import voice_session_gateway as gw

    workspace = Workspace(id="ws-gw-live-q-timeout", name="GW Live Questions Timeout", slug="gw-live-q-timeout")
    user = User(id="user-gw-live-q-timeout", username="liveqt@datategy.local", email="liveqt@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Questions live timeout",
        objective="Verifier que le grounding manquant reste silencieux.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        **_guided_plan_kwargs(),
    )
    session = _approve(db_session, workspace, session)
    session = start_session(db_session, workspace_id=workspace.id, session_id=session.id)

    class FakeProvider:
        async def transcribe(self, audio_bytes, *, filename=None, content_type=None, language=None):
            return {
                "text": "la machine suit une procedure mais sans source retrouvee",
                "provider": "fake",
                "model": "fake-stt",
            }

    async def fake_retrieve_timeout(*_args, **_kwargs):
        return ([], [], [])

    async def fail_questions(*_args, **_kwargs):
        raise AssertionError("questions must not run without retrieval chunks")

    monkeypatch.setattr(gw, "get_voice_runtime_provider", lambda *a, **k: FakeProvider())
    monkeypatch.setattr(gw, "_retrieve_context_chunks_async", fake_retrieve_timeout)
    monkeypatch.setattr(
        "app.services.capture_knowledge_oracle.generate_grounded_open_questions_async",
        fail_questions,
    )

    sent: list[tuple] = []

    class FakeWebSocket:
        async def send_json(self, message):
            sent.append((message.get("type"), message.get("payload")))

    websocket = FakeWebSocket()
    gateway = gw.VoiceSessionGateway()
    state = gw.VoiceSessionState(
        session_id=session.id,
        mode="guided",
        tandem_oracle_enabled=True,
        live_partial_stt_enabled=False,
        live_questions_enabled=True,
    )

    await gateway._handle_event(
        websocket,
        db_session,
        user=user,
        workspace=workspace,
        state=state,
        event={
            "type": "audio.frame",
            "payload": {
                "bytes_b64": base64.b64encode(_WEBM_HEADER_CHUNK).decode(),
                "turn_id": "seg-live-q-timeout-1",
                "content_type": "audio/webm",
                "incremental_transcription": False,
            },
        },
    )
    await gateway._handle_event(
        websocket,
        db_session,
        user=user,
        workspace=workspace,
        state=state,
        event={"type": "audio.endpoint", "payload": {"turn_id": "seg-live-q-timeout-1"}},
    )
    await asyncio.gather(*list(state.live_questions_tasks))

    assert any(t == "text.final" for t, _ in sent)
    assert not any(t == "oracle.questions" for t, _ in sent)
    assert state.live_questions_in_flight is False


@pytest.mark.asyncio
async def test_gateway_pause_flushes_segment_like_endpoint(db_session, monkeypatch):
    """audio.pause = segment flush: a pause with buffered audio finalizes the
    in-flight segment exactly like an endpoint (text.final emitted, turn
    persisted, buffer cleared, partial state reset) but with no relance /
    conversation.step / TTS. A pause with an empty buffer stays silent (ack
    only, never an empty_audio error) so a resume starts a genuinely fresh
    turn under the frontend's new turn id."""
    from app.services import voice_session_gateway as gw

    workspace = Workspace(id="ws-gw-pause", name="GW Pause", slug="gw-pause")
    user = User(id="user-gw-pause", username="gwp@datategy.local", email="gwp@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Pause flush",
        objective="Capturer les réglages de vitesse sur la ligne.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        **_guided_plan_kwargs(),
    )
    session = _approve(db_session, workspace, session)
    session = start_session(db_session, workspace_id=workspace.id, session_id=session.id)

    class FakeProvider:
        def __init__(self) -> None:
            self.transcribe_calls = 0

        async def transcribe(self, audio_bytes, *, filename=None, content_type=None, language=None):
            self.transcribe_calls += 1
            return {
                "text": "le segment se termine quand l'expert met la capture en pause",
                "provider": "fake",
                "model": "fake-stt",
            }

    fake_provider = FakeProvider()
    monkeypatch.setattr(gw, "get_voice_runtime_provider", lambda *a, **k: fake_provider)
    monkeypatch.setattr(gw, "_retrieve_context_chunks", lambda *a, **k: ([], [], []))
    monkeypatch.setattr(gw, "_PARTIAL_STT_MIN_INTERVAL_MS", 0)

    sent: list[tuple] = []

    class FakeWebSocket:
        async def send_json(self, message):
            sent.append((message.get("type"), message.get("payload")))

    websocket = FakeWebSocket()
    gateway = gw.VoiceSessionGateway()
    state = gw.VoiceSessionState(session_id=session.id, mode="guided", tandem_oracle_enabled=True)
    state.oracle = gw.VoiceTandemOracle(min_interval_ms=0, min_delta_chars=0)

    frame_payload = {
        "bytes_b64": base64.b64encode(_WEBM_HEADER_CHUNK).decode(),
        "turn_id": "seg-pause-1",
        "content_type": "audio/webm",
    }
    for _ in range(2):
        await gateway._handle_event(
            websocket,
            db_session,
            user=user,
            workspace=workspace,
            state=state,
            event={"type": "audio.frame", "payload": frame_payload},
        )
        await asyncio.gather(*list(state.partial_stt_tasks))

    await gateway._handle_event(
        websocket,
        db_session,
        user=user,
        workspace=workspace,
        state=state,
        event={"type": "audio.pause", "payload": {"turn_id": "seg-pause-1"}},
    )

    types = [t for t, _ in sent]
    # The pause is always acked AND flushes the segment like an endpoint.
    assert "audio.pause" in types
    assert "text.final" in types
    final = next(p for t, p in sent if t == "text.final")
    assert final.get("turn_id") == "seg-pause-1"
    assert final.get("empty") is False
    # No relance / conversation step / TTS on the pause path.
    assert "conversation.step" not in types
    assert "prompt.next" not in types
    assert "audio.out" not in types
    # The turn is persisted via the same append_turn path as the endpoint.
    reloaded = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    assert [turn for turn in (reloaded.transcript or []) if turn.get("speaker") == "expert"]
    # Buffer flushed + partial state reset: the next resume starts a fresh turn.
    assert state.audio_chunks == []
    assert state.client_turn_id is None
    assert state.partial_stt_in_flight is False
    assert state.last_partial_text == ""

    # Second pause with an EMPTY buffer: ack only — no empty_audio error, no
    # extra text.final (silent pause is normal and must stay observable).
    sent.clear()
    await gateway._handle_event(
        websocket,
        db_session,
        user=user,
        workspace=workspace,
        state=state,
        event={"type": "audio.pause", "payload": {}},
    )
    types_empty = [t for t, _ in sent]
    assert types_empty.count("audio.pause") == 1
    assert "session.error" not in types_empty
    assert "text.final" not in types_empty


@pytest.mark.asyncio
async def test_gateway_realtime_text_final_persists_turn(db_session, monkeypatch):
    """Realtime lane (LiveKit sidecar + gpt-realtime-whisper): a text.final event
    persists the expert turn via the SAME append_turn seam as the batch endpoint
    STT, emits text.final + evaluation.delta and resets turn state — with NO
    audio.frame / audio.endpoint round-trip and no relance / conversation.step."""
    from app.services import voice_session_gateway as gw

    workspace = Workspace(id="ws-gw-rt", name="GW RT", slug="gw-rt")
    user = User(id="user-gw-rt", username="gwrt@datategy.local", email="gwrt@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Realtime capture",
        objective="Capturer les réglages de vitesse sur la ligne.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        **_guided_plan_kwargs(),
    )
    session = _approve(db_session, workspace, session)
    session = start_session(db_session, workspace_id=workspace.id, session_id=session.id)

    monkeypatch.setattr(gw, "_retrieve_context_chunks", lambda *a, **k: ([], [], []))

    async def _fake_async_retrieve(*a, **k):
        return ([], [], [])

    monkeypatch.setattr(gw, "_retrieve_context_chunks_async", _fake_async_retrieve)
    monkeypatch.setattr(gw, "_CAPTURE_HINTS_MIN_INTERVAL_S", 0)

    sent: list[tuple] = []

    class FakeWebSocket:
        async def send_json(self, message):
            sent.append((message.get("type"), message.get("payload")))

    websocket = FakeWebSocket()
    gateway = gw.VoiceSessionGateway()
    state = gw.VoiceSessionState(
        session_id=session.id,
        mode="conversation_only",
        transport="livekit",
        tandem_oracle_enabled=True,
    )
    state.oracle = gw.VoiceTandemOracle(min_interval_ms=0, min_delta_chars=0)

    # Streaming partial deltas (gpt-realtime-whisper) drive live retrieval/section,
    # the committed final persists the turn.
    await gateway._handle_event(
        websocket,
        db_session,
        user=user,
        workspace=workspace,
        state=state,
        event={"type": "text.partial", "payload": {"turn_id": "rt-1", "text": "je règle la vitesse de la ligne"}},
    )
    await asyncio.gather(*list(state.partial_stt_tasks))

    await gateway._handle_event(
        websocket,
        db_session,
        user=user,
        workspace=workspace,
        state=state,
        event={
            "type": "text.final",
            "payload": {
                "turn_id": "rt-1",
                "text": "je règle la vitesse de la ligne à trois mètres par seconde",
                "commit": True,
                "provider": "openai_realtime",
                "model": "gpt-realtime-whisper",
                "duration_ms": 1200,
            },
        },
    )
    await asyncio.gather(*list(state.live_questions_tasks))

    types = [t for t, _ in sent]
    assert "text.final" in types
    final = next(p for t, p in sent if t == "text.final")
    assert final.get("turn_id") == "rt-1"
    assert final.get("empty") is False
    assert "evaluation.delta" in types
    # PENDANT la capture: no relance / conversation step / TTS on the live path.
    assert "conversation.step" not in types
    assert "prompt.next" not in types
    assert "audio.out" not in types
    # Persisted via the same append_turn seam as the endpoint STT.
    reloaded = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    expert_turns = [turn for turn in (reloaded.transcript or []) if turn.get("speaker") == "expert"]
    assert expert_turns
    assert "trois mètres par seconde" in expert_turns[-1].get("text", "")
    # Turn state reset so the next utterance starts clean.
    assert state.client_turn_id is None


@pytest.mark.asyncio
async def test_gateway_drops_orphan_webm_frames_on_empty_buffer(db_session, monkeypatch):
    """Header-validated buffer start (fix 24a345): when the negotiated input
    codec is webm, a frame WITHOUT the EBML magic arriving on an EMPTY buffer is
    a late MediaRecorder continuation frame (its header chunk was already
    flushed) and must be DROPPED — otherwise every subsequent buffer join is an
    unparseable container and STT 400s for the rest of the session. A frame
    WITH the header is accepted as chunk 0, continuation frames are accepted on
    a non-empty buffer, and after a pause flush + late orphan frame the resumed
    recorder's header frame self-heals the buffer."""
    from app.services import voice_session_gateway as gw

    workspace = Workspace(id="ws-gw-orphan", name="GW Orphan", slug="gw-orphan")
    user = User(id="user-gw-orphan", username="gwo@datategy.local", email="gwo@datategy.local")
    db_session.add_all([workspace, user])
    db_session.commit()

    class FakeProvider:
        async def transcribe(self, audio_bytes, *, filename=None, content_type=None, language=None):
            return {"text": "segment valide", "provider": "fake", "model": "fake-stt"}

    monkeypatch.setattr(gw, "get_voice_runtime_provider", lambda *a, **k: FakeProvider())

    sent: list[tuple] = []

    class FakeWebSocket:
        async def send_json(self, message):
            sent.append((message.get("type"), message.get("payload")))

    websocket = FakeWebSocket()
    gateway = gw.VoiceSessionGateway()
    state = gw.VoiceSessionState(session_id="capture-orphan", tandem_oracle_enabled=False)
    state.codec = {"input": "webm", "channels": 1}

    header_chunk = b"\x1a\x45\xdf\xa3" + b"\x00" * 8
    continuation_chunk = b"\xa3\x42\x10\x05" + b"\x01" * 8

    async def send_frame(chunk: bytes, turn_id: str) -> None:
        await gateway._handle_event(
            websocket,
            db_session,
            user=user,
            workspace=workspace,
            state=state,
            event={
                "type": "audio.frame",
                "payload": {
                    "bytes_b64": base64.b64encode(chunk).decode(),
                    "turn_id": turn_id,
                    "content_type": "audio/webm",
                    "incremental_transcription": False,
                },
            },
        )

    # 1) Orphan continuation frame on an EMPTY buffer: dropped, no error, no turn started.
    await send_frame(continuation_chunk, "seg-orphan-1")
    assert state.audio_chunks == []
    assert state.client_turn_id is None
    assert "session.error" not in [t for t, _ in sent]

    # 2) Header frame: accepted as chunk 0; continuation frames then accepted.
    await send_frame(header_chunk, "seg-orphan-1")
    await send_frame(continuation_chunk, "seg-orphan-1")
    assert len(state.audio_chunks) == 2
    assert state.audio_chunks[0][:4] == b"\x1a\x45\xdf\xa3"

    # 3) Pause flush: segment finalized, buffer cleared.
    await gateway._handle_event(
        websocket,
        db_session,
        user=user,
        workspace=workspace,
        state=state,
        event={"type": "audio.pause", "payload": {"turn_id": "seg-orphan-1"}},
    )
    assert "text.final" in [t for t, _ in sent]
    assert state.audio_chunks == []
    assert state.last_partial_text == ""

    # 4) Late in-flight continuation frame AFTER the flush: dropped, buffer stays empty.
    await send_frame(continuation_chunk, "seg-orphan-1")
    assert state.audio_chunks == []

    # 5) Resume: the new recorder's header frame becomes chunk 0 — valid buffer again.
    await send_frame(header_chunk, "seg-orphan-2")
    await send_frame(continuation_chunk, "seg-orphan-2")
    assert len(state.audio_chunks) == 2
    assert state.audio_chunks[0][:4] == b"\x1a\x45\xdf\xa3"
    assert state.client_turn_id == "seg-orphan-2"

    # Browser fallback frames can still be WebM even if the transport envelope
    # negotiated opus; payload content_type must therefore trigger the guard.
    state_livekit_webm = gw.VoiceSessionState(session_id="capture-orphan-livekit-webm", tandem_oracle_enabled=False)
    state_livekit_webm.codec = {"input": "opus"}
    await gateway._handle_event(
        websocket,
        db_session,
        user=user,
        workspace=workspace,
        state=state_livekit_webm,
        event={
            "type": "audio.frame",
            "payload": {
                "bytes_b64": base64.b64encode(continuation_chunk).decode(),
                "turn_id": "seg-livekit-webm-1",
                "content_type": "audio/webm",
                "incremental_transcription": False,
            },
        },
    )
    assert state_livekit_webm.audio_chunks == []

    # Non-webm payloads (e.g. LiveKit wav/opus endpoint blobs) skip the magic check entirely.
    state_other = gw.VoiceSessionState(session_id="capture-orphan-wav", tandem_oracle_enabled=False)
    state_other.codec = {"input": "wav"}
    await gateway._handle_event(
        websocket,
        db_session,
        user=user,
        workspace=workspace,
        state=state_other,
        event={
            "type": "audio.frame",
            "payload": {
                "bytes_b64": base64.b64encode(continuation_chunk).decode(),
                "turn_id": "seg-wav-1",
                "content_type": "audio/wav",
                "incremental_transcription": False,
            },
        },
    )
    assert len(state_other.audio_chunks) == 1


@pytest.mark.asyncio
async def test_gateway_skips_incremental_stt_for_livekit_endpoint_only_wav(db_session, monkeypatch):
    """LiveKit sidecar sends one complete WAV at endpoint time. That frame must not
    trigger the incremental STT path, otherwise the same turn is transcribed twice."""
    from app.services import voice_session_gateway as gw

    workspace = Workspace(id="ws-gw-lk", name="GW LiveKit", slug="gw-lk")
    user = User(id="user-gw-lk", username="gwl@datategy.local", email="gwl@datategy.local")
    db_session.add_all([workspace, user])

    class FakeProvider:
        def __init__(self) -> None:
            self.transcribe_calls = 0

        async def transcribe(self, audio_bytes, *, filename=None, content_type=None, language=None):
            self.transcribe_calls += 1
            return {
                "text": "je règle la vitesse avec un seul segment livekit",
                "provider": "fake",
                "model": "fake-stt",
            }

    fake_provider = FakeProvider()
    monkeypatch.setattr(gw, "get_voice_runtime_provider", lambda *a, **k: fake_provider)
    monkeypatch.setattr(gw, "_PARTIAL_STT_MIN_INTERVAL_MS", 0)

    sent: list[tuple] = []

    class FakeWebSocket:
        async def send_json(self, message):
            sent.append((message.get("type"), message.get("payload")))

    websocket = FakeWebSocket()
    gateway = gw.VoiceSessionGateway()
    state = gw.VoiceSessionState(session_id="livekit-session", mode="conversation_only", transport="livekit")
    state.oracle = gw.VoiceTandemOracle(min_interval_ms=0, min_delta_chars=0)

    await gateway._handle_event(
        websocket,
        db_session,
        user=user,
        workspace=workspace,
        state=state,
        event={
            "type": "audio.frame",
            "payload": {
                "bytes_b64": base64.b64encode(b"RIFF....WAVEfmt data").decode(),
                "turn_id": "seg-livekit-1",
                "content_type": "audio/wav",
                "incremental_transcription": False,
            },
        },
    )

    assert fake_provider.transcribe_calls == 0
    assert "transcript.partial" not in [event_type for event_type, _ in sent]
    assert state.audio_chunks

    await gateway._handle_event(
        websocket,
        db_session,
        user=user,
        workspace=workspace,
        state=state,
        event={"type": "audio.endpoint", "payload": {"turn_id": "seg-livekit-1"}},
    )

    assert fake_provider.transcribe_calls == 1
    assert "text.final" in [event_type for event_type, _ in sent]
    assert state.audio_chunks == []


@pytest.mark.asyncio
async def test_gateway_accepts_livekit_transport_browser_webm_without_mime_fallback(db_session, monkeypatch):
    """Browser fallback can send MediaRecorder WebM frames while the LiveKit
    transport envelope negotiated opus. The payload content_type is authoritative
    for STT so a valid WebM header must be accepted and transcribed once as WebM."""
    from app.services import voice_session_gateway as gw

    workspace = Workspace(id="ws-gw-lk-webm", name="GW LiveKit WebM", slug="gw-lk-webm")
    user = User(id="user-gw-lk-webm", username="gwlw@datategy.local", email="gwlw@datategy.local")
    db_session.add_all([workspace, user])

    class FakeProvider:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def transcribe(self, audio_bytes, *, filename=None, content_type=None, language=None):
            self.calls.append(
                {
                    "audio_bytes": audio_bytes,
                    "filename": filename,
                    "content_type": content_type,
                    "language": language,
                }
            )
            return {
                "text": "segment media recorder webm valide",
                "provider": "fake-stt",
                "model": "fake-stt",
            }

    fake_provider = FakeProvider()
    monkeypatch.setattr(gw, "get_voice_runtime_provider", lambda *a, **k: fake_provider)

    sent: list[tuple] = []

    class FakeWebSocket:
        async def send_json(self, message):
            sent.append((message.get("type"), message.get("payload")))

    websocket = FakeWebSocket()
    gateway = gw.VoiceSessionGateway()
    state = gw.VoiceSessionState(
        session_id="livekit-webm-session",
        mode="conversation_only",
        transport="livekit",
        live_partial_stt_enabled=True,
    )
    # This mirrors the mismatch that used to be risky: transport says opus, but
    # the browser fallback payload is an actual WebM MediaRecorder blob.
    state.codec = {"input": "opus"}

    await gateway._handle_event(
        websocket,
        db_session,
        user=user,
        workspace=workspace,
        state=state,
        event={
            "type": "audio.frame",
            "payload": {
                "bytes_b64": base64.b64encode(_WEBM_HEADER_CHUNK + b"webm-payload").decode(),
                "turn_id": "seg-livekit-webm-valid",
                "content_type": "audio/webm",
                "incremental_transcription": False,
            },
        },
    )

    assert state.audio_chunks
    assert state.audio_chunks[0].startswith(_WEBM_HEADER_CHUNK)
    assert state.content_type == "audio/webm"
    assert fake_provider.calls == []

    await gateway._handle_event(
        websocket,
        db_session,
        user=user,
        workspace=workspace,
        state=state,
        event={"type": "audio.endpoint", "payload": {"turn_id": "seg-livekit-webm-valid"}},
    )

    assert len(fake_provider.calls) == 1
    assert fake_provider.calls[0]["content_type"] == "audio/webm"
    assert fake_provider.calls[0]["filename"] == "seg-livekit-webm-valid.webm"
    assert fake_provider.calls[0]["audio_bytes"].startswith(_WEBM_HEADER_CHUNK)
    final = next(payload for event_type, payload in sent if event_type == "text.final")
    assert final["text"] == "segment media recorder webm valide"
    assert final["endpoint_stt_source"] == "provider"
    assert final["requested_provider"] == "cascade_openai"
    assert final["provider"] == "fake-stt"
    assert final["fallback_used"] is False
    endpoint_metric = next(
        payload for event_type, payload in sent if event_type == "runtime.metric" and payload.get("metric") == "endpoint_stt"
    )
    assert endpoint_metric["provider"] == "fake-stt"
    assert endpoint_metric["fallback_used"] is False
    assert state.audio_chunks == []


def test_oracle_detects_generalized_numeric_contradiction():
    from app.services.capture_knowledge_oracle import (
        CaptureSessionContext,
        detect_claim_contradictions,
        evaluate_capture_partial,
    )

    kb_chunks = ["La température de consigne recommandée est de 120°C selon la fiche process."]
    contradictions = detect_claim_contradictions("En cas d'exception on monte à 180°C", kb_chunks)
    assert contradictions
    assert any("180" in str(item.get("claim_expert") or "") for item in contradictions)

    context = CaptureSessionContext(
        title="Capture température",
        objective="Capturer les exceptions de température",
        domain="technical",
        expert_profile="Process engineer",
        duration_minutes=20,
        unlimited_duration=False,
        elapsed_minutes=None,
        workspace_id="ws-oracle-temp",
        context_snapshot={},
        dialogue_turns=[],
        active_subtopic_id="st-temp",
        recent_transcript=[],
    )
    live = evaluate_capture_partial(
        context,
        "En cas d'exception on monte à 180°C pour stabiliser le procédé",
        kb_chunks,
    )
    assert live["contradiction_candidates"]
    assert live["hints"]
    assert any("180" in str(item.get("hint") or "") for item in live["hints"])


def test_evaluate_capture_partial_yields_retrieval_passages():
    """A precise partial must surface the retrieved passages that back the live
    'CONTEXTE RETROUVÉ' panel, even when no contradiction is detected."""
    from app.services.capture_knowledge_oracle import (
        CaptureSessionContext,
        evaluate_capture_partial,
    )

    context = CaptureSessionContext(
        title="Capture vitesse",
        objective="Capturer les réglages de vitesse",
        domain="technical",
        expert_profile="Field engineer",
        duration_minutes=20,
        unlimited_duration=False,
        elapsed_minutes=None,
        workspace_id="ws-live-retrieval",
        context_snapshot={},
        dialogue_turns=[],
        active_subtopic_id=None,
        recent_transcript=[],
    )
    chunks = ["La vitesse nominale des rouleaux est de 120 par minute selon le manuel."]
    metadatas = [{"title": "Manuel BBA120", "source": "manual-bba120", "document_id": "doc-1"}]
    live = evaluate_capture_partial(
        context,
        "Je règle la vitesse des rouleaux selon le grade de papier produit ce matin",
        chunks,
        retrieval_metadatas=metadatas,
    )
    assert live["retrieval"], "evaluate_capture_partial should return retrieved passages"
    first = live["retrieval"][0]
    assert first["text"]
    assert first["title"] == "Manuel BBA120"
    assert first["document_id"] == "doc-1"
    assert live["oracle_exact_matches"]
    assert live["oracle_exact_matches"][0]["backend"] == "sparse_exact"
    assert "rouleaux" in live["oracle_exact_matches"][0]["matched_terms"]


def test_build_open_questions_falls_back_to_oracle_taxonomy_for_free_conversation(db_session):
    """Free-conversation sessions have no plan gaps, yet the oracle still tracks its
    own internal open questions — these must be non-empty so the panel populates."""
    from app.services.knowledge_capture import (
        build_open_questions,
        create_capture_plan,
    )

    workspace = Workspace(id="ws-free-oq", name="Free OQ", slug="free-oq")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Capture libre",
        objective="Capturer les savoirs maintenance ligne.",
        expert_profile="Senior field engineer",
        duration_minutes=0,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        plan_mode="free_conversation",
    )
    assert session.plan["mode"] == "free_conversation"
    assert not session.knowledge_gaps

    open_questions = build_open_questions(session)
    assert open_questions, "oracle internal open questions should be non-empty in free conversation"
    for item in open_questions:
        assert set(item.keys()) == {"id", "text", "topic_id", "priority", "status"}
        assert item["text"]
        assert item["status"] in {"open", "addressed"}
    priorities = [item["priority"] for item in open_questions]
    assert priorities == sorted(priorities, reverse=True)


def test_oracle_question_statuses_are_persisted_and_applied_to_quality_backlog(db_session):
    workspace = Workspace(id="ws-oracle-status", name="Oracle Status", slug="oracle-status")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Capture oracle status",
        objective="Capturer les savoirs maintenance ligne.",
        expert_profile="Senior field engineer",
        duration_minutes=0,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        plan_mode="free_conversation",
    )
    first = build_open_questions(session)[0]
    session.plan = {
        **(session.plan or {}),
        "open_questions": [{"gap_id": first["id"], "follow_up": first["text"]}],
    }
    db_session.commit()

    update_oracle_question_statuses(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        items=[{"question_id": first["id"], "question_text": first["text"], "status": "dismissed"}],
        actor_user_id="operator-1",
    )
    reloaded = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    dismissed = [item for item in build_open_questions(reloaded) if item["id"] == first["id"]][0]
    assert dismissed["status"] == "dismissed"
    assert build_quality_backlog(reloaded, [])["open_questions"] == []

    update_oracle_question_statuses(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        items=[{"question_id": first["id"], "question_text": first["text"], "status": "deferred"}],
        actor_user_id="operator-1",
    )
    reloaded = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    backlog = build_quality_backlog(reloaded, [])
    assert backlog["open_questions"][0]["status"] == "deferred"


def test_capture_session_flags_can_suppress_oracle_questions(db_session):
    workspace = Workspace(id="ws-oracle-muted", name="Oracle Muted", slug="oracle-muted")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Capture muted questions",
        objective="Capturer les savoirs maintenance ligne.",
        expert_profile="Senior field engineer",
        duration_minutes=0,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        plan_mode="free_conversation",
    )

    updated = update_capture_session_flags(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        suppress_oracle_questions=True,
    )
    assert serialize_session(updated)["metrics"]["suppress_oracle_questions"] is True

    updated = update_capture_session_flags(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        suppress_oracle_questions=False,
    )
    assert serialize_session(updated)["metrics"]["suppress_oracle_questions"] is False


def test_serialize_session_exposes_dashboard_summary_fields(db_session):
    workspace = Workspace(id="ws-dashboard-summary", name="Dashboard Summary", slug="dashboard-summary")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Capture summary",
        objective="Capturer les decisions maintenance ligne.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        plan_mode="free_conversation",
    )
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        text="On remplace la cartouche si la pression reste instable apres nettoyage et verification visuelle.",
    )
    payload = serialize_session(get_session(db_session, workspace_id=workspace.id, session_id=session.id))
    assert payload["summary_short"]
    assert "cartouche" in payload["summary_short"]
    assert isinstance(payload["open_questions_count"], int)
    assert payload["last_activity"]
    assert payload["metrics"]["summary_short"] == payload["summary_short"]


@pytest.mark.asyncio
async def test_gateway_forwards_open_questions_and_retrieval_in_free_conversation(db_session, monkeypatch):
    """New contract: during capture an audio.endpoint stays SILENT — it emits NO
    conversation.step and NO pushed open_questions/relances. It only feeds the
    passive 'contexte retrouvé' retrieval via evaluation.delta and persists the
    turn for the FINAL phase."""
    from app.services import voice_session_gateway as gw
    from app.services.knowledge_capture import create_capture_plan, start_session

    workspace = Workspace(id="ws-gw-free", name="GW Free", slug="gw-free")
    user = User(id="user-gw-free", username="gwf@datategy.local", email="gwf@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Capture libre live",
        objective="Capturer les réglages de vitesse sur la ligne.",
        expert_profile="Senior field engineer",
        duration_minutes=0,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        plan_mode="free_conversation",
    )
    session = start_session(db_session, workspace_id=workspace.id, session_id=session.id)

    class FakeProvider:
        async def transcribe(self, audio_bytes, *, filename=None, content_type=None):
            return {
                "text": "je règle la vitesse des rouleaux selon le grade de papier produit ce matin",
                "provider": "fake",
                "model": "fake-stt",
            }

    monkeypatch.setattr(gw, "get_voice_runtime_provider", lambda *a, **k: FakeProvider())
    monkeypatch.setattr(gw, "_PARTIAL_STT_MIN_INTERVAL_MS", 0)
    # Deterministic non-empty live retrieval.
    monkeypatch.setattr(
        gw,
        "_retrieve_context_chunks",
        lambda *a, **k: (
            ["La vitesse nominale des rouleaux est de 120 par minute selon le manuel."],
            [{"title": "Manuel BBA120", "source": "manual-bba120", "document_id": "doc-1"}],
            [0.91],
        ),
    )

    sent: list[tuple] = []

    class FakeWebSocket:
        async def send_json(self, message):
            sent.append((message.get("type"), message.get("payload")))

    websocket = FakeWebSocket()
    gateway = gw.VoiceSessionGateway()
    state = gw.VoiceSessionState(session_id=session.id, mode="conversation_only", tandem_oracle_enabled=True)
    state.oracle = gw.VoiceTandemOracle(min_interval_ms=0, min_delta_chars=0)

    frame_payload = {
        "bytes_b64": base64.b64encode(_WEBM_HEADER_CHUNK).decode(),
        "turn_id": "seg-free-1",
        "content_type": "audio/webm",
    }
    for _ in range(2):
        await gateway._handle_event(
            websocket,
            db_session,
            user=user,
            workspace=workspace,
            state=state,
            event={"type": "audio.frame", "payload": frame_payload},
        )
        # Drain the offloaded incremental STT task before the next frame.
        await asyncio.gather(*list(state.partial_stt_tasks))

    # The partial path stored live retrieval for the upcoming endpoint emit.
    assert state.last_retrieval_chunks

    await gateway._handle_event(
        websocket,
        db_session,
        user=user,
        workspace=workspace,
        state=state,
        event={"type": "audio.endpoint", "payload": {"turn_id": "seg-free-1"}},
    )

    # Capture stays silent: no conversation.step / prompt.next / content push.
    assert not any(t == "conversation.step" for t, _ in sent)
    assert not any(t == "prompt.next" for t, _ in sent)

    # Passive "contexte retrouvé" retrieval still rides on evaluation.delta, but
    # without any pushed open_questions/relance.
    evaluation_delta = next((p for t, p in sent if t == "evaluation.delta"), None)
    assert evaluation_delta is not None
    assert not evaluation_delta.get("open_questions")
    assert (evaluation_delta.get("relance") or {}).get("text") is None
    assert evaluation_delta.get("retrieval", {}).get("chunks"), "retrieval.chunks must be forwarded and non-empty"
    first_chunk = evaluation_delta["retrieval"]["chunks"][0]
    assert first_chunk["text"]
    assert first_chunk["title"] == "Manuel BBA120"

    # The turn is persisted silently for the FINAL phase.
    reloaded = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    assert [turn for turn in (reloaded.transcript or []) if turn.get("speaker") == "expert"]


@pytest.mark.asyncio
async def test_analyze_plan_oracle_async_uses_llm_when_available(monkeypatch):
    from app.services.capture_knowledge_oracle import CaptureSessionContext, analyze_plan_oracle_async

    monkeypatch.setattr(
        "app.services.capture_knowledge_oracle._resolve_llm_config",
        lambda workspace_id=None: ("test-key", "gpt-test"),
    )

    class FakeMessage:
        content = json.dumps(
            {
                "topic_proposals": [
                    {
                        "id": "t-llm",
                        "title": "Sujet LLM",
                        "rationale": "Proposé par le modèle.",
                        "confidence": 0.91,
                        "subtopics": [{"id": "st-llm", "title": "Sous-sujet", "objective": "Objectif"}],
                    }
                ],
                "coverage_gaps": [{"slug": "decision_rationale", "title": "Décisions", "description": "Arbitrages"}],
                "contradiction_candidates": [],
                "dialogue_probe": "Quels cas terrain sont prioritaires ?",
            }
        )

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        async def create(self, **kwargs):
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr("openai.AsyncOpenAI", lambda api_key=None: FakeClient())

    context = CaptureSessionContext(
        title="Capture LLM",
        objective="Tester l'oracle LLM",
        domain="technical",
        expert_profile="Expert",
        duration_minutes=20,
        unlimited_duration=False,
        elapsed_minutes=None,
        workspace_id="ws-oracle-llm",
        context_snapshot={},
        dialogue_turns=[{"text": "Réglages ligne"}],
        active_subtopic_id=None,
        recent_transcript=[],
    )
    oracle = await analyze_plan_oracle_async(context, rag_chunks=["Chunk KB"], base_gaps=[])
    assert oracle["topic_proposals"][0]["title"] == "Sujet LLM"
    assert oracle["dialogue_probe"].startswith("Quels cas")


@pytest.mark.asyncio
async def test_plan_structure_llm_async_includes_current_plan_and_instruction(monkeypatch):
    from app.services.capture_knowledge_oracle import CaptureSessionContext, plan_structure_llm_async

    monkeypatch.setattr(
        "app.services.capture_knowledge_oracle._resolve_llm_config",
        lambda workspace_id=None: ("test-key", "gpt-test"),
    )

    captured: dict = {}

    class FakeMessage:
        content = json.dumps(
            {
                "topic_proposals": [
                    {
                        "id": "t-sec",
                        "title": "Directives de sécurité",
                        "subtopics": [
                            {
                                "id": "st-sec",
                                "title": "Consignes",
                                "questions": [{"id": "pt-sec", "title": "Point sécurité ajouté"}],
                            }
                        ],
                    }
                ],
                "coverage_gaps": [],
                "contradiction_candidates": [],
                "dialogue_probe": "Autre point à couvrir ?",
            }
        )

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        async def create(self, **kwargs):
            captured["kwargs"] = kwargs
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr("openai.AsyncOpenAI", lambda api_key=None: FakeClient())

    current_plan = [
        {
            "id": "t-01",
            "title": "Contexte projet",
            "subtopics": [{"id": "st-01", "title": "Périmètre", "questions": []}],
        },
        {
            "id": "t-04",
            "title": "Directives de sécurité",
            "subtopics": [{"id": "st-04", "title": "Consignes", "questions": []}],
        },
    ]
    context = CaptureSessionContext(
        title="Capture sécurité",
        objective="Capturer le savoir terrain",
        domain="technical",
        expert_profile="Expert",
        duration_minutes=20,
        unlimited_duration=False,
        elapsed_minutes=None,
        workspace_id="ws-oracle-iter",
        context_snapshot={},
        dialogue_turns=[{"text": "ajouter un point sécurité"}],
        active_subtopic_id=None,
        recent_transcript=[],
        current_plan=current_plan,
        latest_instruction="ajouter un point sécurité",
        provided_seed="1. Contexte\n4. Directives de sécurité",
    )
    parsed = await plan_structure_llm_async(context)
    assert parsed is not None
    payload = json.loads(captured["kwargs"]["messages"][1]["content"])
    assert payload["current_plan"] == current_plan
    assert payload["latest_instruction"] == "ajouter un point sécurité"
    assert payload["provided_seed"] == "1. Contexte\n4. Directives de sécurité"
    assert "MODE ITÉRATION" in payload["instruction"]
    system = captured["kwargs"]["messages"][0]["content"]
    assert "ITERATION MODE" in system


def test_plan_dialogue_turn_passes_iteration_context_to_llm(db_session, monkeypatch):
    """Existing plan + targeted instruction must reach the LLM as current_plan."""
    from app.services.knowledge_capture import (
        PLAN_BUILD_V2_SCHEMA_VERSION,
        create_capture_plan,
        get_session,
        process_plan_dialogue_turn,
    )

    workspace = Workspace(id="ws-plan-iter", name="Plan Iter", slug="plan-iter")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    captured: dict = {}

    async def fake_retrieve_for_mode(doc_svc, query, mode, **kwargs):
        class Result:
            chunks = []
            scores = []
            metadatas = []
            pipeline = "chah_backend"
            label = "C-HAH (backend)"
            reason = "fake retrieval"
            detail = query

        return Result()

    async def fake_plan_structure_llm_async(context, **kwargs):
        captured["current_plan"] = context.current_plan
        captured["latest_instruction"] = context.latest_instruction
        captured["provided_seed"] = context.provided_seed
        return {
            "topic_proposals": [
                {
                    "id": "t-04-new",
                    "title": "Directives de sécurité",
                    "subtopics": [
                        {
                            "id": "st-04-new",
                            "title": "Consignes",
                            "questions": [{"id": "pt-new", "title": "Point sécurité"}],
                        }
                    ],
                }
            ],
            "coverage_gaps": [],
            "contradiction_candidates": [],
            "dialogue_probe": "Autre point ?",
        }

    monkeypatch.setattr("app.services.rag.pipeline_retrieval.retrieve_for_mode", fake_retrieve_for_mode)
    monkeypatch.setattr("app.services.rag.context.retrieve_for_mode", fake_retrieve_for_mode)
    monkeypatch.setattr("app.services.rag.document_service.DocumentService", lambda **kwargs: object())
    monkeypatch.setattr("app.services.knowledge_capture.plan_structure_llm_async", fake_plan_structure_llm_async)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Co-construction sécurité",
        objective="Capturer le savoir terrain.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        plan_mode="plan_build",
        provided_plan_text="1. Contexte\n4. Directives de sécurité",
    )
    session = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    plan = dict(session.plan or {})
    plan["topics"] = [
        {
            "id": "t-01",
            "title": "Contexte projet",
            "subtopics": [{"id": "st-01", "title": "Périmètre", "questions": []}],
        },
        {
            "id": "t-04",
            "title": "Directives de sécurité",
            "subtopics": [{"id": "st-04", "title": "Consignes", "questions": []}],
        },
    ]
    session.plan = plan
    db_session.add(session)
    db_session.commit()

    turn = process_plan_dialogue_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        text="ajouter un point sécurité",
        workspace_slug=workspace.slug,
    )
    assert turn["session"]["plan"]["schema_version"] == PLAN_BUILD_V2_SCHEMA_VERSION
    assert captured["latest_instruction"] == "ajouter un point sécurité"
    assert captured["provided_seed"] == "1. Contexte\n4. Directives de sécurité"
    plan_titles = [topic["title"] for topic in captured["current_plan"]]
    assert "Directives de sécurité" in plan_titles
    merged_titles = [topic["title"] for topic in turn["session"]["plan"]["topics"]]
    assert "Directives de sécurité" in merged_titles
    persisted = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    security_topic = next(
        topic for topic in persisted.plan["topics"] if topic["title"] == "Directives de sécurité"
    )
    assert security_topic["id"] == "t-04"
    assert security_topic["subtopics"][0]["questions"][0]["title"] == "Point sécurité"


def test_detect_active_section_from_text_title_overlap():
    from app.services.capture_knowledge_oracle import (
        LIVE_SECTION_DETECT_MIN_CONFIDENCE,
        detect_active_section_from_text,
    )

    plan_topics = [
        {
            "id": "t-01",
            "title": "Maintenance rouleaux",
            "subtopics": [
                {"id": "st-speed", "title": "Vitesse rouleaux"},
                {"id": "st-align", "title": "Inspection et alignement"},
            ],
        }
    ]
    detected = detect_active_section_from_text(
        plan_topics,
        "En cas exceptionnel on monte la vitesse rouleaux à 180 par minute sur la ligne",
    )
    assert detected["subtopic_id"] == "st-speed"
    assert detected["topic_id"] == "t-01"
    assert detected["confidence"] >= LIVE_SECTION_DETECT_MIN_CONFIDENCE

    low_signal = detect_active_section_from_text(
        plan_topics,
        "oui d'accord je comprends bien merci",
        fallback_subtopic_id="st-align",
    )
    assert low_signal["confidence"] == 0.0
    assert low_signal["subtopic_id"] == "st-align"


@pytest.mark.asyncio
async def test_gateway_emits_section_active_on_partial(db_session, monkeypatch):
    from app.services import voice_session_gateway as gw
    import app.services.knowledge_capture as kc

    async def _no_retrieval(*_a, **_k):
        return ([], [], [])

    monkeypatch.setattr(kc, "_retrieve_context_chunks_async", _no_retrieval)

    workspace = Workspace(id="ws-sec-active", name="Sec Active", slug="sec-active")
    user = User(id="user-sec-active", username="sa@datategy.local", email="sa@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session, topic_id, subtopic_id = _final_phase_session(db_session, workspace, user)
    sent: list[tuple] = []

    class FakeWebSocket:
        async def send_json(self, message):
            sent.append((message.get("type"), message.get("payload")))

    websocket = FakeWebSocket()
    gateway = gw.VoiceSessionGateway()
    state = gw.VoiceSessionState(session_id=session.id, mode="guided", tandem_oracle_enabled=True)
    state.active_topic_id = topic_id
    state.active_subtopic_id = subtopic_id

    capture_session = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    other_subtopic = None
    other_title = None
    for topic in (capture_session.plan or {}).get("topics") or []:
        for st in topic.get("subtopics") or []:
            if st.get("id") != subtopic_id:
                other_subtopic = st["id"]
                other_title = st.get("title") or "autre section"
                break
        if other_subtopic:
            break
    assert other_subtopic and other_title
    partial = (
        f"Pour la sous-section {other_title} on vérifie les points clés "
        f"chaque semaine avec un gabarit sur la ligne"
    )
    await gateway._maybe_detect_and_emit_active_section(
        websocket,
        db_session,
        workspace=workspace,
        state=state,
        plan=capture_session.plan,
        partial_text=partial,
        source="turn_commit",
    )

    active_events = [p for t, p in sent if t == "section.active"]
    assert len(active_events) == 1
    assert active_events[0]["subtopic_id"] == other_subtopic
    assert active_events[0]["confidence"] >= 0.42


@pytest.mark.asyncio
async def test_generate_question_bank_entry_async_falls_back_without_key():
    from app.services.capture_knowledge_oracle import generate_question_bank_entry_async

    entry = await generate_question_bank_entry_async(
        workspace_id="ws-qb-fallback",
        subtopic_title="Vitesse rouleaux",
        subtopic_objective="Clarifier les exceptions terrain",
        session_objective="Capture réglages",
        rag_chunks=["La vitesse nominale est de 120/min."],
    )
    assert entry["full_question"]
    assert entry["hint"]
    assert len(entry["hint"]) <= 80


def test_plan_build_oracle_dialogue_and_topic_validation(db_session, monkeypatch):
    from app.services.knowledge_capture import (
        PLAN_BUILD_V2_SCHEMA_VERSION,
        create_capture_plan,
        finalize_plan_from_dialogue,
        generate_question_bank,
        get_hint_queue,
        get_session,
        process_capture_partial_hints,
        process_plan_dialogue_turn,
        serialize_session,
        start_session,
        validate_plan_topics,
    )

    workspace = Workspace(id="ws-oracle-plan", name="Oracle Plan", slug="oracle-plan")
    context = Context(
        id="ctx-oracle-plan",
        workspace_id=workspace.id,
        name="BBA120 manuals",
        environment_state={"collection": "andritz-manuals-bba120-pilot"},
    )
    db_session.add_all([workspace, context])
    seed_skills_and_capabilities(db_session)

    async def fake_retrieve_for_mode(doc_svc, query, mode, **kwargs):
        class Result:
            chunks = ["La vitesse nominale des rouleaux est de 120/min."]
            scores = [0.92]
            metadatas = [{"title": "Manuel BBA120", "source": "manual-bba120"}]
            pipeline = "chah_backend"
            label = "C-HAH (backend)"
            reason = "fake retrieval"
            detail = query

        return Result()

    monkeypatch.setattr("app.services.rag.pipeline_retrieval.retrieve_for_mode", fake_retrieve_for_mode)
    monkeypatch.setattr("app.services.rag.context.retrieve_for_mode", fake_retrieve_for_mode)
    monkeypatch.setattr("app.services.rag.document_service.DocumentService", lambda **kwargs: object())

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Co-construction rouleaux",
        objective="Capturer les réglages vitesse rouleaux.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=context.id,
        system_id=None,
        knowledge_refs=[],
        plan_mode="plan_build",
    )
    assert session.plan["schema_version"] == PLAN_BUILD_V2_SCHEMA_VERSION

    turn = process_plan_dialogue_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        text="Réglages ligne, vitesse rouleaux et cas exceptionnels terrain à 180/min",
        workspace_slug=workspace.slug,
    )
    # New contract: a single dialogue turn already builds the topic tree, so the
    # plan is ready to finalize immediately (frontend gates on topics existing) and
    # the oracle no longer returns a follow-up probe.
    assert turn["ready_to_finalize"]
    assert turn["session"]["plan"]["topics"]
    assert turn["session"]["plan"].get("oracle", {}).get("coverage_gaps") is not None
    assert turn["session"]["plan"]["oracle"]["oracle_exact_matches"]
    assert turn["session"]["plan"]["oracle"]["contradiction_candidates"][0]["exact_match_backend"] == "sparse_exact"
    assert not serialize_session(session, surface="plan_build")["plan"].get("questions")

    for idx in range(2):
        process_plan_dialogue_turn(
            db_session,
            workspace_id=workspace.id,
            session_id=session.id,
            text=f"Précision cadrage {idx + 2} sur ligne BBA120 et exceptions maintenance.",
            workspace_slug=workspace.slug,
            confirm_finalize=idx == 1,
        )

    pre_finalize_topics = serialize_session(
        get_session(db_session, workspace_id=workspace.id, session_id=session.id),
        surface="plan_build",
    )["plan"]["topics"]

    finalized = finalize_plan_from_dialogue(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        workspace_slug=workspace.slug,
    )
    assert finalized.plan["topics"]
    # Finalize preserves the topics already built by the dialogue verbatim — it must
    # not re-run the oracle / reshuffle the plan the user already saw.
    assert [t["id"] for t in finalized.plan["topics"]] == [t["id"] for t in pre_finalize_topics]
    # Idle question bank is auto-scheduled (status flips to generating) so the launch
    # screen no longer needs an explicit confirmation step.
    assert finalized.plan["question_bank_status"] == "generating"
    assert not serialize_session(finalized, surface="plan")["plan"].get("questions")

    validated = validate_plan_topics(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
    )
    assert validated.plan["review"]["status"] == "topics_validated"

    ready = generate_question_bank(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        workspace_slug=workspace.slug,
    )
    assert ready.plan["question_bank_status"] == "ready"
    assert ready.plan["question_bank"]

    hint_result = process_capture_partial_hints(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        partial_text="En cas X on monte à 180/min pour stabiliser la ligne",
        retrieval_chunks=["La vitesse nominale des rouleaux est de 120/min."],
    )
    assert hint_result["hints"]
    queue = get_hint_queue(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        subtopic_id=hint_result["hints"][0].get("subtopic_id"),
    )
    assert queue["hints"][0]["hint"]
    assert "180" in queue["hints"][0]["hint"]

    started = start_session(db_session, workspace_id=workspace.id, session_id=session.id)
    assert started.status == "active"


def test_plan_dialogue_turns_do_not_pollute_capture_transcript(db_session, monkeypatch):
    """Plan co-construction dialogue must stay in plan metadata, not capture turns."""
    from app.services.knowledge_capture import (
        create_capture_plan,
        get_session,
        list_capture_events,
        process_plan_dialogue_turn,
    )

    workspace = Workspace(id="ws-plan-tx-leak", name="Plan Tx Leak", slug="plan-tx-leak")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    async def fake_retrieve_for_mode(doc_svc, query, mode, **kwargs):
        class Result:
            chunks = []
            scores = []
            metadatas = []
            pipeline = "chah_backend"
            label = "C-HAH (backend)"
            reason = "fake retrieval"
            detail = query

        return Result()

    monkeypatch.setattr("app.services.rag.pipeline_retrieval.retrieve_for_mode", fake_retrieve_for_mode)
    monkeypatch.setattr("app.services.rag.context.retrieve_for_mode", fake_retrieve_for_mode)
    monkeypatch.setattr("app.services.rag.document_service.DocumentService", lambda **kwargs: object())

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Cadrage client",
        objective="Présenter le client et les consignes de sécurité.",
        expert_profile="Expert métier",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        plan_mode="plan_build",
    )

    for text in (
        "Alors, ce document va d'abord présenter le client machin chose.",
        "Rajoute la consigne de sécurité dans le plan.",
    ):
        process_plan_dialogue_turn(
            db_session,
            workspace_id=workspace.id,
            session_id=session.id,
            text=text,
            workspace_slug=workspace.slug,
        )

    all_events = list_capture_events(
        db_session, workspace_id=workspace.id, session_id=session.id, business_only=False
    )
    business_events = list_capture_events(
        db_session, workspace_id=workspace.id, session_id=session.id, business_only=True
    )
    plan_events = [event for event in all_events if event.event_type == "plan_dialogue_turn"]
    assert len(plan_events) == 2
    for event in plan_events:
        assert event.speaker != "expert"
        assert (event.meta_data or {}).get("capture_phase") == "plan_build"

    capture_turn_types = {"expert_turn_finalized", "stt_final", "transcript_turn_recorded"}
    assert not any(event.event_type in capture_turn_types for event in all_events)
    assert not any(event.event_type in capture_turn_types for event in business_events)
    reloaded = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    assert not (reloaded.transcript or [])


def test_plan_build_subtopics_are_grounded_not_gap_taxonomy(db_session):
    """Co-construction (plan_build) must ground topics/subtopics in what the expert
    expressed, and must never surface the internal _BASE_GAPS taxonomy titles
    (Decision rationale, Exceptions and edge cases, ...) as visible plan subtopics."""
    from app.services.knowledge_capture import (
        _BASE_GAPS,
        create_capture_plan,
        finalize_plan_from_dialogue,
        process_plan_dialogue_turn,
    )

    workspace = Workspace(id="ws-grounded-plan", name="Grounded Plan", slug="grounded-plan")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Cadrage maintenance",
        objective="Capturer les savoirs maintenance.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        plan_mode="plan_build",
    )
    # Co-construction path is reachable: a fresh plan_build session is a dialogue
    # shell with no questions and no pre-seeded topics.
    assert session.plan["mode"] == "plan_build"
    assert session.plan["dialogue"]["status"] == "in_progress"
    assert not session.plan.get("topics")
    assert not session.plan.get("questions")

    expert_text = (
        "On va décrire la maintenance des rouleaux, puis la lubrification de la "
        "ligne et enfin les contrôles qualité en fin de poste."
    )
    turn = process_plan_dialogue_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        text=expert_text,
        workspace_slug=workspace.slug,
        confirm_finalize=True,
    )
    # The co-construction dialogue is intact: the expert's statement is recorded as a
    # turn, the oracle runs, and a grounded outline is produced from it.
    assert turn["session"]["plan"]["dialogue"]["turns"]
    assert turn["session"]["plan"]["topics"]
    assert turn["oracle"].get("coverage_gaps") is not None

    finalized = finalize_plan_from_dialogue(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        workspace_slug=workspace.slug,
    )

    gap_titles = {str(gap["title"]).lower() for gap in _BASE_GAPS}
    gap_descriptions = {str(gap["description"]).lower() for gap in _BASE_GAPS}
    topics = finalized.plan["topics"]
    assert topics

    all_titles: list[str] = []
    for topic in topics:
        all_titles.append(str(topic.get("title") or ""))
        for subtopic in topic.get("subtopics") or []:
            sub_title = str(subtopic.get("title") or "")
            all_titles.append(sub_title)
            # Gap taxonomy must never become a visible subtopic title/objective.
            assert sub_title.lower() not in gap_titles
            assert str(subtopic.get("objective") or "").lower() not in gap_descriptions
            # No duplication where the subtopic title equals its description line.
            assert sub_title.strip() and sub_title.strip() != str(subtopic.get("objective") or "").strip()

    titles_blob = " ".join(all_titles).lower()
    assert not (gap_titles & set(t.lower() for t in all_titles))
    # Subtopics are grounded in the expert's expressed subjects.
    assert "maintenance" in titles_blob or "lubrification" in titles_blob


def test_parse_provided_plan_text_builds_topic_tree():
    from app.services.knowledge_capture import parse_provided_plan_text

    topics = parse_provided_plan_text(
        "# Maintenance ligne\n"
        "## Réglages rouleaux\n"
        "## Lubrification\n"
        "# Revue documentaire\n"
        "- Sources internes\n"
    )
    assert len(topics) == 2
    assert topics[0]["title"] == "Maintenance ligne"
    assert len(topics[0]["subtopics"]) == 2
    assert topics[0]["subtopics"][0]["title"] == "Réglages rouleaux"
    assert topics[1]["subtopics"][0]["title"] == "Sources internes"


def test_parse_provided_plan_text_builds_three_level_hierarchy():
    from app.services.knowledge_capture import parse_provided_plan_text

    topics = parse_provided_plan_text(
        "# Introduction\n"
        "## Contexte\n"
        "### Périmètre du projet\n"
        "### Objectifs\n"
        "# Optimisation\n"
        "## Énergie\n"
        "- Réduction consommation\n"
        "- Récupération de chaleur\n"
    )
    assert [t["title"] for t in topics] == ["Introduction", "Optimisation"]
    contexte = topics[0]["subtopics"][0]
    assert contexte["title"] == "Contexte"
    assert [p["title"] for p in contexte["questions"]] == ["Périmètre du projet", "Objectifs"]
    # 3rd-level points carry an invitation-to-present prompt, never an interview question.
    assert contexte["questions"][0]["prompt"]
    assert "?" not in contexte["questions"][0]["prompt"]
    energy = topics[1]["subtopics"][0]
    assert energy["title"] == "Énergie"
    assert [p["title"] for p in energy["questions"]] == [
        "Réduction consommation",
        "Récupération de chaleur",
    ]


def test_parse_provided_plan_text_honours_indentation():
    from app.services.knowledge_capture import parse_provided_plan_text

    topics = parse_provided_plan_text(
        "Description de la ligne\n"
        "    Machines\n"
        "        Cardes\n"
        "        Nappeur\n"
        "Analyse de l'existant\n"
        "    Problèmes rencontrés\n"
    )
    assert [t["title"] for t in topics] == ["Description de la ligne", "Analyse de l'existant"]
    machines = topics[0]["subtopics"][0]
    assert machines["title"] == "Machines"
    assert [p["title"] for p in machines["questions"]] == ["Cardes", "Nappeur"]
    assert topics[1]["subtopics"][0]["title"] == "Problèmes rencontrés"


def test_parse_provided_plan_text_honours_dotted_numbering():
    from app.services.knowledge_capture import parse_provided_plan_text

    topics = parse_provided_plan_text(
        "1. Introduction\n"
        "1.1 Contexte\n"
        "1.1.1 Périmètre\n"
        "2. Optimisation\n"
        "2.1 Énergie\n"
    )
    assert [t["title"] for t in topics] == ["Introduction", "Optimisation"]
    assert topics[0]["subtopics"][0]["title"] == "Contexte"
    assert topics[0]["subtopics"][0]["questions"][0]["title"] == "Périmètre"
    assert topics[1]["subtopics"][0]["title"] == "Énergie"


def test_parse_provided_plan_text_plain_multisection_does_not_collapse():
    """A plain multi-line paste (no markers, no indentation) must NOT collapse into a
    single topic with everything else as one flat subtopic list."""
    from app.services.knowledge_capture import parse_provided_plan_text

    sections = [
        "Introduction",
        "Description de la ligne",
        "Analyse de l'existant",
        "Optimisation énergétique",
        "Optimisation de la vitesse",
        "Optimisation de l'homogénéité",
        "Essais",
        "Conclusions",
    ]
    topics = parse_provided_plan_text("\n".join(sections))
    assert [t["title"] for t in topics] == sections
    assert len(topics) == len(sections)
    # Plain sections stay topic-only; no forced mirror subtopics.
    assert all(not t["subtopics"] for t in topics)


def test_normalize_plan_build_topics_allows_topic_without_subtopics():
    from app.services.knowledge_capture import (
        _flatten_plan_questions,
        _normalize_plan_build_topics,
        validate_plan_topics,
        create_capture_plan,
    )

    topics = [{"id": "t-01", "title": "Attentes du client", "subtopics": []}]
    normalized = _normalize_plan_build_topics({"topics": topics})
    assert len(normalized) == 1
    assert normalized[0]["title"] == "Attentes du client"
    assert normalized[0]["subtopics"] == []

    questions = _flatten_plan_questions({"topics": normalized})
    assert len(questions) == 1
    assert questions[0]["topic_id"] == "t-01"
    assert questions[0]["subtopic_id"] is None
    assert "Attentes du client" in questions[0]["question"]


def test_validate_plan_topics_accepts_topic_only_outline(db_session):
    from app.services.knowledge_capture import (
        PLAN_BUILD_V2_SCHEMA_VERSION,
        create_capture_plan,
        update_plan_topics,
        validate_plan_topics,
    )

    workspace = Workspace(id="ws-topic-only", name="Topic Only", slug="topic-only")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Capture topic-only",
        objective="Capturer les attentes client.",
        expert_profile="Expert",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        plan_mode="plan_build",
    )
    assert session.plan["schema_version"] == PLAN_BUILD_V2_SCHEMA_VERSION

    update_plan_topics(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        topics=[{"id": "t-01", "title": "Attentes du client", "subtopics": []}],
    )
    validated = validate_plan_topics(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
    )
    assert validated.plan["review"]["status"] == "topics_validated"
    assert validated.plan["topics"][0]["subtopics"] == []


def test_parse_provided_plan_text_tree_passes_normalization():
    """A parsed 3-level tree must survive _normalize_plan_build_topics unchanged in depth."""
    from app.services.knowledge_capture import (
        _normalize_plan_build_topics,
        parse_provided_plan_text,
    )

    topics = parse_provided_plan_text(
        "# Optimisation de la ligne\n"
        "## Énergie\n"
        "### Récupération de chaleur\n"
        "## Vitesse\n"
    )
    normalized = _normalize_plan_build_topics({"topics": topics})
    n_topics = len(normalized)
    n_sub = sum(len(t.get("subtopics") or []) for t in normalized)
    n_points = sum(
        len(sub.get("questions") or [])
        for t in normalized
        for sub in t.get("subtopics") or []
    )
    assert n_topics == 1
    assert n_sub == 2
    assert n_points == 1


def test_merge_topic_proposals_preserves_three_level_points():
    """Oracle proposals carrying subtopic-level presentation points (3rd level) must be
    persisted end-to-end through merge_topic_proposals."""
    from app.services.capture_knowledge_oracle import merge_topic_proposals

    proposals = [
        {
            "id": "t-01",
            "title": "Optimisation énergétique",
            "subtopics": [
                {
                    "id": "t-01-sub-01",
                    "title": "Récupération de chaleur",
                    "questions": [
                        {"title": "Sources de chaleur récupérables"},
                        "Dimensionnement de l'échangeur",
                    ],
                }
            ],
        }
    ]
    merged = merge_topic_proposals({"topics": []}, proposals)
    assert len(merged) == 1
    sub = merged[0]["subtopics"][0]
    points = sub["questions"]
    assert [p["title"] for p in points] == [
        "Sources de chaleur récupérables",
        "Dimensionnement de l'échangeur",
    ]
    assert all(p["id"] and p["prompt"] for p in points)
    # Re-merging preserves the prior points (idempotent, no duplication).
    remerged = merge_topic_proposals({"topics": merged}, proposals)
    assert len(remerged[0]["subtopics"][0]["questions"]) == 2


def test_merge_topic_proposals_iteration_replaces_instead_of_appending():
    """QA 'ajout section jets d'eau': applying an instruction regenerates the whole
    plan with fresh ids and slightly reworded titles. The merge must REPLACE the
    plan (matching existing sections by title) instead of re-appending the old
    sections after the regenerated ones — no duplicate sections."""
    from app.services.capture_knowledge_oracle import merge_topic_proposals

    existing_plan = {
        "topics": [
            {
                "id": "t-01",
                "title": "Maintenance des rouleaux",
                "subtopics": [{"id": "st-01", "title": "Inspection et alignement", "status": "pending"}],
            },
            {
                "id": "t-02",
                "title": "Lubrification de la ligne",
                "subtopics": [{"id": "st-02", "title": "Points de graissage", "status": "pending"}],
            },
            {
                "id": "t-03",
                "title": "Contrôles qualité",
                "subtopics": [{"id": "st-03", "title": "Contrôles visuels", "status": "pending"}],
            },
        ]
    }
    # LLM regenerated the plan: new ids, reworded titles, plus the requested new section.
    proposals = [
        {
            "id": "n-01",
            "title": "Maintenance et entretien des rouleaux",
            "subtopics": [{"id": "n-01-sub-01", "title": "Inspection et alignement des rouleaux"}],
        },
        {
            "id": "n-02",
            "title": "Lubrification de la ligne",
            "subtopics": [{"id": "n-02-sub-01", "title": "Points de graissage"}],
        },
        {
            "id": "n-03",
            "title": "Contrôles qualité",
            "subtopics": [{"id": "n-03-sub-01", "title": "Contrôles visuels"}],
        },
        {
            "id": "n-04",
            "title": "Jets d'eau",
            "subtopics": [{"id": "n-04-sub-01", "title": "Réglage des jets d'eau"}],
        },
    ]
    merged = merge_topic_proposals(existing_plan, proposals)
    titles = [topic["title"] for topic in merged]
    # One coherent plan: 3 original sections (user-seen titles preserved) + 1 new.
    assert len(merged) == 4
    assert titles == [
        "Maintenance des rouleaux",
        "Lubrification de la ligne",
        "Contrôles qualité",
        "Jets d'eau",
    ]
    # Existing ids/subtopic state survive the title-based match.
    assert [topic["id"] for topic in merged[:3]] == ["t-01", "t-02", "t-03"]
    assert merged[0]["subtopics"][0]["id"] == "st-01"
    # Idempotent: re-applying the same proposals never duplicates sections.
    remerged = merge_topic_proposals({"topics": merged}, proposals)
    assert [topic["title"] for topic in remerged] == titles


def test_merge_topic_proposals_dedupes_duplicate_llm_sections():
    """A single LLM response sometimes emits near-duplicate sections; only the
    first occurrence is kept."""
    from app.services.capture_knowledge_oracle import merge_topic_proposals

    proposals = [
        {"id": "a-01", "title": "Maintenance des rouleaux", "subtopics": [{"title": "Inspection"}]},
        {"id": "a-02", "title": "Maintenance et entretien des rouleaux", "subtopics": [{"title": "Inspection"}]},
        {"id": "a-03", "title": "Jets d'eau", "subtopics": [{"title": "Réglage"}]},
    ]
    merged = merge_topic_proposals({"topics": []}, proposals)
    assert [topic["title"] for topic in merged] == ["Maintenance des rouleaux", "Jets d'eau"]


def test_provided_plan_mode_seeds_topics_on_create(db_session):
    from app.services.knowledge_capture import create_capture_plan

    workspace = Workspace(id="ws-provided-plan", name="Provided Plan", slug="provided-plan")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Plan importé",
        objective="Capturer les savoirs maintenance.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        plan_mode="provided_plan",
        provided_plan_text="# Sujet A\n## Point 1\n## Point 2",
        plan_source_kind="uploaded_file",
        plan_source_filename="plan-capture.md",
        plan_source_replaces_existing_plan=True,
    )
    assert session.plan["mode"] == "provided_plan"
    assert session.plan["schema_version"] == "plan_build_v2"
    assert len(session.plan["topics"]) == 1
    assert len(session.plan["topics"][0]["subtopics"]) == 2
    assert session.plan["dialogue"]["ready_to_finalize"] is True
    assert session.plan["plan_source"] == {
        "kind": "uploaded_file",
        "filename": "plan-capture.md",
        "extracted_outline": [{"title": "Sujet A", "subtopics": ["Point 1", "Point 2"]}],
        "replaces_existing_plan": True,
        "chars": 31,
        "line_count": 3,
    }


def test_classify_conversation_intent_detects_defer_vocal():
    from app.services.knowledge_capture import classify_conversation_intent

    result = classify_conversation_intent(text="Je traiterai plus tard, pas maintenant.")
    assert result["intent"] == "defer_vocal"


def test_defer_vocal_defers_open_quality_item(db_session):
    from app.services.knowledge_capture import (
        append_turn,
        create_capture_plan,
        process_conversation_step,
        start_session,
    )

    workspace = Workspace(id="ws-defer-vocal", name="Defer Vocal", slug="defer-vocal")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Defer vocal",
        objective="Capture maintenance.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        plan_mode="free_conversation",
    )
    session = start_session(db_session, workspace_id=workspace.id, session_id=session.id)
    question_id = None
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        text="ok",
        question_id=question_id,
    )
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        text="C'est peut-être vrai mais je ne suis pas sûr du seuil exact.",
        question_id=question_id,
    )

    step = process_conversation_step(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        client_turn_id="defer-vocal-1",
        question_id=question_id,
        retrieval_event_id=None,
        interruption_of_event_id=None,
        last_proposal_id=None,
        text="On verra en fin de session.",
    )
    assert step["intent"] == "defer_vocal"
    assert step["action_taken"] in {"quality_item_deferred", "hint_deferred", "defer_no_target"}


def test_quality_backlog_empty_session_has_no_items(db_session):
    workspace = Workspace(id="ws-quality-empty", name="Quality Empty", slug="quality-empty")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Backlog vide",
        objective="Vérifier l'état vide du backlog qualité.",
        expert_profile="Expert",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        plan_mode="free_conversation",
    )

    backlog = build_quality_backlog(session, [])

    assert backlog["imprecisions"] == []
    assert backlog["contradictions"] == []
    assert backlog["open_questions"] == []
    assert backlog["defer_weak_contradictions"] is False


def test_defer_quality_item_rejects_stale_id_without_event(db_session):
    workspace = Workspace(id="ws-quality-stale", name="Quality Stale", slug="quality-stale")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Backlog stale",
        objective="Vérifier le rejet d'un item qualité obsolète.",
        expert_profile="Expert",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        plan_mode="free_conversation",
    )

    with pytest.raises(ValueError, match="Quality item not found"):
        defer_quality_item(
            db_session,
            workspace_id=workspace.id,
            session_id=session.id,
            item_id="missing-quality-item",
            bucket="imprecisions",
            deferred_reason="end_of_session",
            actor_user_id="reviewer",
        )

    events = list_capture_events(db_session, workspace_id=workspace.id, session_id=session.id)
    assert not any(event.event_type == "quality_item_deferred" for event in events)
    assert build_quality_backlog(session, events)["imprecisions"] == []


def test_defer_quality_item_marks_existing_item_without_duplicate_open_entry(db_session):
    workspace = Workspace(id="ws-quality-valid", name="Quality Valid", slug="quality-valid")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Backlog defer",
        objective="Vérifier le report d'un item qualité existant.",
        expert_profile="Expert",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        plan_mode="free_conversation",
    )
    session.evaluations = [
        {
            "id": "quality-precision-1",
            "verdict": "needs_precision",
            "score": 0.52,
            "follow_up": "Préciser le seuil de validation terrain.",
        }
    ]
    db_session.add(session)
    db_session.commit()

    before = build_quality_backlog(session, [])
    assert [item["id"] for item in before["imprecisions"]] == ["quality-precision-1"]

    after = defer_quality_item(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        item_id="quality-precision-1",
        bucket="imprecisions",
        deferred_reason="end_of_session",
        actor_user_id="reviewer",
    )

    assert after["imprecisions"] == [
        {
            "id": "quality-precision-1",
            "label": "Préciser le seuil de validation terrain.",
            "status": "deferred",
            "deferred_reason": "end_of_session",
        }
    ]
    events = list_capture_events(db_session, workspace_id=workspace.id, session_id=session.id)
    deferred_events = [event for event in events if event.event_type == "quality_item_deferred"]
    assert len(deferred_events) == 1
    assert deferred_events[0].meta_data["item_id"] == "quality-precision-1"


def test_resolve_hints_from_expert_text_marks_overlap(db_session, monkeypatch):
    from app.services.knowledge_capture import (
        create_capture_plan,
        get_hint_queue,
        prepend_hint_to_queue,
        resolve_hints_from_expert_text,
        start_session,
    )

    workspace = Workspace(id="ws-hint-resolve", name="Hint Resolve", slug="hint-resolve")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Hint resolve",
        objective="Vitesse rouleaux et exceptions terrain.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        plan_mode="free_conversation",
    )
    plan = dict(session.plan or {})
    plan["topics"] = [
        {
            "id": "t-01",
            "title": "Rouleaux",
            "subtopics": [{"id": "t-01-sub-01", "title": "Vitesse", "objective": "Exceptions 180/min"}],
        }
    ]
    session.plan = plan
    db_session.commit()
    session = start_session(db_session, workspace_id=workspace.id, session_id=session.id)
    plan = dict(session.plan or {})
    prepend_hint_to_queue(
        plan,
        subtopic_id="t-01-sub-01",
        hint_entry={
            "id": "hint-speed",
            "hint": "Clarifier vitesse rouleaux exception 180/min",
            "priority": 90,
            "visibility": "hint",
        },
    )
    session.plan = plan
    db_session.commit()

    resolved = resolve_hints_from_expert_text(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        text="En production on monte parfois la vitesse rouleaux à 180/min pour stabiliser.",
    )
    assert resolved
    queue = get_hint_queue(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        subtopic_id="t-01-sub-01",
    )
    assert queue["hints"] == []


def test_timer_metrics_last_five_minutes_and_unlimited(db_session, monkeypatch):
    workspace = Workspace(id="ws-capture-timer", name="Capture Timer", slug="capture-timer")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    limited = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Timed session",
        objective="Capture expert decisions.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        plan_mode="free_conversation",
    )
    limited = start_session(db_session, workspace_id=workspace.id, session_id=limited.id)
    started_at = limited.started_at
    assert started_at is not None

    class FixedDateTime:
        @classmethod
        def utcnow(cls):
            from datetime import timedelta

            return started_at + timedelta(minutes=16)

    monkeypatch.setattr("app.services.knowledge_capture.datetime", FixedDateTime)
    metrics = serialize_session(limited)["metrics"]
    assert metrics["timer_phase"] == "last_5_minutes"
    assert metrics["last_minutes_alert"] is True
    assert metrics["remaining_seconds"] <= 5 * 60

    unlimited = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Unlimited session",
        objective="Capture expert decisions.",
        expert_profile="Senior field engineer",
        duration_minutes=0,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        plan_mode="free_conversation",
    )
    unlimited = start_session(db_session, workspace_id=workspace.id, session_id=unlimited.id)
    unlimited_metrics = serialize_session(unlimited)["metrics"]
    assert unlimited_metrics["unlimited_duration"] is True
    assert unlimited_metrics["timer_phase"] == "running"
    assert unlimited_metrics["remaining_seconds"] is None
    assert unlimited_metrics["last_minutes_alert"] is False


def test_build_session_closure_sheet_and_extend(db_session):
    workspace = Workspace(id="ws-capture-closure", name="Capture Closure", slug="capture-closure")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Closure sheet",
        objective="Décisions sur la ligne BBA120.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        plan_mode="free_conversation",
    )
    session = start_session(db_session, workspace_id=workspace.id, session_id=session.id)
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        text="On retient 180/min seulement si le papier est trop humide, sinon exception terrain.",
    )
    session_payload = append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        text="La décision vient du retour d'expérience atelier, pas du manuel seul.",
    )["session"]
    from app.models.expert_capture import ExpertCaptureSession

    loaded = db_session.query(ExpertCaptureSession).filter(ExpertCaptureSession.id == session_payload["id"]).first()
    events = list_capture_events(db_session, workspace_id=workspace.id, session_id=loaded.id)
    sheet = build_session_closure_sheet(loaded, events)
    assert "Fiche fin de session" in sheet["markdown"]
    assert "Sujets abordés" in sheet["markdown"]
    assert "Faits capturés" in sheet["markdown"]
    assert "Points non résolus" in sheet["markdown"]
    assert sheet["captured_facts"]

    extended = extend_capture_session(
        db_session,
        workspace_id=workspace.id,
        session_id=loaded.id,
        extension_minutes=15,
        actor_user_id="test-user",
    )
    assert extended.metrics["duration_extension_minutes"] == 15
    assert extended.metrics["session_end_pending"] is False


def test_session_complete_intent_generates_closure_sheet(db_session):
    workspace = Workspace(id="ws-capture-voice-end", name="Capture Voice End", slug="capture-voice-end")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Voice end",
        objective="Capture expert decisions.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        plan_mode="free_conversation",
    )
    session = start_session(db_session, workspace_id=workspace.id, session_id=session.id)
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        text="On valide le réglage standard à 160/min pour ce grade de papier.",
    )
    intent = classify_conversation_intent(text="C'est terminé pour aujourd'hui.")
    assert intent["intent"] == "session_complete"
    step = process_conversation_step(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        client_turn_id="turn-end",
        text="C'est terminé pour aujourd'hui.",
        question_id=None,
        retrieval_event_id=None,
        interruption_of_event_id=None,
        last_proposal_id=None,
        actor_user_id="test-user",
    )
    assert step["action_taken"] == "closure_sheet_generated"
    assert step["closure_sheet"]["markdown"]
    assert step["next_prompt"] is None
    assert step["session"]["metrics"]["session_end_pending"] is True


def test_andritz_knowledge_sheet_template_for_technical_domain(db_session):
    workspace = Workspace(id="ws-capture-andritz-sheet", name="Capture Andritz", slug="capture-andritz-sheet")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Andritz SPL",
        objective="Décision sur notices techniques SPL.",
        expert_profile="Expert process",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        plan_mode="free_conversation",
        capture_domain="technical",
    )
    session = start_session(db_session, workspace_id=workspace.id, session_id=session.id)
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        text="Décision : on valide le réglage si la température dépasse 85°C, sauf en cas de papier recyclé.",
    )
    from app.models.expert_capture import ExpertCaptureSession

    loaded = db_session.query(ExpertCaptureSession).filter(ExpertCaptureSession.id == session.id).first()
    events = list_capture_events(db_session, workspace_id=workspace.id, session_id=loaded.id)
    payload = structure_capture_payload(loaded, events)
    # The technical domain now resolves to the canonical industrial template id.
    assert payload["knowledge_sheet_template"] == INDUSTRIAL_TEMPLATE_ID
    content = payload["recommended_ingestion"]["content"]
    assert "## Contexte" in content
    assert "## Décision" in content
    assert "## Owner" in content
    assert resolve_knowledge_sheet_template(loaded) == INDUSTRIAL_TEMPLATE_ID
    # ``andritz_knowledge_v1`` stays a backward-compatible alias that still
    # resolves to the same industrial knowledge sheet.
    assert ANDRITZ_TEMPLATE_ID != INDUSTRIAL_TEMPLATE_ID
    alias_sheet = build_knowledge_sheet_content(
        ANDRITZ_TEMPLATE_ID,
        loaded,
        payload["captured_facts"],
        [],
        transcript=loaded.transcript or [],
    )
    assert "Fiche connaissance" in alias_sheet
    direct = build_andritz_knowledge_sheet(
        loaded,
        payload["captured_facts"],
        transcript=loaded.transcript or [],
    )
    assert "Fiche connaissance" in direct


# --------------------------------------------------------------------------- #
# FINAL phase (section.finish / capture.finish) + targeted answer re-synthesis #
# --------------------------------------------------------------------------- #


def _final_phase_session(db_session, workspace, user):
    """A started, approved ai_plan session with one expert turn tagged to the
    first plan subtopic — the substrate for the FINAL-phase tests."""
    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Réglages ligne",
        objective="Capturer les réglages de vitesse sur la ligne.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        created_by_user_id=user.id,
        **_guided_plan_kwargs(),
    )
    session = _approve(db_session, workspace, session)
    session = start_session(db_session, workspace_id=workspace.id, session_id=session.id)
    topic = (session.plan.get("topics") or [])[0]
    subtopic = (topic.get("subtopics") or [])[0]
    return session, topic["id"], subtopic["id"]


@pytest.mark.asyncio
async def test_finalize_capture_section_builds_section_synthesis(db_session, monkeypatch):
    """section.finish (C1/C2): the FINAL per-section pass reformulates the captured
    statements (deterministic fallback without an LLM) and stores the synthesis on
    the plan under ``section_synthesis``."""
    import app.services.knowledge_capture as kc

    async def _no_retrieval(*_a, **_k):
        return ([], [], [])

    monkeypatch.setattr(kc, "_retrieve_context_chunks_async", _no_retrieval)

    workspace = Workspace(id="ws-final-sec", name="Final Sec", slug="final-sec")
    user = User(id="user-final-sec", username="fs@datategy.local", email="fs@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session, topic_id, subtopic_id = _final_phase_session(db_session, workspace, user)
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        text="La vitesse nominale des rouleaux est de 120 par minute selon le grade.",
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        actor_user_id=user.id,
    )

    entry = await finalize_capture_section(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        workspace_slug=workspace.slug,
    )

    assert entry.get("skipped") is not True
    assert entry["statement_count"] == 1
    assert "120 par minute" in entry["synthesis"]

    reloaded = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    stored = (reloaded.plan or {}).get("section_synthesis") or {}
    assert subtopic_id in stored
    assert "120 par minute" in stored[subtopic_id]["synthesis"]


@pytest.mark.asyncio
async def test_finalize_capture_builds_proposal_with_plan_structure(db_session, monkeypatch):
    """capture.finish: closes every section and builds a proposal whose
    ``plan_structure`` carries the per-section FINAL synthesis."""
    import app.services.knowledge_capture as kc

    async def _no_retrieval(*_a, **_k):
        return ([], [], [])

    monkeypatch.setattr(kc, "_retrieve_context_chunks_async", _no_retrieval)

    workspace = Workspace(id="ws-final-cap", name="Final Cap", slug="final-cap")
    user = User(id="user-final-cap", username="fc@datategy.local", email="fc@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session, topic_id, subtopic_id = _final_phase_session(db_session, workspace, user)
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        text="On contrôle la pression hydraulique à 12 bar avant le démarrage.",
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        actor_user_id=user.id,
    )

    proposal = await finalize_capture(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        workspace_slug=workspace.slug,
        created_by_user_id=user.id,
    )

    assert proposal.proposal.get("plan_structure")
    content = proposal.proposal["recommended_ingestion"]["content"]
    assert "12 bar" in content


def _multi_section_session(db_session, workspace, user, texts_by_topic: dict):
    """A started session whose plan carries one flat topic per key of
    ``texts_by_topic``, each with one tagged expert turn — the substrate for
    the concurrent FINAL-phase tests."""
    from sqlalchemy.orm.attributes import flag_modified

    session, _topic_id, _subtopic_id = _final_phase_session(db_session, workspace, user)
    loaded = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    plan = dict(loaded.plan or {})
    plan["topics"] = [
        {"id": topic_id, "title": f"Sujet {topic_id}", "subtopics": []}
        for topic_id in texts_by_topic
    ]
    loaded.plan = plan
    flag_modified(loaded, "plan")
    db_session.commit()
    for topic_id, text in texts_by_topic.items():
        append_turn(
            db_session,
            workspace_id=workspace.id,
            session_id=session.id,
            speaker="expert",
            text=text,
            topic_id=topic_id,
            actor_user_id=user.id,
        )
    return session


@pytest.mark.asyncio
async def test_finalize_capture_concurrent_sections_all_synthesized(db_session, monkeypatch):
    """capture.finish processes sections with bounded concurrency: every section
    still gets its ``section_synthesis`` entry, the per-section reformulations
    actually overlap, and all DB writes land after the concurrent phase."""
    import asyncio as aio

    import app.services.capture_knowledge_oracle as oracle
    import app.services.knowledge_capture as kc

    async def _no_retrieval(*_a, **_k):
        return ([], [], [])

    monkeypatch.setattr(kc, "_retrieve_context_chunks_async", _no_retrieval)

    active = {"now": 0, "max": 0}

    async def _slow_reformulate(**kwargs):
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        await aio.sleep(0.05)
        active["now"] -= 1
        return f"Synthèse: {' '.join(kwargs['statements'])}"

    monkeypatch.setattr(oracle, "reformulate_section_async", _slow_reformulate)

    workspace = Workspace(id="ws-final-conc", name="Final Conc", slug="final-conc")
    user = User(id="user-final-conc", username="fcc@datategy.local", email="fcc@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    texts = {
        "t-conc-1": "Les rouleaux se règlent à 7 millimètres d'entrefer.",
        "t-conc-2": "La pression hydraulique doit atteindre 12 bar.",
        "t-conc-3": "La vitesse nominale est de 120 par minute.",
    }
    session = _multi_section_session(db_session, workspace, user, texts)

    proposal = await finalize_capture(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        workspace_slug=workspace.slug,
        created_by_user_id=user.id,
    )

    reloaded = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    stored = (reloaded.plan or {}).get("section_synthesis") or {}
    for topic_id, text in texts.items():
        assert topic_id in stored, f"missing synthesis for {topic_id} in {sorted(stored)}"
        assert text in stored[topic_id]["synthesis"]
    # The per-section LLM work genuinely overlapped (bounded concurrency).
    assert active["max"] > 1
    content = proposal.proposal["recommended_ingestion"]["content"]
    assert "12 bar" in content and "120 par minute" in content


@pytest.mark.asyncio
async def test_finalize_capture_section_failure_does_not_abort_others(db_session, monkeypatch):
    """One failing section must not abort the FINAL pass: the other sections
    keep their synthesis and the proposal is still built."""
    import app.services.capture_knowledge_oracle as oracle
    import app.services.knowledge_capture as kc

    async def _no_retrieval(*_a, **_k):
        return ([], [], [])

    monkeypatch.setattr(kc, "_retrieve_context_chunks_async", _no_retrieval)

    async def _flaky_reformulate(**kwargs):
        if "12 bar" in " ".join(kwargs["statements"]):
            raise RuntimeError("boom: section reformulation failed")
        return f"Synthèse: {' '.join(kwargs['statements'])}"

    monkeypatch.setattr(oracle, "reformulate_section_async", _flaky_reformulate)

    workspace = Workspace(id="ws-final-fail", name="Final Fail", slug="final-fail")
    user = User(id="user-final-fail", username="ffl@datategy.local", email="ffl@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    texts = {
        "t-fail-1": "Les rouleaux se règlent à 7 millimètres d'entrefer.",
        "t-fail-2": "La pression hydraulique doit atteindre 12 bar.",
        "t-fail-3": "La vitesse nominale est de 120 par minute.",
    }
    session = _multi_section_session(db_session, workspace, user, texts)

    proposal = await finalize_capture(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        workspace_slug=workspace.slug,
        created_by_user_id=user.id,
    )

    reloaded = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    stored = (reloaded.plan or {}).get("section_synthesis") or {}
    assert "t-fail-2" not in stored
    assert "t-fail-1" in stored and "t-fail-3" in stored
    assert "7 millimètres" in stored["t-fail-1"]["synthesis"]
    assert "120 par minute" in stored["t-fail-3"]["synthesis"]
    # The proposal is still produced from the surviving sections.
    content = proposal.proposal["recommended_ingestion"]["content"]
    assert "120 par minute" in content


@pytest.mark.asyncio
async def test_answer_proposal_open_question_resynthesizes_only_that_section(db_session, monkeypatch):
    """POST .../open-questions/{id}/answer (c3): injects the answer into the right
    section, marks the question answered, and re-synthesizes ONLY that section."""
    import app.services.knowledge_capture as kc

    async def _no_retrieval(*_a, **_k):
        return ([], [], [])

    monkeypatch.setattr(kc, "_retrieve_context_chunks_async", _no_retrieval)

    workspace = Workspace(id="ws-answer", name="Answer", slug="answer")
    user = User(id="user-answer", username="ans@datategy.local", email="ans@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session, topic_id, subtopic_id = _final_phase_session(db_session, workspace, user)
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        text="La vitesse nominale est de 120 par minute.",
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        actor_user_id=user.id,
    )
    proposal = create_update_proposal(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        created_by_user_id=user.id,
    )
    payload = dict(proposal.proposal or {})
    payload["open_questions"] = [
        {
            "gap_id": "speed-exception",
            "follow_up": "Quelle vitesse en exception terrain ?",
            "text": "Quelle vitesse en exception terrain ?",
            "topic_id": topic_id,
            "subtopic_id": subtopic_id,
            "status": "open",
        }
    ]
    proposal.proposal = payload
    db_session.commit()

    updated = await answer_proposal_open_question(
        db_session,
        workspace_id=workspace.id,
        proposal_id=proposal.id,
        question_id="speed-exception",
        text="En exception terrain on monte à 180 par minute.",
        actor_user_id=user.id,
        actor_label=user.email,
        workspace_slug=workspace.slug,
    )

    question = updated.proposal["open_questions"][0]
    assert question["status"] == "answered"
    assert "180" in question["answer_text"]
    # The answer was injected into the section and the report re-synthesized.
    content = updated.proposal["recommended_ingestion"]["content"]
    assert "180 par minute" in content
    assert updated.proposal.get("plan_structure")


@pytest.mark.asyncio
async def test_answer_proposal_open_question_unknown_id_does_not_mutate(db_session):
    workspace = Workspace(id="ws-answer-unknown", name="Answer Unknown", slug="answer-unknown")
    user = User(id="user-answer-unknown", username="answer-unknown@datategy.local", email="answer-unknown@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session, topic_id, subtopic_id = _final_phase_session(db_session, workspace, user)
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        text="La vitesse nominale est de 120 par minute.",
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        actor_user_id=user.id,
    )
    proposal = create_update_proposal(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        created_by_user_id=user.id,
    )
    payload_before = dict(proposal.proposal or {})
    payload_before["open_questions"] = [
        {
            "gap_id": "speed-exception",
            "follow_up": "Quelle vitesse en exception terrain ?",
            "text": "Quelle vitesse en exception terrain ?",
            "topic_id": topic_id,
            "subtopic_id": subtopic_id,
            "status": "open",
        }
    ]
    proposal.proposal = payload_before
    db_session.commit()
    transcript_before = list(session.transcript or [])

    with pytest.raises(ValueError, match="Open question not found"):
        await answer_proposal_open_question(
            db_session,
            workspace_id=workspace.id,
            proposal_id=proposal.id,
            question_id="missing-question",
            text="En exception terrain on monte à 180 par minute.",
            actor_user_id=user.id,
            actor_label=user.email,
            workspace_slug=workspace.slug,
        )

    db_session.refresh(session)
    db_session.refresh(proposal)
    assert session.transcript == transcript_before
    question = proposal.proposal["open_questions"][0]
    assert question["status"] == "open"
    assert "answer_text" not in question
    assert proposal.proposal["recommended_ingestion"]["content"] == payload_before["recommended_ingestion"]["content"]


@pytest.mark.asyncio
async def test_gateway_section_finish_emits_single_timeline_relance(db_session, monkeypatch):
    """section.finish over WS: exactly ONE conversation.step timeline relance with
    the fixed prompt, NO pushed content questions, and the section synthesis stored."""
    from app.services import voice_session_gateway as gw
    import app.services.knowledge_capture as kc

    async def _no_retrieval(*_a, **_k):
        return ([], [], [])

    monkeypatch.setattr(kc, "_retrieve_context_chunks_async", _no_retrieval)

    workspace = Workspace(id="ws-sec-finish", name="Sec Finish", slug="sec-finish")
    user = User(id="user-sec-finish", username="sf@datategy.local", email="sf@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session, topic_id, subtopic_id = _final_phase_session(db_session, workspace, user)
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        text="Le réglage tambour se fait à 7 millimètres d'entrefer.",
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        actor_user_id=user.id,
    )

    sent: list[tuple] = []

    class FakeWebSocket:
        async def send_json(self, message):
            sent.append((message.get("type"), message.get("payload")))

    websocket = FakeWebSocket()
    gateway = gw.VoiceSessionGateway()
    state = gw.VoiceSessionState(session_id=session.id, mode="guided", tandem_oracle_enabled=True)
    state.active_topic_id = topic_id
    state.active_subtopic_id = subtopic_id

    await gateway._handle_event(
        websocket,
        db_session,
        user=user,
        workspace=workspace,
        state=state,
        event={"type": "section.finish", "payload": {"topic_id": topic_id, "subtopic_id": subtopic_id}},
    )
    # The FINAL-phase finalization is offloaded (fire-and-forget) so the receive
    # loop never blocks behind its multi-LLM work; drain it before asserting.
    await asyncio.gather(*list(state.finalize_tasks))

    steps = [p for t, p in sent if t == "conversation.step"]
    assert len(steps) == 1
    step = steps[0]
    assert step["next_prompt"] == gw.SECTION_FINISH_RELANCE
    assert step["relance"]["text"] == gw.SECTION_FINISH_RELANCE
    assert step["open_questions"] == []
    assert step["section_synthesis"]["statement_count"] == 1

    reloaded = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    assert subtopic_id in ((reloaded.plan or {}).get("section_synthesis") or {})


@pytest.mark.asyncio
async def test_gateway_capture_finish_emits_proposal(db_session, monkeypatch):
    """capture.finish over WS: builds the proposal and emits proposal-ready via
    conversation.step (capture_finished=True, proposal payload present)."""
    from app.services import voice_session_gateway as gw
    import app.services.knowledge_capture as kc

    async def _no_retrieval(*_a, **_k):
        return ([], [], [])

    monkeypatch.setattr(kc, "_retrieve_context_chunks_async", _no_retrieval)

    workspace = Workspace(id="ws-cap-finish", name="Cap Finish", slug="cap-finish")
    user = User(id="user-cap-finish", username="cf@datategy.local", email="cf@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session, topic_id, subtopic_id = _final_phase_session(db_session, workspace, user)
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        text="On valide le démarrage quand la pression atteint 12 bar.",
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        actor_user_id=user.id,
    )

    sent: list[tuple] = []

    class FakeWebSocket:
        async def send_json(self, message):
            sent.append((message.get("type"), message.get("payload")))

    websocket = FakeWebSocket()
    gateway = gw.VoiceSessionGateway()
    state = gw.VoiceSessionState(session_id=session.id, mode="guided", tandem_oracle_enabled=True)

    await gateway._handle_event(
        websocket,
        db_session,
        user=user,
        workspace=workspace,
        state=state,
        event={"type": "capture.finish", "payload": {}},
    )
    # Same offload as section.finish: drain the background finalization task.
    await asyncio.gather(*list(state.finalize_tasks))

    step = next((p for t, p in sent if t == "conversation.step"), None)
    assert step is not None
    assert step["capture_finished"] is True
    assert step["proposal"] and step["proposal"].get("id")
    assert step["open_questions"] == []
    # The heavy FINAL pass streams honest stage events for the loader, and the
    # proposal-ready step always arrives AFTER the progress stream.
    progress = [p for t, p in sent if t == "capture.finalize.progress"]
    assert progress, "capture.finish must stream capture.finalize.progress events"
    stages = [p.get("stage") for p in progress]
    assert "start" in stages
    assert "section" in stages
    assert "report" in stages
    assert sent.index(("conversation.step", step)) > max(
        i for i, (t, _p) in enumerate(sent) if t == "capture.finalize.progress"
    )


# --------------------------------------------------------------------------- #
# FINAL pipeline rework: dedupe, Tier-2 glossary alignment, thematic blocks,   #
# synthesis-based report and progress stages                                   #
# --------------------------------------------------------------------------- #


def test_dedupe_statements_removes_repeated_and_rephrased_content():
    from app.services.capture_knowledge_oracle import dedupe_statements

    statements = [
        "La vitesse nominale des rouleaux est de 120 par minute.",
        "Donc la vitesse nominale des rouleaux est bien de 120 par minute.",
        "En cas d'exception terrain on monte à 180 par minute.",
        "La vitesse nominale des rouleaux est de 120 par minute selon le manuel constructeur.",
    ]
    deduped, removed = dedupe_statements(statements)
    assert removed == 2
    assert len(deduped) == 2
    # The richest variant of the duplicated content wins.
    assert any("manuel constructeur" in s for s in deduped)
    assert any("180 par minute" in s for s in deduped)


@pytest.mark.asyncio
async def test_finalize_capture_section_dedupes_and_wires_tier2_glossary(db_session, monkeypatch):
    """The FINAL per-section pass must (a) dedupe repeated turns before the
    reformulation, (b) hand the resolved Andritz Tier-2 glossary terms to the
    reformulation prompt, and (c) store displayable KB sources on the entry."""
    import app.services.knowledge_capture as kc
    import app.services.capture_knowledge_oracle as oracle

    async def _retrieval(*_a, **_k):
        return (
            ["La carde KD724 tourne à 120 par minute en vitesse nominale."],
            [
                {
                    "document_id": "doc-carde-1",
                    "title": "Manuel carde KD724",
                    "collection": "andritz-notices",
                    "source": "manuel_carde.pdf",
                }
            ],
            [0.92],
        )

    monkeypatch.setattr(kc, "_retrieve_context_chunks_async", _retrieval)

    recorded: dict = {}

    async def _fake_reformulate(**kwargs):
        recorded.update(kwargs)
        return "Synthèse restructurée de la section."

    monkeypatch.setattr(oracle, "reformulate_section_async", _fake_reformulate)

    workspace = Workspace(
        id="ws-final-glossary",
        name="Final Glossary",
        slug="final-glossary",
        settings={"voice": {"transcript_glossary": ["carde", "KD724"]}},
    )
    user = User(id="user-final-glossary", username="fg@datategy.local", email="fg@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session, topic_id, subtopic_id = _final_phase_session(db_session, workspace, user)
    for text in (
        "La vitesse nominale des rouleaux est de 120 par minute.",
        "Donc la vitesse nominale des rouleaux est de 120 par minute.",
    ):
        append_turn(
            db_session,
            workspace_id=workspace.id,
            session_id=session.id,
            speaker="expert",
            text=text,
            topic_id=topic_id,
            subtopic_id=subtopic_id,
            actor_user_id=user.id,
        )

    entry = await finalize_capture_section(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        workspace_slug=workspace.slug,
    )

    # (a) dedupe before the reformulation
    assert entry["raw_statement_count"] == 2
    assert entry["statement_count"] == 1
    assert entry["dedup_removed"] == 1
    assert len(recorded["statements"]) == 1
    # (b) Tier-2 glossary wired into the FINAL reformulation
    assert "carde" in recorded["glossary_terms"]
    assert "KD724" in recorded["glossary_terms"]
    assert entry["glossary_term_count"] >= 2
    # (c) displayable sources (title + document identity), not raw ids only
    assert entry["sources"]
    assert entry["sources"][0]["title"] == "Manuel carde KD724"
    assert entry["sources"][0]["document_id"] == "doc-carde-1"
    assert entry["sources"][0]["collection"] == "andritz-notices"


@pytest.mark.asyncio
async def test_finalize_capture_free_conversation_structures_thematic_blocks(db_session, monkeypatch):
    """capture.finish on a planless (free conversation) session must still
    structure the expression: thematic blocks become plan topics, expert turns
    are tagged, and the report is assembled from the per-theme syntheses."""
    import app.services.knowledge_capture as kc

    async def _no_retrieval(*_a, **_k):
        return ([], [], [])

    monkeypatch.setattr(kc, "_retrieve_context_chunks_async", _no_retrieval)

    async def _fake_themes(*, workspace_id, statements, max_themes=6):
        assert len(statements) == 2
        return [
            {"id": "theme-01", "title": "Réglage des rouleaux", "statement_indexes": [0]},
            {"id": "theme-02", "title": "Pression hydraulique", "statement_indexes": [1]},
        ]

    monkeypatch.setattr(kc, "derive_thematic_blocks_async", _fake_themes)

    workspace = Workspace(id="ws-final-themes", name="Final Themes", slug="final-themes")
    user = User(id="user-final-themes", username="ft@datategy.local", email="ft@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Conversation libre maintenance",
        objective="Capturer les savoirs maintenance sans plan.",
        expert_profile="Senior field engineer",
        duration_minutes=0,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        created_by_user_id=user.id,
        plan_mode="free_conversation",
    )
    session = start_session(db_session, workspace_id=workspace.id, session_id=session.id)
    for text in (
        "Les rouleaux se règlent à 7 millimètres d'entrefer.",
        "La pression hydraulique doit atteindre 12 bar avant démarrage.",
    ):
        append_turn(
            db_session,
            workspace_id=workspace.id,
            session_id=session.id,
            speaker="expert",
            text=text,
            actor_user_id=user.id,
        )

    proposal = await finalize_capture(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        workspace_slug=workspace.slug,
        created_by_user_id=user.id,
    )

    reloaded = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    topics = (reloaded.plan or {}).get("topics") or []
    assert [t["title"] for t in topics] == ["Réglage des rouleaux", "Pression hydraulique"]
    assert all(t.get("generated_by") == "final_thematic" for t in topics)
    expert_turns = [t for t in reloaded.transcript if t.get("speaker") == "expert"]
    assert [t.get("topic_id") for t in expert_turns] == ["theme-01", "theme-02"]
    # The report follows the thematic structure with the per-theme synthesis.
    content = proposal.proposal["recommended_ingestion"]["content"]
    assert "## Réglage des rouleaux" in content
    assert "## Pression hydraulique" in content
    assert "7 millimètres" in content
    assert "12 bar" in content


@pytest.mark.asyncio
async def test_finalize_capture_reports_progress_stages_and_synthesis_report(db_session, monkeypatch):
    """finalize_capture must stream honest stage events (restructure, per-section
    dedupe/vocabulary/reformulate, report, done) and the proposal report must be
    assembled from the restructured syntheses (with their sources), not the raw
    fact template."""
    import app.services.knowledge_capture as kc

    async def _retrieval(*_a, **_k):
        return (
            ["Extrait notice pression hydraulique 12 bar."],
            [{"document_id": "doc-press-1", "title": "Notice hydraulique", "collection": "andritz-notices"}],
            [0.9],
        )

    monkeypatch.setattr(kc, "_retrieve_context_chunks_async", _retrieval)

    workspace = Workspace(id="ws-final-progress", name="Final Progress", slug="final-progress")
    user = User(id="user-final-progress", username="fp@datategy.local", email="fp@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session, topic_id, subtopic_id = _final_phase_session(db_session, workspace, user)
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        text="On contrôle la pression hydraulique à 12 bar avant le démarrage.",
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        actor_user_id=user.id,
    )

    events: list[dict] = []

    async def _progress(payload):
        events.append(payload)

    proposal = await finalize_capture(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        workspace_slug=workspace.slug,
        created_by_user_id=user.id,
        progress=_progress,
    )

    stages = [event["stage"] for event in events]
    for expected in ("restructure", "section", "dedupe", "vocabulary", "reformulate", "report", "done"):
        assert expected in stages, f"missing stage {expected} in {stages}"
    assert stages.index("restructure") < stages.index("section") < stages.index("report") < stages.index("done")
    assert all(event.get("label") for event in events)

    # Report assembled from the synthesis path (sources footer with titles).
    content = proposal.proposal["recommended_ingestion"]["content"]
    assert "12 bar" in content
    assert "Sources : Notice hydraulique" in content
    # plan_structure carries the section sources for the fiche UI.
    structure = proposal.proposal["plan_structure"]
    nodes = []
    for topic in structure["topics"]:
        nodes.append(topic)
        nodes.extend(topic.get("subtopics") or [])
    assert any((node.get("sources") or [{}])[0].get("title") == "Notice hydraulique" for node in nodes)


def test_backfill_turn_plan_tags_assigns_default_section(db_session):
    """Untagged expert turns must be mappable to the active/default plan section."""
    import app.services.knowledge_capture as kc

    workspace = Workspace(id="ws-backfill", name="Backfill", slug="backfill")
    user = User(id="user-backfill", username="bf@datategy.local", email="bf@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session, topic_id, subtopic_id = _final_phase_session(db_session, workspace, user)
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        text="Procédure machine ABC avant démarrage.",
        actor_user_id=user.id,
    )
    loaded = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    transcript = [dict(turn) for turn in (loaded.transcript or [])]
    for turn in transcript:
        if turn.get("speaker") == "expert":
            turn.pop("topic_id", None)
            turn.pop("subtopic_id", None)
    loaded.transcript = transcript
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(loaded, "transcript")
    db_session.commit()

    updated = kc._backfill_turn_plan_tags(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
    )
    expert = next(t for t in updated.transcript if t.get("speaker") == "expert")
    assert expert.get("topic_id") == topic_id
    assert expert.get("subtopic_id") == subtopic_id


@pytest.mark.asyncio
async def test_finalize_capture_plan_mode_reformulates_untagged_turns(db_session, monkeypatch):
    """Plan-mode capture.finish must run the same FINAL reformulation pipeline even
    when turns were committed without explicit topic/subtopic tags (frontend
    syncVoice=false on first section)."""
    import app.services.knowledge_capture as kc

    async def _no_retrieval(*_a, **_k):
        return ([], [], [])

    monkeypatch.setattr(kc, "_retrieve_context_chunks_async", _no_retrieval)

    workspace = Workspace(id="ws-plan-untagged", name="Plan Untagged", slug="plan-untagged")
    user = User(id="user-plan-untagged", username="pu@datategy.local", email="pu@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session, topic_id, subtopic_id = _final_phase_session(db_session, workspace, user)
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        text="Donc nous voilà partis, la machine ABC demande un contrôle des procédures avant démarrage.",
        actor_user_id=user.id,
    )
    # Simulate the regression: turns committed before section.select / voice sync.
    loaded = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    transcript = [dict(turn) for turn in (loaded.transcript or [])]
    for turn in transcript:
        if turn.get("speaker") == "expert":
            turn.pop("topic_id", None)
            turn.pop("subtopic_id", None)
    loaded.transcript = transcript
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(loaded, "transcript")
    db_session.commit()

    proposal = await finalize_capture(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        workspace_slug=workspace.slug,
        created_by_user_id=user.id,
    )

    reloaded = get_session(db_session, workspace_id=workspace.id, session_id=session.id)
    stored = (reloaded.plan or {}).get("section_synthesis") or {}
    assert subtopic_id in stored
    assert stored[subtopic_id].get("synthesis")
    content = proposal.proposal["recommended_ingestion"]["content"]
    structure = proposal.proposal["plan_structure"]
    subtopic_nodes = [
        subtopic
        for topic in structure.get("topics") or []
        for subtopic in (topic.get("subtopics") or [])
        if subtopic.get("subtopic_id") == subtopic_id
    ]
    assert subtopic_nodes
    assert subtopic_nodes[0].get("synthesis")
    assert "machine ABC" in content or "procédures" in content
    assert "## Contexte" not in content


def test_build_proposal_open_questions_prefers_live_and_dedupes_generic(db_session):
    """Report open questions must reuse LIVE/grounded oracle questions and drop
    duplicate generic contradiction placeholders from evaluations."""
    import app.services.knowledge_capture as kc

    workspace = Workspace(id="ws-oq-dedupe", name="OQ Dedupe", slug="oq-dedupe")
    user = User(id="user-oq-dedupe", username="oq@datategy.local", email="oq@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Procédures machine",
        objective="Capturer les procédures machine ABC.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        created_by_user_id=user.id,
        **_guided_plan_kwargs(),
    )
    session = _approve(db_session, workspace, session)
    session = start_session(db_session, workspace_id=workspace.id, session_id=session.id)
    topic = (session.plan.get("topics") or [])[0]
    subtopic = (topic.get("subtopics") or [])[0]

    plan = dict(session.plan or {})
    plan["live_open_questions"] = [
        {
            "id": "live-abc-01",
            "text": "Quelle est la procédure exacte de contrôle sur la machine ABC avant démarrage ?",
            "topic_id": topic["id"],
            "subtopic_id": subtopic["id"],
            "source": "oracle_live",
            "status": "open",
        }
    ]
    plan["section_synthesis"] = {
        subtopic["id"]: {
            "open_questions": [
                {
                    "id": "grounded-abc-01",
                    "text": "Quelle est la procédure exacte de contrôle sur la machine ABC avant démarrage ?",
                    "topic_id": topic["id"],
                    "subtopic_id": subtopic["id"],
                    "source": "oracle_grounded",
                    "status": "open",
                }
            ]
        }
    }
    session.plan = plan
    session.evaluations = [
        {
            "verdict": "contradiction_or_update",
            "follow_up": kc._GENERIC_CONTRADICTION_FOLLOWUP,
            "gap_id": "contradiction_or_update",
        },
        {
            "verdict": "contradiction_or_update",
            "follow_up": kc._GENERIC_CONTRADICTION_FOLLOWUP,
            "gap_id": "contradiction_or_update-2",
        },
    ]
    db_session.commit()
    db_session.refresh(session)

    open_questions = kc._build_proposal_open_questions(session, plan, session.evaluations)
    texts = [item["text"] for item in open_questions]
    assert len(texts) == 1
    assert "machine ABC" in texts[0]
    assert kc._GENERIC_CONTRADICTION_FOLLOWUP not in texts

    payload = structure_capture_payload(session, [])
    proposal_texts = [item.get("text") or item.get("follow_up") for item in payload["open_questions"]]
    assert len(proposal_texts) == 1
    assert "machine ABC" in proposal_texts[0]


def test_attach_section_synthesis_surfaces_unscoped_session_entry():
    """No-plan resilience: when the FINAL pass stored its synthesis under the
    unscoped "session" key (thematic structuring yielded no topics), the
    structured report must still surface the reformulated text, its KB sources
    and grounded questions as a single pseudo-section instead of regressing to
    the verbatim transcript."""
    import app.services.knowledge_capture as kc

    plan = {
        "section_synthesis": {
            "session": {
                "section_key": "session",
                "section_label": "Maintenance des cardes",
                "synthesis": "Synthèse reformulée de la capture libre.",
                "sources": [{"title": "Doc A", "document_id": "doc-a", "preview": "extrait"}],
                "open_questions": [{"id": "grounded-sec-01", "text": "Quelle périodicité exacte ?", "status": "open"}],
            }
        }
    }
    structure = kc._structure_facts_by_plan({}, [{"text": "fait brut hors plan"}])
    assert structure["topics"] == []
    result = kc._attach_section_synthesis(structure, plan)
    topics = result["topics"]
    assert len(topics) == 1
    assert topics[0]["title"] == "Maintenance des cardes"
    assert topics[0]["synthesis"] == "Synthèse reformulée de la capture libre."
    assert topics[0]["sources"][0]["title"] == "Doc A"
    assert topics[0]["open_questions"][0]["text"] == "Quelle périodicité exacte ?"
    # The previously-unassigned facts move under the pseudo-section.
    assert result["unassigned"] == []
    assert topics[0]["facts"][0]["text"] == "fait brut hors plan"


def test_attach_section_synthesis_session_entry_ignored_when_topics_exist():
    import app.services.knowledge_capture as kc

    plan = {
        "topics": [{"id": "t1", "title": "Sujet 1", "subtopics": []}],
        "section_synthesis": {
            "t1": {"synthesis": "Synthèse du sujet 1.", "sources": []},
            "session": {"synthesis": "Ne doit pas écraser.", "sources": []},
        },
    }
    structure = kc._structure_facts_by_plan(plan, [])
    result = kc._attach_section_synthesis(structure, plan)
    assert len(result["topics"]) == 1
    assert result["topics"][0]["synthesis"] == "Synthèse du sujet 1."


def test_create_update_proposal_free_conversation_materializes_session_topic(db_session):
    workspace = Workspace(id="ws-free-direct-topic", name="Free Direct Topic", slug="free-direct-topic")
    user = User(id="user-free-direct-topic", username="free-direct@datategy.local", email="free-direct@datategy.local")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Capture libre directe",
        objective="Capturer une fiche sans plan.",
        expert_profile="Senior field engineer",
        duration_minutes=0,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        created_by_user_id=user.id,
        plan_mode="free_conversation",
    )
    session = start_session(db_session, workspace_id=workspace.id, session_id=session.id)
    append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        speaker="expert",
        text="La pompe de reprise doit être purgée deux minutes avant redémarrage terrain.",
        actor_user_id=user.id,
    )

    proposal = create_update_proposal(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        created_by_user_id=user.id,
    )

    structure = proposal.proposal["plan_structure"]
    assert structure["unassigned"] == []
    assert structure["topics"][0]["topic_id"] == "session"
    assert structure["topics"][0]["title"] == "Synthèse de la capture"
    assert structure["topics"][0]["facts"][0]["text"].startswith("La pompe de reprise")


def test_silent_capture_defers_transcript_rewrite_but_readers_stay_complete(db_session):
    """Etape 7 / Scope complet: a silent capture turn (``persist_transcript=False``)
    must NOT rewrite the growing transcript column every turn. The append-only event
    ledger is the source of truth and every reader still observes a complete,
    correctly-ordered transcript with the same turn shape."""
    import app.services.knowledge_capture as kc

    workspace = Workspace(id="ws-silent-transcript", name="Silent Transcript", slug="silent-transcript")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    session = create_capture_plan(
        db_session,
        workspace_id=workspace.id,
        title="Silent capture materialization",
        objective="Capture tacit troubleshooting knowledge for the silent path.",
        expert_profile="Senior field engineer",
        duration_minutes=20,
        context_id=None,
        system_id=None,
        knowledge_refs=[],
        **_guided_plan_kwargs(),
    )
    session = _approve(db_session, workspace, session)
    session_id = session.id
    question_id = session.plan["questions"][0]["id"]

    texts = [
        "Quand la ligne dérive après redémarrage, je vérifie le rapport et les réglages.",
        "Ensuite je contrôle la température du rouleau avant de valider la procédure terrain.",
        "Enfin je consigne la décision dans le CRM pour tracer le contexte client.",
    ]
    for idx, text in enumerate(texts):
        result = append_turn(
            db_session,
            workspace_id=workspace.id,
            session_id=session_id,
            speaker="expert",
            question_id=question_id if idx == 0 else None,
            text=text,
            compute_evaluation=False,
            persist_transcript=False,
        )
        # The silent path skips the O(N) serialize/refresh — the caller discards it.
        assert result["session"] is None
        assert result["turn"]["text"] == text

    # The committed column was NOT rewritten per turn: it is deferred and flagged
    # dirty, while the per-turn counters were maintained incrementally.
    deferred = get_session(db_session, workspace_id=workspace.id, session_id=session_id, materialize=False)
    assert kc._transcript_is_dirty(deferred) is True
    assert (deferred.transcript or []) == []
    assert deferred.metrics["turns"] == len(texts)

    # A materializing reader sees the full transcript rebuilt from the ledger.
    materialized = get_session(db_session, workspace_id=workspace.id, session_id=session_id)
    transcript = list(materialized.transcript)
    assert [turn["text"] for turn in transcript] == texts
    assert all(turn["speaker"] == "expert" for turn in transcript)
    assert all(turn["source_event_id"] for turn in transcript)
    assert transcript[0]["question_id"] == question_id

    # An eager (persist_transcript=True) turn catches up the deferred column and the
    # rebuilt turn shape matches exactly what the eager path materializes.
    eager = append_turn(
        db_session,
        workspace_id=workspace.id,
        session_id=session_id,
        speaker="expert",
        question_id=None,
        text="Tour eager pour comparer la forme du tour.",
        compute_evaluation=False,
    )
    assert set(eager["turn"].keys()) == set(transcript[0].keys())

    # serialize_session observes the complete transcript and never leaks the internal
    # deferred flag.
    payload = serialize_session(get_session(db_session, workspace_id=workspace.id, session_id=session_id))
    assert len(payload["transcript"]) == len(texts) + 1
    assert "transcript_dirty" not in payload["metrics"]
    assert payload["metrics"]["turns"] == len(texts) + 1

    # Proposal building persists the ledger-derived transcript and clears the flag so
    # the column and the source of truth agree again.
    proposal = create_update_proposal(db_session, workspace_id=workspace.id, session_id=session_id)
    segment_texts = {
        (segment.get("amended_segment") or segment.get("raw_segment") or "").strip()
        for segment in proposal.proposal["transcript_segments"]
    }
    assert all(text in segment_texts for text in texts)
    synced = get_session(db_session, workspace_id=workspace.id, session_id=session_id, materialize=False)
    assert kc._transcript_is_dirty(synced) is False
    assert len(synced.transcript) == len(texts) + 1
