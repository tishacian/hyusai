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
    review_proposal,
)
from app.services.skills_registry.seed import seed_skills_and_capabilities
from app.services.skills_registry.wrappers import runtime_status


def test_seeded_expert_capture_capability_and_bound_skills(db_session):
    report = seed_skills_and_capabilities(db_session)

    assert report["skills_added"] >= 1
    assert runtime_status("voice_transcribe_v1") == "bound"
    assert runtime_status("voice_tts_v1") == "bound"
    assert runtime_status("knowledge_gap_analysis_v1") == "bound"
    assert runtime_status("expert_interview_plan_v1") == "bound"


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
