import json
import pytest

from app.models.context import Context
from app.models.run import Run
from app.models.user import User
from app.models.workspace import Workspace
from app.services.knowledge_capture import (
    amend_capture_event,
    amend_capture_plan,
    apply_session_closure_action,
    build_session_closure_sheet,
    create_capture_plan,
    approve_capture_plan,
    append_turn,
    classify_conversation_intent,
    create_update_proposal,
    extend_capture_session,
    list_capture_events,
    prefetch_capture_retrieval,
    process_conversation_step,
    review_proposal,
    serialize_session,
    start_session,
    structure_capture_payload,
)
from app.services.capture_report_templates import (
    ANDRITZ_TEMPLATE_ID,
    build_andritz_knowledge_sheet,
    resolve_knowledge_sheet_template,
)
from app.services.chains.dag_validator import validate_flow
from app.services.skills_registry.seed import seed_skills_and_capabilities
from app.services.skills_registry.wrappers import runtime_status
from app.services.systems.bootstrap import ensure_expert_capture_system_default


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

    class FakeDocumentService:
        def __init__(self, collection_name="documents", workspace_slug=None, **kwargs):
            self.collection_name = collection_name
            self.workspace_slug = workspace_slug

    async def fake_retrieve_for_mode(doc_svc, query, mode, **kwargs):
        class Result:
            chunks = ["Le rapport CRM indique que la vibration suit un changement de rouleau."]
            scores = [0.91]
            metadatas = [{"title": "CRM maintenance", "source": "crm"}]
            pipeline = "chah_backend"
            label = "C-HAH (backend)"
            reason = "fake retrieval"
            detail = f"{doc_svc.collection_name}:{mode}:{query[:8]}"

        return Result()

    monkeypatch.setattr("app.services.rag.document_service.DocumentService", FakeDocumentService)
    monkeypatch.setattr("app.services.rag.pipeline_retrieval.retrieve_for_mode", fake_retrieve_for_mode)

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
    )
    assert turn["system_prompt_event_id"]
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
    assert "stt_final" in event_types
    assert "ai_speech_interrupted" in event_types
    assert "system_prompt_prepared" in event_types

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

    live = evaluate_capture_partial(
        context,
        "En cas X on monte à 180/min pour stabiliser la ligne",
        kb_chunks,
        plan_topics=oracle["topic_proposals"],
    )
    assert live["hints"]
    assert live["hints"][0]["priority"] == 100
    assert "180" in live["hints"][0]["hint"]


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
    assert turn["next_prompt"]
    assert turn["session"]["plan"]["topics"]
    assert turn["session"]["plan"].get("oracle", {}).get("coverage_gaps") is not None
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

    finalized = finalize_plan_from_dialogue(
        db_session,
        workspace_id=workspace.id,
        session_id=session.id,
        workspace_slug=workspace.slug,
    )
    assert finalized.plan["topics"]
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
    )
    assert session.plan["mode"] == "provided_plan"
    assert session.plan["schema_version"] == "plan_build_v2"
    assert len(session.plan["topics"]) == 1
    assert len(session.plan["topics"][0]["subtopics"]) == 2
    assert session.plan["dialogue"]["ready_to_finalize"] is True


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
    assert payload["knowledge_sheet_template"] == ANDRITZ_TEMPLATE_ID
    content = payload["recommended_ingestion"]["content"]
    assert "## Contexte" in content
    assert "## Décision" in content
    assert "## Owner" in content
    assert resolve_knowledge_sheet_template(loaded) == ANDRITZ_TEMPLATE_ID
    direct = build_andritz_knowledge_sheet(
        loaded,
        payload["captured_facts"],
        transcript=loaded.transcript or [],
    )
    assert "Fiche connaissance" in direct
