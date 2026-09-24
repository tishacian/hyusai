"""Volet 6 — cross-worker integration tests for "Correction experte en chat".

Each worker (Volets 1-5) unit-tested its own slice. These tests close the
end-to-end gaps *between* the slices:

1. Metadata continuity — a chat-correction proposal (Volet 2) carried all the
   way through ``publish_proposal_to_knowledge`` yields ``ingest_metadata`` with
   ``source_type="expert_fiche"`` (the marker the Volet 3 boost keys on).
2. Retrieval consequence — that same marker, fed through the *chat-path*
   reranker ``rerank_aligned_with_policy`` (Volet 3), makes a validated fiche
   outrank a near-tie plain doc when ``rag_expert_fiche_boost_enabled`` is ON,
   and leaves ordering untouched when it is OFF.
3. Golden "doc périmée vs fiche experte" — a stale doc with a *higher* raw
   similarity still loses to the validated expert fiche on the same topic once
   the flag is ON, and wins again when it is OFF (the boost is the only lever).
"""
from __future__ import annotations

import pytest

from app.core.config import settings as app_config
from app.models.user import User
from app.models.workspace import Workspace
from app.services.knowledge_capture import (
    create_chat_correction_proposal,
    publish_proposal_to_knowledge,
    review_proposal,
)
from app.services.rag.retrieval_policy import rerank_aligned_with_policy


def _seed_workspace_user(db_session, *, ws_id: str, slug: str, user_id: str) -> tuple[Workspace, User]:
    workspace = Workspace(id=ws_id, name=ws_id, slug=slug)
    user = User(id=user_id, username="expert", email="expert@demo.test")
    db_session.add_all([workspace, user])
    db_session.commit()
    return workspace, user


# ---------------------------------------------------------------------------
# 1. End-to-end metadata continuity: capture -> accept -> publish
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_correction_publish_propagates_expert_fiche_metadata(db_session, monkeypatch):
    """The provenance markers set at capture survive ingestion at publish time.

    This is the seam between Volet 2 (capture writes ``source_type``) and the
    publish path that feeds the index: ``ingest_document`` must receive
    ``document_metadata`` carrying ``source_type="expert_fiche"`` so the Volet 3
    boost can recognise the fiche once it is retrieved.
    """
    workspace, user = _seed_workspace_user(
        db_session, ws_id="ws-e2e-meta", slug="andritz", user_id="user-e2e-meta"
    )

    captured: dict[str, dict] = {}

    class FakeDocumentService:
        def __init__(self, **_: object) -> None:
            pass

        async def ingest_document(self, *_: object, document_metadata: dict | None = None, **__: object) -> dict:
            captured["document_metadata"] = dict(document_metadata or {})
            return {"document_id": "doc-e2e-fiche", "chunks_processed": 2, "status": "success"}

        async def get_document_count(self) -> int:
            # Publication records the collection's vector total in its source ledger.
            return 2

    monkeypatch.setattr("app.services.rag.document_service.DocumentService", FakeDocumentService)

    proposal, _session = create_chat_correction_proposal(
        db_session,
        workspace=workspace,
        user=user,
        query="Quelle est la pression nominale de la pompe KD724 ?",
        assistant_answer="Environ 5 bar.",
        correction_text="La pression nominale de la pompe KD724 est 7 bar, pas 5 bar.",
        sources=[{"title": "Manuel pompe KD724", "url": "https://docs/kd724"}],
        input_modality="voice",
        transcript_raw="sept bar pour la pompe KD724",
        audio_ref="workspaces/ws-e2e-meta/expert-fiche-captures/andritz-expert-fiche/abc/audio.webm",
        source_policy={"expert_fiche_collection": "andritz-validated-fiches"},
    )
    assert proposal.status == "pending_review"

    review_proposal(
        db_session,
        workspace_id=workspace.id,
        proposal_id=proposal.id,
        status="accepted",
        reviewer="reviewer@demo.test",
        review_notes="Validated for publication.",
    )

    result = await publish_proposal_to_knowledge(
        db_session,
        workspace=workspace,
        proposal_id=proposal.id,
        actor_label="reviewer@demo.test",
    )

    # The fiche was published to the configured expert-fiche collection.
    assert result["destination"] == "andritz-validated-fiches"
    assert result["status"] == "success"

    # The decisive cross-worker assertion: provenance markers reached ingestion.
    ingest_metadata = captured["document_metadata"]
    assert ingest_metadata["source_type"] == "expert_fiche"
    assert ingest_metadata["origin"] == "chat_correction"
    assert ingest_metadata["input_modality"] == "voice"

    db_session.refresh(proposal)
    assert proposal.status == "published"


# ---------------------------------------------------------------------------
# 2. Retrieval consequence through the chat-path reranker
# ---------------------------------------------------------------------------

_RERANK_QUERY = "pump maintenance procedure"


def _aligned_sample() -> tuple[list[str], list[float], list[dict]]:
    """A plain manual extract and a near-tie validated expert fiche.

    Identical query-evidence coverage means equal base policy scores, so only
    the expert-fiche boost can change the ordering between the two rows.
    """
    chunks = [
        "Pump maintenance procedure from the manual.",
        "Pump maintenance procedure corrected by an expert.",
    ]
    scores = [0.80, 0.78]
    metadatas = [
        {"document_filename": "manual-extract.md"},
        {"document_filename": "fiche.md", "source_type": "expert_fiche"},
    ]
    return chunks, scores, metadatas


def test_chat_reranker_off_keeps_plain_doc_first(monkeypatch):
    monkeypatch.setattr(app_config, "rag_expert_fiche_boost_enabled", False)

    chunks, scores, metadatas = _aligned_sample()
    ranked_chunks, _ranked_scores, ranked_metas = rerank_aligned_with_policy(
        chunks, scores, metadatas, query=_RERANK_QUERY, policy=None
    )

    # The higher raw-similarity plain doc keeps the lead and no boost marker leaks.
    assert ranked_metas[0]["document_filename"] == "manual-extract.md"
    assert ranked_chunks[0] == "Pump maintenance procedure from the manual."
    assert all("expert_fiche_boost_applied" not in meta for meta in ranked_metas)


def test_chat_reranker_on_promotes_expert_fiche(monkeypatch):
    monkeypatch.setattr(app_config, "rag_expert_fiche_boost_enabled", True)
    monkeypatch.setattr(app_config, "rag_expert_fiche_boost", 18)

    chunks, scores, metadatas = _aligned_sample()
    ranked_chunks, _ranked_scores, ranked_metas = rerank_aligned_with_policy(
        chunks, scores, metadatas, query=_RERANK_QUERY, policy=None
    )

    # The validated fiche now leads despite its lower raw similarity score.
    assert ranked_metas[0]["document_filename"] == "fiche.md"
    assert ranked_chunks[0] == "Pump maintenance procedure corrected by an expert."
    assert ranked_metas[0]["expert_fiche_boost_applied"] is True

    score_by_file = {
        meta["document_filename"]: meta.get("retrieval_policy_score") for meta in ranked_metas
    }
    # The fiche gains exactly rag_expert_fiche_boost over the close non-fiche row.
    assert score_by_file["fiche.md"] - score_by_file["manual-extract.md"] == 18


# ---------------------------------------------------------------------------
# 3. Golden-style "doc périmée vs fiche experte"
# ---------------------------------------------------------------------------

_GOLDEN_QUERY = "Quelle est la pression nominale de la pompe KD724 ?"


def _golden_sample() -> tuple[list[str], list[float], list[dict]]:
    """A stale doc (higher raw similarity) vs a validated expert fiche.

    Both carry the same query-relevant evidence (same topic, same identifiers);
    they differ only in the corrected value and in the provenance marker. The
    stale doc even has the *higher* raw similarity, so without the boost it wins.
    """
    chunks = [
        "La pression nominale de la pompe KD724 est de 5 bar.",
        "La pression nominale de la pompe KD724 est de 7 bar.",
    ]
    scores = [0.90, 0.62]
    metadatas = [
        {"document_filename": "manuel-pompe-kd724.pdf", "status": "draft"},
        {"document_filename": "fiche-kd724.md", "source_type": "expert_fiche"},
    ]
    return chunks, scores, metadatas


def test_golden_stale_doc_outranks_fiche_when_boost_off(monkeypatch):
    monkeypatch.setattr(app_config, "rag_expert_fiche_boost_enabled", False)

    chunks, scores, metadatas = _golden_sample()
    _ranked_chunks, _ranked_scores, ranked_metas = rerank_aligned_with_policy(
        chunks, scores, metadatas, query=_GOLDEN_QUERY, policy=None
    )

    order = [meta["document_filename"] for meta in ranked_metas]
    # OFF: the stale doc's higher raw similarity keeps it on top.
    assert order.index("manuel-pompe-kd724.pdf") < order.index("fiche-kd724.md")


def test_golden_validated_fiche_outranks_stale_doc_when_boost_on(monkeypatch):
    monkeypatch.setattr(app_config, "rag_expert_fiche_boost_enabled", True)
    monkeypatch.setattr(app_config, "rag_expert_fiche_boost", 18)

    chunks, scores, metadatas = _golden_sample()
    ranked_chunks, _ranked_scores, ranked_metas = rerank_aligned_with_policy(
        chunks, scores, metadatas, query=_GOLDEN_QUERY, policy=None
    )

    order = [meta["document_filename"] for meta in ranked_metas]
    # ON: the validated fiche outranks the stale doc despite lower raw similarity.
    assert order.index("fiche-kd724.md") < order.index("manuel-pompe-kd724.pdf")
    assert ranked_chunks[0] == "La pression nominale de la pompe KD724 est de 7 bar."
    assert ranked_metas[0]["expert_fiche_boost_applied"] is True
