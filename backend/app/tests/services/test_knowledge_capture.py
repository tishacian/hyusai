import pytest

from app.models.context import Context
from app.models.workspace import Workspace
from app.services.knowledge_capture import (
    amend_capture_event,
    create_capture_plan,
    append_turn,
    create_update_proposal,
    list_capture_events,
    prefetch_capture_retrieval,
    process_conversation_step,
    review_proposal,
)
from app.services.chains.dag_validator import validate_flow
from app.services.skills_registry.seed import seed_skills_and_capabilities
from app.services.skills_registry.wrappers import runtime_status
from app.services.systems.bootstrap import ensure_expert_capture_system_default


def test_seeded_expert_capture_capability_and_bound_skills(db_session):
    report = seed_skills_and_capabilities(db_session)

    assert report["skills_added"] >= 1
    assert runtime_status("semantic_search_v1") == "bound"
    assert runtime_status("voice_transcribe_v1") == "bound"
    assert runtime_status("voice_tts_v1") == "bound"
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
    assert len(system.skill_ids) == 8
    assert system.flow_definition["variant"] == "expert_knowledge_capture"
    assert system.flow_definition["ui"]["type"] == "knowledge_capture"
    assert system.flow_definition["ui"]["entry_route"] == "capture"
    assert [issue for issue in validate_flow(system.flow_definition) if issue.level == "error"] == []
    node_ids = {node["id"] for node in system.flow_definition["nodes"]}
    assert "skill.semantic_search_prefetch" in node_ids
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
    )

    assert session.status == "planned"
    assert session.plan["duration_minutes"] == 20
    assert len(session.plan["questions"]) >= 2
    assert session.knowledge_gaps[0]["status"] == "open"

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
    )
    question_id = session.plan["questions"][0]["id"]

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
    )

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
    )
    question_id = session.plan["questions"][0]["id"]

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
