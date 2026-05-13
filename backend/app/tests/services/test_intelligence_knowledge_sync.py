from __future__ import annotations

from datetime import datetime

import pytest

from app.models.intelligence import FeedArticle, FeedSource
from app.models.knowledge_collection import KnowledgeCollection
from app.models.workspace import Workspace
from app.services.intelligence import knowledge_sync
from app.services.intelligence.knowledge_sync import (
    INTELLIGENCE_COLLECTION_SLUG,
    sync_intelligence_to_knowledge,
)


class _FakeVectorDB:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def get_by_document_id(self, document_id: str) -> list[str]:
        return [f"{document_id}_chunk_0"]

    async def delete(self, ids: list[str]) -> None:
        self.deleted.extend(ids)


class _FakeDocumentService:
    instances: list["_FakeDocumentService"] = []

    def __init__(self, collection_name: str, vector_db_type: str, workspace_slug: str, **_kwargs):
        self.collection_name = collection_name
        self.vector_db_type = vector_db_type
        self.workspace_slug = workspace_slug
        self.vector_db = _FakeVectorDB()
        self.ingested_paths: list[str] = []
        _FakeDocumentService.instances.append(self)

    async def ingest_documents_batch(self, paths: list[str], **_kwargs) -> dict:
        self.ingested_paths.extend(paths)
        return {"total": len(paths), "successful": len(paths), "failed": 0}

    async def list_documents(self) -> list[dict]:
        return [{"document_id": path, "chunk_count": 1} for path in self.ingested_paths]

    async def get_document_count(self) -> int:
        return len(self.ingested_paths) * 2


@pytest.mark.asyncio
async def test_intelligence_sync_indexes_consolidated_and_raw_workspace_sources(db_session, monkeypatch):
    monkeypatch.setattr(knowledge_sync, "DocumentService", _FakeDocumentService)

    async def _fake_bm25(**_kwargs):
        return {"status": "ready", "chunk_count": 4}

    monkeypatch.setattr(knowledge_sync, "rebuild_bm25_artifact", _fake_bm25)
    _FakeDocumentService.instances = []

    sentinel = Workspace(id="workspace-sentinel", slug="sentinel-ci", name="SENTINEL-CI", mode="demo")
    andritz = Workspace(id="workspace-andritz", slug="andritz", name="Andritz")
    db_session.add_all([sentinel, andritz])
    db_session.add_all(
        [
            FeedSource(
                id="feed-sentinel",
                workspace_id=sentinel.id,
                name="RFI Afrique",
                url="https://example.test/rss",
                category="africa",
                active=True,
            ),
            FeedSource(
                id="feed-andritz",
                workspace_id=andritz.id,
                name="Andritz feed",
                url="https://andritz.example/rss",
                category="industry",
                active=True,
            ),
        ]
    )
    db_session.add_all(
        [
            FeedArticle(
                id="article-ci-1",
                source_id="feed-sentinel",
                title="Cote d'Ivoire: coordination gouvernementale",
                url="https://example.test/ci",
                content="Raw scraped article content about cabinet coordination and public projects.",
                summary="Signal faible sur coordination publique.",
                published_at=datetime.utcnow(),
                fetched_at=datetime.utcnow(),
                embedded=True,
                relevance_score=0.82,
                safety_flag="clear",
                analysis={
                    "risk_level": "medium",
                    "sentiment": "mixed",
                    "entities": ["Cote d'Ivoire", "Abidjan"],
                    "key_findings": ["Risque de perception publique si les projets glissent."],
                },
            ),
            FeedArticle(
                id="article-andritz-1",
                source_id="feed-andritz",
                title="Andritz maintenance update",
                content="This article must not leak into SENTINEL-CI.",
                fetched_at=datetime.utcnow(),
                embedded=True,
                relevance_score=0.7,
                analysis={"risk_level": "low", "key_findings": ["Industrial update."]},
            ),
        ]
    )
    db_session.commit()

    result = await sync_intelligence_to_knowledge(
        db_session,
        sentinel,
        dashboard_payload={
            "kpis": {"active_feeds": 1, "total_articles": 1, "analyzed": 1, "high_risk": 0},
            "risk": {"medium": 1},
            "sentiment": {"mixed": 1},
            "synthesis": {
                "summary": "Synthese cabinet.",
                "key_findings": ["Un signal prioritaire."],
                "recommended_actions": ["Preparer une note."],
                "source_articles": [{"title": "Cote d'Ivoire: coordination gouvernementale"}],
            },
            "articles": [{"title": "Cote d'Ivoire: coordination gouvernementale", "risk_level": "medium"}],
        },
        max_articles=10,
    )

    assert result["status"] == "ready"
    assert result["collection_slug"] == INTELLIGENCE_COLLECTION_SLUG
    assert result["articles_synced"] == 1
    assert result["documents_written"] == 2

    service = _FakeDocumentService.instances[-1]
    assert service.collection_name == INTELLIGENCE_COLLECTION_SLUG
    assert service.workspace_slug == "sentinel-ci"
    assert any(path.endswith("news-lab-consolidated-latest.md") for path in service.ingested_paths)
    assert any(path.endswith("rss-article-article-ci-1.md") for path in service.ingested_paths)
    assert not any("andritz" in path.lower() for path in service.ingested_paths)

    collection = result["collection_id"]
    row = db_session.query(KnowledgeCollection).filter(KnowledgeCollection.id == collection).one()
    assert row.status == "ready"
    assert "rss-article-article-ci-1.md" in row.document_names
    assert all("andritz" not in name.lower() for name in row.document_names)
