from uuid import uuid4

from app.models.workspace import Workspace
from app.services.evaluation.canonical_answer_service import (
    create_canonical_answer,
    find_canonical_answer,
    normalize_question,
    record_hit,
)


def test_normalize_question_keeps_semantic_tokens():
    assert normalize_question("What is the SLA, please?") == "what is the sla please"


def test_create_and_find_canonical_answer(db_session):
    ws = Workspace(id=str(uuid4()), slug=f"canon-{uuid4().hex[:6]}", name="Canon")
    db_session.add(ws)
    db_session.commit()

    row = create_canonical_answer(
        db_session,
        workspace_id=ws.id,
        question="What is the enterprise SLA?",
        answer="The enterprise SLA is 99.9% uptime.",
        actor="alice",
    )
    db_session.commit()

    match = find_canonical_answer(
        db_session,
        workspace_id=ws.id,
        query="What is the enterprise SLA?",
    )
    assert match is not None
    found, score = match
    assert found.id == row.id
    assert score >= row.similarity_threshold


def test_canonical_answer_hit_increments_counter(db_session):
    ws = Workspace(id=str(uuid4()), slug=f"hit-{uuid4().hex[:6]}", name="Hit")
    db_session.add(ws)
    db_session.commit()
    row = create_canonical_answer(
        db_session,
        workspace_id=ws.id,
        question="How do refunds work?",
        answer="Refunds are available within 30 days.",
    )
    record_hit(db_session, canonical_answer=row, query="How do refunds work?", score=1.0)
    db_session.commit()

    assert row.hit_count == 1
