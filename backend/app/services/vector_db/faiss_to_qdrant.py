"""FAISS to Qdrant migration helpers."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger
from app.services.vector_db.factory import VectorDBFactory
from app.services.vector_db.faiss_db import FAISSVectorDB
from app.services.vector_db.qdrant_db import QdrantVectorDB

logger = get_logger(__name__)


@dataclass(frozen=True)
class FaissSnapshot:
    logical_collection: str
    scoped_collection: str
    ids: list[str]
    metadatas: list[dict[str, Any]]
    vectors: np.ndarray
    dimension: int
    document_ids: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class MigrationReport:
    workspace_slug: str
    logical_collection: str
    scoped_collection: str
    dry_run: bool
    replaced_target: bool
    source_count: int
    target_count_before: int
    target_count_after: int
    dimension: int | None
    document_count: int
    missing_target_ids: list[str]
    extra_target_ids: list[str]
    batches_written: int

    @property
    def strict_match(self) -> bool:
        return (
            not self.missing_target_ids
            and not self.extra_target_ids
            and self.target_count_after == self.source_count
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "workspace_slug": self.workspace_slug,
            "logical_collection": self.logical_collection,
            "scoped_collection": self.scoped_collection,
            "dry_run": self.dry_run,
            "replaced_target": self.replaced_target,
            "source_count": self.source_count,
            "target_count_before": self.target_count_before,
            "target_count_after": self.target_count_after,
            "dimension": self.dimension,
            "document_count": self.document_count,
            "missing_target_ids": self.missing_target_ids,
            "extra_target_ids": self.extra_target_ids,
            "batches_written": self.batches_written,
            "strict_match": self.strict_match,
        }


def _reconstruct_vectors(faiss_db: FAISSVectorDB) -> np.ndarray:
    if faiss_db.index is None or faiss_db.index.ntotal == 0:
        dimension = int(faiss_db.dimension or 0)
        return np.empty((0, dimension), dtype=np.float32)

    try:
        vectors = faiss_db.index.reconstruct_n(0, faiss_db.index.ntotal)
    except Exception:
        vectors = np.vstack(
            [faiss_db.index.reconstruct(i) for i in range(faiss_db.index.ntotal)]
        )
    return np.asarray(vectors, dtype=np.float32)


def load_faiss_snapshot(*, workspace: Any, collection: str) -> FaissSnapshot:
    """Load one workspace-scoped FAISS collection without mutating it."""
    scoped_collection = VectorDBFactory.scoped_name(collection, workspace.slug)
    index_path = Path(settings.faiss_persist_directory) / f"{scoped_collection}.index"
    metadata_path = Path(settings.faiss_persist_directory) / f"{scoped_collection}.metadata.pkl"
    if not index_path.exists() or not metadata_path.exists():
        raise FileNotFoundError(
            f"FAISS collection {scoped_collection!r} not found in {settings.faiss_persist_directory!r}"
        )
    faiss_db = FAISSVectorDB(
        persist_directory=settings.faiss_persist_directory,
        collection_name=scoped_collection,
    )
    ids = faiss_db.ids.copy()
    if len(set(ids)) != len(ids):
        raise ValueError(f"FAISS collection {scoped_collection!r} has duplicate chunk ids")
    if faiss_db.index is not None and faiss_db.index.ntotal != len(ids):
        raise ValueError(
            f"FAISS collection {scoped_collection!r} index/id mismatch: "
            f"{faiss_db.index.ntotal} vectors for {len(ids)} ids"
        )

    vectors = _reconstruct_vectors(faiss_db)
    if vectors.shape[0] != len(ids):
        raise ValueError(
            f"FAISS collection {scoped_collection!r} vector/id mismatch: "
            f"{vectors.shape[0]} vectors for {len(ids)} ids"
        )

    metadatas = [dict(faiss_db.metadatas.get(chunk_id, {})) for chunk_id in ids]
    document_ids = {
        str(meta.get("document_id"))
        for meta in metadatas
        if meta.get("document_id") and not str(meta.get("document_id")).startswith(("tmp_", "temp_"))
    }
    dimension = int(vectors.shape[1]) if vectors.ndim == 2 and vectors.shape[1:] else 0
    return FaissSnapshot(
        logical_collection=collection,
        scoped_collection=scoped_collection,
        ids=ids,
        metadatas=metadatas,
        vectors=vectors,
        dimension=dimension,
        document_ids=document_ids,
    )


async def migrate_faiss_snapshot_to_qdrant(
    *,
    workspace: Any,
    snapshot: FaissSnapshot,
    qdrant: QdrantVectorDB,
    batch_size: int = 512,
    dry_run: bool = True,
    replace_target: bool = False,
) -> MigrationReport:
    """Copy one FAISS snapshot to Qdrant and validate ID parity."""
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    source_ids = set(snapshot.ids)
    target_ids_before = set(await qdrant.get_all_ids())

    batches_written = 0
    if not dry_run:
        if replace_target:
            await qdrant.clear_collection()
        if snapshot.dimension <= 0:
            raise ValueError(f"Cannot migrate empty-dimension collection {snapshot.scoped_collection!r}")
        await qdrant.create_index(snapshot.dimension)
        for start in range(0, len(snapshot.ids), batch_size):
            end = start + batch_size
            await qdrant.add_vectors(
                snapshot.vectors[start:end],
                snapshot.metadatas[start:end],
                snapshot.ids[start:end],
            )
            batches_written += 1

    target_ids_after = set(await qdrant.get_all_ids())
    if dry_run:
        target_count_after = len(target_ids_before)
        missing = sorted(source_ids - target_ids_before)
        extra = sorted(target_ids_before - source_ids)
    else:
        target_count_after = len(target_ids_after)
        missing = sorted(source_ids - target_ids_after)
        extra = sorted(target_ids_after - source_ids)

    return MigrationReport(
        workspace_slug=workspace.slug,
        logical_collection=snapshot.logical_collection,
        scoped_collection=snapshot.scoped_collection,
        dry_run=dry_run,
        replaced_target=replace_target and not dry_run,
        source_count=len(snapshot.ids),
        target_count_before=len(target_ids_before),
        target_count_after=target_count_after,
        dimension=snapshot.dimension or None,
        document_count=len(snapshot.document_ids),
        missing_target_ids=missing,
        extra_target_ids=extra,
        batches_written=batches_written,
    )


async def migrate_faiss_collection_to_qdrant(
    *,
    workspace: Any,
    collection: str,
    qdrant_client: Any,
    batch_size: int = 512,
    dry_run: bool = True,
    replace_target: bool = False,
) -> MigrationReport:
    snapshot = load_faiss_snapshot(workspace=workspace, collection=collection)
    qdrant = QdrantVectorDB(collection_name=snapshot.scoped_collection, client=qdrant_client)
    report = await migrate_faiss_snapshot_to_qdrant(
        workspace=workspace,
        snapshot=snapshot,
        qdrant=qdrant,
        batch_size=batch_size,
        dry_run=dry_run,
        replace_target=replace_target,
    )
    logger.info(
        "faiss_to_qdrant.migrated",
        workspace_slug=workspace.slug,
        collection=collection,
        dry_run=dry_run,
        strict_match=report.strict_match,
        source_count=report.source_count,
        target_count_after=report.target_count_after,
    )
    return report


def run_migration(coro):
    """Run an async migration from a sync CLI entrypoint."""
    return asyncio.run(coro)
