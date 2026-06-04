"""Sparse retrieval adapters for layered HAH/CHAH.

Qdrant sparse is the primary scoped chunk-level backend when enabled. OpenSearch
remains available for coarse/manual summary artifacts or explicit fallback.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_KEYWORD_FILTER_FIELDS = {
    "title": "title.keyword",
    "document_filename": "document_filename.keyword",
}


class SparseSearchBackend(Protocol):
    name: str

    async def search(
        self,
        query: str,
        *,
        collection: str,
        filters: Mapping[str, Any] | None = None,
        top_k: int = 10,
        deadline_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        ...


@dataclass
class DisabledSparseBackend:
    name: str = "disabled"

    async def search(
        self,
        query: str,
        *,
        collection: str,
        filters: Mapping[str, Any] | None = None,
        top_k: int = 10,
        deadline_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        return []


@dataclass
class OpenSearchSparseBackend:
    base_url: str
    index_prefix: str
    name: str = "opensearch"

    def _index_name(self, collection: str) -> str:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in collection.lower())
        return f"{self.index_prefix}-{safe}"

    def _filter_clause(self, filters: Mapping[str, Any] | None) -> list[dict[str, Any]]:
        clauses: list[dict[str, Any]] = []
        for key, value in (filters or {}).items():
            if value in (None, "", []):
                continue
            field = _KEYWORD_FILTER_FIELDS.get(str(key), str(key))
            if isinstance(value, (list, tuple, set)):
                values = [item for item in value if item not in (None, "")]
                if values:
                    clauses.append({"terms": {field: values}})
            else:
                clauses.append({"term": {field: value}})
        return clauses

    async def search(
        self,
        query: str,
        *,
        collection: str,
        filters: Mapping[str, Any] | None = None,
        top_k: int = 10,
        deadline_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        if not self.base_url:
            return []
        timeout = max(0.001, min(float(deadline_seconds or 2.0), 10.0))
        body = {
            "size": max(1, min(int(top_k or 10), 100)),
            "query": {
                "bool": {
                    "must": [{"multi_match": {"query": query, "fields": ["content^2", "document_filename", "title"]}}],
                    "filter": self._filter_clause(filters),
                }
            },
        }
        url = f"{self.base_url.rstrip('/')}/{self._index_name(collection)}/_search"
        started = time.time()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=body)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenSearch sparse search failed", error=str(exc), collection=collection)
            return []
        hits = (payload.get("hits") or {}).get("hits") or []
        out: list[dict[str, Any]] = []
        for hit in hits:
            source = hit.get("_source") or {}
            content = source.get("content") or ""
            metadata = dict(source.get("metadata") or {})
            for key in (
                "collection",
                "collection_slug",
                "document_id",
                "document_filename",
                "source_kind",
                "extension",
                "project_code",
                "archive_name",
                "language",
                "status",
            ):
                if source.get(key) is not None and key not in metadata:
                    metadata[key] = source.get(key)
            out.append(
                {
                    "id": hit.get("_id") or source.get("chunk_id") or "",
                    "content": content,
                    "score": float(hit.get("_score") or 0.0),
                    "combined_score": float(hit.get("_score") or 0.0),
                    "bm25_score": float(hit.get("_score") or 0.0),
                    "vector_score": 0.0,
                    "metadata": metadata,
                    "sparse_backend": self.name,
                    "sparse_elapsed_ms": int((time.time() - started) * 1000),
                }
            )
        return out


@dataclass
class QdrantSparseBackend:
    name: str = "qdrant_sparse"

    async def search(
        self,
        query: str,
        *,
        collection: str,
        filters: Mapping[str, Any] | None = None,
        top_k: int = 10,
        deadline_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        if not settings.rag_qdrant_sparse_enabled:
            return []
        from app.services.vector_db.factory import VectorDBFactory

        started = time.time()
        try:
            vector_db = VectorDBFactory.get_db(collection, db_type="qdrant", workspace_slug=None)
            search_sparse = getattr(vector_db, "search_sparse", None)
            if not callable(search_sparse):
                return []
            rows = await search_sparse(
                query,
                top_k=top_k,
                filters=dict(filters or {}),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Qdrant sparse search failed", error=str(exc), collection=collection)
            return []
        elapsed_ms = int((time.time() - started) * 1000)
        for row in rows:
            row["sparse_backend"] = self.name
            row["sparse_elapsed_ms"] = elapsed_ms
            metadata = dict(row.get("metadata") or {})
            metadata["sparse_backend"] = self.name
            metadata["sparse_elapsed_ms"] = elapsed_ms
            row["metadata"] = metadata
        return rows


def get_sparse_backend() -> SparseSearchBackend:
    backend = str(settings.rag_sparse_backend or "auto").strip().lower()
    if backend == "auto":
        if settings.rag_qdrant_sparse_enabled:
            return QdrantSparseBackend()
        if settings.rag_opensearch_url:
            return OpenSearchSparseBackend(
                base_url=settings.rag_opensearch_url or "",
                index_prefix=settings.rag_opensearch_index_prefix,
            )
        return DisabledSparseBackend()
    if backend == "opensearch":
        return OpenSearchSparseBackend(
            base_url=settings.rag_opensearch_url or "",
            index_prefix=settings.rag_opensearch_index_prefix,
        )
    if backend in {"qdrant_sparse", "qdrant-sparse"}:
        return QdrantSparseBackend()
    return DisabledSparseBackend()
