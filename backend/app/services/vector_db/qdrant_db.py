"""Qdrant vector database implementation (remote collection per logical collection name)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional

import numpy as np

from app.core.logging import get_logger
from app.services.vector_db.base import VectorDBBase

logger = get_logger(__name__)

# Fixed namespace for deterministic UUID point ids from string chunk ids
_CHUNK_ID_NAMESPACE = uuid.UUID("018f3f8e-7b4e-7f3a-9c0d-4a6b8e1c2d30")


def _sanitize_payload(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Qdrant payload: JSON-serializable scalars only."""
    out: Dict[str, Any] = {}
    for k, v in metadata.items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            out[str(k)] = v
        else:
            out[str(k)] = str(v)
    return out


class QdrantVectorDB(VectorDBBase):
    """Qdrant-backed vectors; string chunk ids mapped to UUID point ids + payload."""

    def __init__(
        self,
        collection_name: str = "documents",
        client: Any = None,
    ):
        self.collection_name = collection_name
        self.client = client
        self._dimension: Optional[int] = None

    def _point_id(self, chunk_id: str) -> str:
        return str(uuid.uuid5(_CHUNK_ID_NAMESPACE, f"{self.collection_name}:{chunk_id}"))

    def get_metadatas_for_chunk_ids(self, chunk_ids: List[str]) -> List[Dict[str, Any]]:
        """Sync: retrieve payloads for BM25 warm-up (used by DocumentService hybrid path)."""
        if not chunk_ids or self.client is None:
            return []
        try:
            ids = [self._point_id(cid) for cid in chunk_ids]
            records = self.client.retrieve(
                collection_name=self.collection_name,
                ids=ids,
                with_payload=True,
                with_vectors=False,
            )
            return [dict(r.payload) if r.payload else {} for r in records]
        except Exception as e:
            logger.warning(f"Qdrant get_metadatas_for_chunk_ids failed: {e}")
            return []

    async def create_index(self, dimension: int, index_type: str = "default"):
        from qdrant_client.models import Distance, VectorParams

        self._dimension = dimension
        if self.client.collection_exists(self.collection_name):
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
        )
        logger.info(f"Created Qdrant collection '{self.collection_name}' dim={dimension}")

    def _ensure_collection(self, dimension: int):
        from qdrant_client.models import Distance, VectorParams

        self._dimension = dimension
        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
            )

    async def add_vectors(
        self, vectors: np.ndarray, metadatas: List[Dict], ids: List[str]
    ):
        from qdrant_client.models import PointStruct

        if len(vectors) == 0:
            return
        dim = vectors.shape[1]
        loop = asyncio.get_event_loop()

        def _add():
            self._ensure_collection(dim)
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1, norms)
            normalized = (vectors / norms).astype(np.float32)
            points = []
            for i, chunk_id in enumerate(ids):
                pid = self._point_id(chunk_id)
                payload = _sanitize_payload(dict(metadatas[i]))
                payload["chunk_id"] = chunk_id
                points.append(
                    PointStruct(id=pid, vector=normalized[i].tolist(), payload=payload)
                )
            self.client.upsert(collection_name=self.collection_name, wait=True, points=points)

        await loop.run_in_executor(None, _add)
        logger.debug(f"Qdrant upserted {len(ids)} points into '{self.collection_name}'")

    def _filters_to_qdrant(self, filters: Optional[Dict]) -> Optional[Any]:
        if not filters:
            return None
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        must = []
        for key, value in filters.items():
            must.append(FieldCondition(key=str(key), match=MatchValue(value=value)))
        return Filter(must=must) if must else None

    async def search(
        self, query_vector: np.ndarray, top_k: int = 10, filters: Optional[dict] = None
    ) -> List[dict]:
        if top_k <= 0 or self.client is None:
            return []
        if not self.client.collection_exists(self.collection_name):
            return []

        loop = asyncio.get_event_loop()
        qf = self._filters_to_qdrant(filters)

        def _search():
            qn = np.linalg.norm(query_vector)
            if qn == 0:
                return []
            q = (query_vector / qn).astype(np.float32).tolist()
            res = self.client.query_points(
                collection_name=self.collection_name,
                query=q,
                limit=top_k,
                query_filter=qf,
            )
            out: List[dict] = []
            for hit in res.points:
                payload = dict(hit.payload) if hit.payload else {}
                chunk_id = payload.pop("chunk_id", None) or str(hit.id)
                content = payload.get("content", "")
                score = float(hit.score) if hit.score is not None else 0.0
                score = max(0.0, min(1.0, score))
                out.append(
                    {
                        "id": chunk_id,
                        "score": score,
                        "metadata": payload,
                        "content": content,
                    }
                )
            return out

        return await loop.run_in_executor(None, _search)

    async def delete(self, ids: List[str]):
        if not ids or self.client is None:
            return
        from qdrant_client.models import PointIdsList

        loop = asyncio.get_event_loop()
        point_ids = [self._point_id(i) for i in ids if i]

        def _del():
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=PointIdsList(points=point_ids),
            )

        await loop.run_in_executor(None, _del)

    async def update(self, ids: List[str], vectors: np.ndarray, metadatas: List[Dict]):
        await self.delete(ids)
        await self.add_vectors(vectors, metadatas, ids)

    async def get_count(self) -> int:
        if self.client is None or not self.client.collection_exists(self.collection_name):
            return 0
        loop = asyncio.get_event_loop()

        def _c():
            return self.client.count(collection_name=self.collection_name).count

        return await loop.run_in_executor(None, _c)

    async def get_all_ids(self) -> List[str]:
        if self.client is None or not self.client.collection_exists(self.collection_name):
            return []
        loop = asyncio.get_event_loop()

        def _scroll():
            chunk_ids: List[str] = []
            next_off = None
            while True:
                records, next_off = self.client.scroll(
                    collection_name=self.collection_name,
                    limit=256,
                    offset=next_off,
                    with_payload=True,
                    with_vectors=False,
                )
                if not records:
                    break
                for r in records:
                    pl = r.payload or {}
                    cid = pl.get("chunk_id")
                    if cid:
                        chunk_ids.append(str(cid))
                if next_off is None:
                    break
            return chunk_ids

        return await loop.run_in_executor(None, _scroll)

    async def get_by_document_id(self, document_id: str) -> List[str]:
        if self.client is None or not self.client.collection_exists(self.collection_name):
            return []
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        loop = asyncio.get_event_loop()
        flt = Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))])

        def _scroll():
            chunk_ids: List[str] = []
            next_off = None
            while True:
                records, next_off = self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=flt,
                    limit=256,
                    offset=next_off,
                    with_payload=True,
                    with_vectors=False,
                )
                if not records:
                    break
                for r in records:
                    pl = r.payload or {}
                    cid = pl.get("chunk_id")
                    if cid:
                        chunk_ids.append(str(cid))
                if next_off is None:
                    break
            return chunk_ids

        return await loop.run_in_executor(None, _scroll)

    async def list_documents(self) -> List[dict]:
        if self.client is None or not self.client.collection_exists(self.collection_name):
            return []
        loop = asyncio.get_event_loop()

        def _list():
            seen: Dict[str, dict] = {}
            next_off = None
            while True:
                records, next_off = self.client.scroll(
                    collection_name=self.collection_name,
                    limit=256,
                    offset=next_off,
                    with_payload=True,
                    with_vectors=False,
                )
                if not records:
                    break
                for r in records:
                    pl = r.payload or {}
                    doc_id = pl.get("document_id")
                    filename = pl.get("document_filename", "Unknown")
                    if not doc_id or str(filename).startswith((".", "tmp_")):
                        continue
                    if str(filename).endswith(".tmp"):
                        continue
                    if doc_id not in seen:
                        seen[str(doc_id)] = {
                            "document_id": doc_id,
                            "filename": filename,
                            "document_type": pl.get("document_type", "unknown"),
                        }
                if next_off is None:
                    break
            return list(seen.values())

        return await loop.run_in_executor(None, _list)

    async def clear_collection(self):
        if self.client is None:
            return
        loop = asyncio.get_event_loop()

        def _clear():
            if self.client.collection_exists(self.collection_name):
                self.client.delete_collection(self.collection_name)
            self._dimension = None

        await loop.run_in_executor(None, _clear)
        logger.info(f"Qdrant collection '{self.collection_name}' deleted (cleared)")
