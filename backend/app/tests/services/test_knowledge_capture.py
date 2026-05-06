from app.models.workspace import Workspace
from app.services.knowledge_capture import (
    amend_capture_event,
    create_capture_plan,
    append_turn,
    create_update_proposal,
    list_capture_events,
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
