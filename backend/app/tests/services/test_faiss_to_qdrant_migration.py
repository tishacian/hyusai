"""Tests for FAISS to Qdrant migration helpers."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from app.core.config import settings
from app.models.workspace import Workspace
from app.services.vector_db.faiss_db import FAISSVectorDB
from app.services.vector_db.faiss_to_qdrant import (
    load_faiss_snapshot,
    migrate_faiss_snapshot_to_qdrant,
)
from app.services.vector_db.qdrant_db import QdrantVectorDB


pytest.importorskip("faiss")


class FakeQdrantClient:
    def __init__(self) -> None:
        self.collections: dict[str, dict[str, object]] = {}
        self.deleted: list[str] = []

    def collection_exists(self, collection_name: str) -> bool:
        return collection_name in self.collections

    def create_collection(self, collection_name: str, vectors_config) -> None:
        self.collections.setdefault(collection_name, {})

    def delete_collection(self, collection_name: str) -> None:
        self.deleted.append(collection_name)
        self.collections.pop(collection_name, None)

    def upsert(self, collection_name: str, wait: bool, points: list[object]) -> None:
        collection = self.collections.setdefault(collection_name, {})
        for point in points:
            collection[str(point.id)] = point

    def count(self, collection_name: str) -> SimpleNamespace:
        return SimpleNamespace(count=len(self.collections.get(collection_name, {})))

    def scroll(
        self,
        collection_name: str,
        limit: int = 256,
        offset: int | None = None,
        with_payload: bool = True,
        with_vectors: bool = False,
        **_: object,
    ):
        points = list(self.collections.get(collection_name, {}).values())
        start = int(offset or 0)
        chunk = points[start : start + limit]
        next_offset = start + limit if start + limit < len(points) else None
        records = [SimpleNamespace(payload=dict(point.payload or {})) for point in chunk]
        return records, next_offset


@pytest.mark.asyncio
async def test_migrates_faiss_snapshot_to_qdrant_with_strict_parity(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "faiss_persist_directory", str(tmp_path))
    workspace = Workspace(id="workspace-1", slug="andritz", name="Andritz")
    faiss_db = FAISSVectorDB(
        persist_directory=str(tmp_path),
        collection_name="andritz__docs",
    )
    await faiss_db.add_vectors(
        np.array([[3.0, 4.0], [1.0, 0.0]], dtype=np.float32),
        [
            {"document_id": "doc-1", "document_filename": "a.txt", "content": "alpha"},
            {"document_id": "doc-2", "document_filename": "b.txt", "content": "bravo"},
        ],
        ["chunk-1", "chunk-2"],
    )

    snapshot = load_faiss_snapshot(workspace=workspace, collection="docs")
    client = FakeQdrantClient()
    qdrant = QdrantVectorDB(collection_name="andritz__docs", client=client)

    dry = await migrate_faiss_snapshot_to_qdrant(
        workspace=workspace,
        snapshot=snapshot,
        qdrant=qdrant,
        dry_run=True,
    )
    assert dry.source_count == 2
    assert dry.target_count_after == 0
    assert not dry.strict_match
    assert "andritz__docs" not in client.collections

    report = await migrate_faiss_snapshot_to_qdrant(
        workspace=workspace,
        snapshot=snapshot,
        qdrant=qdrant,
        dry_run=False,
        replace_target=True,
        batch_size=1,
    )

    assert report.source_count == 2
    assert report.target_count_after == 2
    assert report.document_count == 2
    assert report.batches_written == 2
    assert report.strict_match
    assert report.replaced_target
    stored_payloads = [
        point.payload for point in client.collections["andritz__docs"].values()
    ]
    assert {payload["chunk_id"] for payload in stored_payloads} == {"chunk-1", "chunk-2"}
    assert {payload["content"] for payload in stored_payloads} == {"alpha", "bravo"}


@pytest.mark.asyncio
async def test_detects_extra_target_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "faiss_persist_directory", str(tmp_path))
    workspace = Workspace(id="workspace-1", slug="andritz", name="Andritz")
    faiss_db = FAISSVectorDB(
        persist_directory=str(tmp_path),
        collection_name="andritz__docs",
    )
    await faiss_db.add_vectors(
        np.array([[1.0, 0.0]], dtype=np.float32),
        [{"document_id": "doc-1", "content": "alpha"}],
        ["chunk-1"],
    )
    snapshot = load_faiss_snapshot(workspace=workspace, collection="docs")
    client = FakeQdrantClient()
    qdrant = QdrantVectorDB(collection_name="andritz__docs", client=client)
    await qdrant.add_vectors(
        np.array([[0.0, 1.0]], dtype=np.float32),
        [{"content": "stale"}],
        ["stale-chunk"],
    )

    report = await migrate_faiss_snapshot_to_qdrant(
        workspace=workspace,
        snapshot=snapshot,
        qdrant=qdrant,
        dry_run=False,
        replace_target=False,
    )

    assert report.target_count_after == 2
    assert report.extra_target_ids == ["stale-chunk"]
    assert not report.strict_match
