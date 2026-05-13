from __future__ import annotations

import pytest

from app.models.knowledge_collection import KnowledgeCollection
from app.models.workspace import Workspace
from app.services import mission_room_knowledge_sync
from app.services.mission_room import SENTINEL_WORKSPACE_SLUG, ensure_sentinel_ci_workspace
from app.services.mission_room_knowledge_sync import (
    sync_mission_room_fixtures_to_knowledge,
    sync_visual_observations_to_knowledge,
)


class _FakeVectorDB:
    async def get_by_document_id(self, document_id: str) -> list[str]:
        return [f"{document_id}_chunk_0"]

    async def delete(self, _ids: list[str]) -> None:
        return None


class _FakeDocumentService:
    instances: list["_FakeDocumentService"] = []

    def __init__(self, collection_name: str, vector_db_type: str, workspace_slug: str, **_kwargs):
        self.collection_name = collection_name
        self.vector_db_type = vector_db_type
        self.workspace_slug = workspace_slug
        self.vector_db = _FakeVectorDB()
        self.ingested_paths: list[str] = []
        _FakeDocumentService.instances.append(self)

    async def ingest_documents_batch(self, paths: list[str]) -> dict:
        self.ingested_paths.extend(paths)
        return {"total": len(paths), "successful": len(paths), "failed": 0}

    async def list_documents(self) -> list[dict]:
        return [{"document_id": path, "chunk_count": 1} for path in self.ingested_paths]

    async def get_document_count(self) -> int:
        return len(self.ingested_paths)


@pytest.mark.asyncio
async def test_mission_room_fixture_sync_indexes_all_vigie_scope_collections(db_session, monkeypatch):
    monkeypatch.setattr(mission_room_knowledge_sync, "DocumentService", _FakeDocumentService)

    async def _fake_bm25(**_kwargs):
        return {"status": "ready", "chunk_count": 4}

    monkeypatch.setattr(mission_room_knowledge_sync, "rebuild_bm25_artifact", _fake_bm25)
    _FakeDocumentService.instances = []

    ensure_sentinel_ci_workspace(db_session)
    workspace = db_session.query(Workspace).filter_by(slug=SENTINEL_WORKSPACE_SLUG).one()

    result = await sync_mission_room_fixtures_to_knowledge(db_session, workspace)

    assert result["status"] == "ready"
    assert set(result["collections"]) == {
        "sentinel-ci-ministerial-briefs",
        "sentinel-ci-projects",
        "sentinel-ci-territorial-map",
        "sentinel-ci-territorial-intelligence",
    }
    assert {instance.workspace_slug for instance in _FakeDocumentService.instances} == {"sentinel-ci"}

    for slug in result["collections"]:
        row = db_session.query(KnowledgeCollection).filter_by(workspace_id=workspace.id, slug=slug).one()
        assert row.status == "ready"
        assert row.document_count > 0
        assert row.chunk_count > 0
        assert row.document_names


@pytest.mark.asyncio
async def test_visual_observation_sync_creates_queryable_placeholder_when_empty(db_session, monkeypatch):
    monkeypatch.setattr(mission_room_knowledge_sync, "DocumentService", _FakeDocumentService)

    async def _fake_bm25(**_kwargs):
        return {"status": "ready", "chunk_count": 1}

    monkeypatch.setattr(mission_room_knowledge_sync, "rebuild_bm25_artifact", _fake_bm25)
    _FakeDocumentService.instances = []

    ensure_sentinel_ci_workspace(db_session)
    workspace = db_session.query(Workspace).filter_by(slug=SENTINEL_WORKSPACE_SLUG).one()

    result = await sync_visual_observations_to_knowledge(db_session, workspace)

    assert result["collection_slug"] == "sentinel-ci-visual-intelligence"
    assert result["documents_written"] == 1
    service = _FakeDocumentService.instances[-1]
    assert service.collection_name == "sentinel-ci-visual-intelligence"
    assert service.workspace_slug == "sentinel-ci"
