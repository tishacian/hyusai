"""Qdrant vector database implementation (remote collection per logical collection name)."""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import uuid
from collections import Counter
from typing import Any, Dict, List, Optional

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger
from app.services.vector_db.base import VectorDBBase

logger = get_logger(__name__)

# Fixed namespace for deterministic UUID point ids from string chunk ids
_CHUNK_ID_NAMESPACE = uuid.UUID("018f3f8e-7b4e-7f3a-9c0d-4a6b8e1c2d30")
_PAYLOAD_INDEX_FIELDS = (
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
)
_DENSE_VECTOR_NAME = "dense"
_SPARSE_VECTOR_NAME = "sparse"
_SPARSE_HASH_BUCKETS = 2_000_003
_SPARSE_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ0-9_.-]{2,}")


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


def _batch_size() -> int:
    try:
        size = int(settings.qdrant_upsert_batch_size)
    except (TypeError, ValueError):
        return 128
    return max(1, size)


def _qdrant_sparse_enabled() -> bool:
    return bool(getattr(settings, "rag_qdrant_sparse_enabled", False))


def _sparse_index(token: str) -> int:
    digest = hashlib.blake2b(token.encode("utf-8", errors="ignore"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % _SPARSE_HASH_BUCKETS


def _sparse_vector_from_text(text: str) -> Any:
    from qdrant_client.models import SparseVector

    tokens = [token.lower() for token in _SPARSE_TOKEN_RE.findall(text or "")]
    if not tokens:
        return SparseVector(indices=[], values=[])
    counts = Counter(tokens)
    buckets: dict[int, float] = {}
    for token, count in counts.items():
        buckets[_sparse_index(token)] = buckets.get(_sparse_index(token), 0.0) + math.log1p(float(count))
    norm = math.sqrt(sum(value * value for value in buckets.values())) or 1.0
    ordered = sorted(buckets)
    return SparseVector(
        indices=ordered,
        values=[float(buckets[index] / norm) for index in ordered],
    )


def _qdrant_search_params(search_params: Optional[Dict[str, Any]]) -> Any:
    if not search_params:
        return None
    from qdrant_client.models import QuantizationSearchParams, SearchParams

    profile = str(search_params.get("retrieval_profile") or "").strip().lower()
    explicit_ef = search_params.get("hnsw_ef")
    hnsw_ef: int | None = None
    try:
        if explicit_ef is not None:
            hnsw_ef = max(1, int(explicit_ef))
    except (TypeError, ValueError):
        hnsw_ef = None
    if hnsw_ef is None:
        profile_to_ef = {
            "oracle_fast": getattr(settings, "rag_qdrant_oracle_hnsw_ef", 32),
            "chat": getattr(settings, "rag_qdrant_chat_hnsw_ef", 64),
            "deep_async": getattr(settings, "rag_qdrant_deep_hnsw_ef", 128),
        }
        try:
            hnsw_ef = int(profile_to_ef.get(profile) or 0) or None
        except (TypeError, ValueError):
            hnsw_ef = None
    quantization = None
    if profile in {"oracle_fast", "chat"} and bool(getattr(settings, "rag_qdrant_quantized_search_enabled", True)):
        quantization = QuantizationSearchParams(ignore=False, rescore=True)
    elif profile == "deep_async":
        quantization = QuantizationSearchParams(ignore=True)
    if hnsw_ef is None and quantization is None:
        return None
    return SearchParams(hnsw_ef=hnsw_ef, quantization=quantization)


def _qdrant_fusion(search_params: Optional[Dict[str, Any]]) -> Any:
    from qdrant_client.models import Fusion

    requested = str((search_params or {}).get("fusion") or getattr(settings, "rag_qdrant_hybrid_fusion", "rrf"))
    requested = requested.strip().lower()
    if requested == "dbsf":
        return Fusion.DBSF
    return Fusion.RRF


def _dense_vector_from_raw(raw: Any) -> Optional[List[float]]:
    if raw is None:
        return None
    if isinstance(raw, dict):
        raw = raw.get(_DENSE_VECTOR_NAME) or next(
            (value for value in raw.values() if isinstance(value, (list, tuple))),
            None,
        )
    if raw is None:
        return None
    try:
        return [float(value) for value in raw]
    except (TypeError, ValueError):
        return None


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
        self._payload_indexes_ensured = False

    def _point_id(self, chunk_id: str) -> str:
        return str(uuid.uuid5(_CHUNK_ID_NAMESPACE, f"{self.collection_name}:{chunk_id}"))

    def _vectors_config(self, dimension: int) -> Any:
        from qdrant_client.models import Distance, VectorParams

        if not _qdrant_sparse_enabled():
            return VectorParams(size=dimension, distance=Distance.COSINE)
        return {
            _DENSE_VECTOR_NAME: VectorParams(size=dimension, distance=Distance.COSINE),
        }

    def _sparse_vectors_config(self) -> Optional[Any]:
        if not _qdrant_sparse_enabled():
            return None
        try:
            from qdrant_client.models import SparseIndexParams, SparseVectorParams

            return {
                _SPARSE_VECTOR_NAME: SparseVectorParams(
                    index=SparseIndexParams(on_disk=False),
                )
            }
        except Exception as exc:  # pragma: no cover - qdrant-client version guard.
            logger.warning("Qdrant sparse vector config unavailable", error=str(exc))
            return None

    def _create_collection(self, dimension: int) -> None:
        kwargs = {
            "collection_name": self.collection_name,
            "vectors_config": self._vectors_config(dimension),
        }
        sparse_vectors_config = self._sparse_vectors_config()
        if sparse_vectors_config is not None:
            kwargs["sparse_vectors_config"] = sparse_vectors_config
        self.client.create_collection(**kwargs)

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
        self._dimension = dimension
        if self.client.collection_exists(self.collection_name):
            self._ensure_payload_indexes()
            return
        self._create_collection(dimension)
        self._ensure_payload_indexes()
        logger.info(f"Created Qdrant collection '{self.collection_name}' dim={dimension}")

    def _ensure_collection(self, dimension: int):
        self._dimension = dimension
        if not self.client.collection_exists(self.collection_name):
            self._create_collection(dimension)
            self._ensure_payload_indexes()

    def _ensure_payload_indexes(self):
        if self.client is None:
            return
        try:
            from qdrant_client.models import PayloadSchemaType
        except Exception:  # pragma: no cover - old client fallback
            PayloadSchemaType = None  # type: ignore
        for field in _PAYLOAD_INDEX_FIELDS:
            try:
                kwargs = {
                    "collection_name": self.collection_name,
                    "field_name": field,
                    "wait": False,
                }
                if PayloadSchemaType is not None:
                    kwargs["field_schema"] = PayloadSchemaType.KEYWORD
                self.client.create_payload_index(**kwargs)
            except Exception as exc:  # noqa: BLE001 - idempotent/index-exists path.
                logger.debug(
                    "Qdrant payload index skipped",
                    collection=self.collection_name,
                    field=field,
                    error=str(exc),
                )
        self._payload_indexes_ensured = True

    def _ensure_payload_indexes_once(self):
        if self._payload_indexes_ensured or self.client is None:
            return
        self._ensure_payload_indexes()

    def _collection_supports_named_sparse(self) -> bool:
        if self.client is None:
            return False
        try:
            info = self.client.get_collection(collection_name=self.collection_name)
            params = getattr(getattr(info, "config", None), "params", None)
            vectors = getattr(params, "vectors", None)
            sparse_vectors = getattr(params, "sparse_vectors", None)
            dense_ok = isinstance(vectors, dict) and _DENSE_VECTOR_NAME in vectors
            sparse_ok = isinstance(sparse_vectors, dict) and _SPARSE_VECTOR_NAME in sparse_vectors
            return bool(dense_ok and sparse_ok)
        except Exception as exc:  # noqa: BLE001 - old clients may not expose config.
            logger.debug(
                "Qdrant collection config inspection failed",
                collection=self.collection_name,
                error=str(exc),
            )
            return False

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
                vector: Any = normalized[i].tolist()
                if _qdrant_sparse_enabled():
                    vector = {
                        _DENSE_VECTOR_NAME: normalized[i].tolist(),
                        _SPARSE_VECTOR_NAME: _sparse_vector_from_text(str(payload.get("content") or "")),
                    }
                points.append(
                    PointStruct(id=pid, vector=vector, payload=payload)
                )
            batch_size = _batch_size()
            for start in range(0, len(points), batch_size):
                batch = points[start : start + batch_size]
                self.client.upsert(
                    collection_name=self.collection_name,
                    wait=True,
                    points=batch,
                )

        await loop.run_in_executor(None, _add)
        logger.debug(f"Qdrant upserted {len(ids)} points into '{self.collection_name}'")

    async def reindex_sparse_vectors(self, batch_size: Optional[int] = None) -> Dict[str, Any]:
        """Backfill named dense+sparse vectors for an existing Qdrant collection.

        Legacy collections used a single unnamed dense vector. Qdrant sparse search
        needs a named dense vector plus a named sparse vector per chunk, so this
        method scrolls all points, rebuilds the collection schema when required,
        and re-upserts payloads with deterministic chunk ids.
        """
        if self.client is None:
            return {"status": "skipped", "configured": False, "reason": "qdrant_client_missing"}
        if not _qdrant_sparse_enabled():
            return {"status": "skipped", "configured": False, "reason": "qdrant_sparse_disabled"}
        if not self.client.collection_exists(self.collection_name):
            return {
                "status": "skipped",
                "configured": True,
                "reason": "collection_missing",
                "collection": self.collection_name,
            }

        loop = asyncio.get_event_loop()

        def _reindex() -> Dict[str, Any]:
            records: List[Dict[str, Any]] = []
            next_offset = None
            while True:
                batch, next_offset = self.client.scroll(
                    collection_name=self.collection_name,
                    limit=512,
                    offset=next_offset,
                    with_payload=True,
                    with_vectors=True,
                )
                if not batch:
                    break
                for record in batch:
                    payload = _sanitize_payload(dict(getattr(record, "payload", None) or {}))
                    dense = _dense_vector_from_raw(getattr(record, "vector", None))
                    if dense is None:
                        continue
                    chunk_id = str(payload.get("chunk_id") or getattr(record, "id", ""))
                    if not chunk_id:
                        continue
                    payload["chunk_id"] = chunk_id
                    records.append(
                        {
                            "point_id": self._point_id(chunk_id),
                            "chunk_id": chunk_id,
                            "payload": payload,
                            "dense": dense,
                        }
                    )
                if next_offset is None:
                    break

            if not records:
                return {
                    "status": "ready",
                    "configured": True,
                    "collection": self.collection_name,
                    "points_reindexed": 0,
                    "recreated_collection": False,
                    "reason": "no_vectors_found",
                }

            dimension = len(records[0]["dense"])
            recreate_collection = not self._collection_supports_named_sparse()
            if recreate_collection:
                self.client.delete_collection(collection_name=self.collection_name)
                self._create_collection(dimension)
                self._payload_indexes_ensured = False
                self._ensure_payload_indexes()

            from qdrant_client.models import PointStruct

            requested_batch_size = batch_size if batch_size is not None else _batch_size()
            try:
                effective_batch_size = max(1, int(requested_batch_size))
            except (TypeError, ValueError):
                effective_batch_size = _batch_size()

            points = []
            for record in records:
                dense_array = np.array(record["dense"], dtype=np.float32)
                norm = float(np.linalg.norm(dense_array)) or 1.0
                normalized = (dense_array / norm).astype(np.float32).tolist()
                payload = dict(record["payload"])
                points.append(
                    PointStruct(
                        id=record["point_id"],
                        vector={
                            _DENSE_VECTOR_NAME: normalized,
                            _SPARSE_VECTOR_NAME: _sparse_vector_from_text(str(payload.get("content") or "")),
                        },
                        payload=payload,
                    )
                )

            for start in range(0, len(points), effective_batch_size):
                self.client.upsert(
                    collection_name=self.collection_name,
                    wait=True,
                    points=points[start : start + effective_batch_size],
                )

            return {
                "status": "ready",
                "configured": True,
                "collection": self.collection_name,
                "points_reindexed": len(points),
                "recreated_collection": recreate_collection,
                "dimension": dimension,
                "sparse_vector_name": _SPARSE_VECTOR_NAME,
                "dense_vector_name": _DENSE_VECTOR_NAME,
            }

        result = await loop.run_in_executor(None, _reindex)
        logger.info(
            "Qdrant sparse vectors reindexed",
            collection=self.collection_name,
            status=result.get("status"),
            points=result.get("points_reindexed"),
            recreated=result.get("recreated_collection"),
        )
        return result

    def _filters_to_qdrant(self, filters: Optional[Dict]) -> Optional[Any]:
        if not filters:
            return None
        from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

        must = []
        for key, value in filters.items():
            if value in (None, "", []):
                continue
            if isinstance(value, (list, tuple, set)):
                values = [item for item in value if item not in (None, "")]
                if values:
                    must.append(FieldCondition(key=str(key), match=MatchAny(any=list(values))))
            else:
                must.append(FieldCondition(key=str(key), match=MatchValue(value=value)))
        return Filter(must=must) if must else None

    @staticmethod
    def _hits_to_results(points: Any) -> List[dict]:
        out: List[dict] = []
        for hit in points:
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

    async def search(
        self,
        query_vector: np.ndarray,
        top_k: int = 10,
        filters: Optional[dict] = None,
        search_params: Optional[Dict[str, Any]] = None,
    ) -> List[dict]:
        if top_k <= 0 or self.client is None:
            return []
        if not self.client.collection_exists(self.collection_name):
            return []

        loop = asyncio.get_event_loop()
        qf = self._filters_to_qdrant(filters)
        if qf is not None:
            self._ensure_payload_indexes_once()

        def _search():
            qn = np.linalg.norm(query_vector)
            if qn == 0:
                return []
            q = (query_vector / qn).astype(np.float32).tolist()
            kwargs = {
                "collection_name": self.collection_name,
                "query": q,
                "limit": top_k,
                "query_filter": qf,
            }
            qdrant_params = _qdrant_search_params(search_params)
            if qdrant_params is not None:
                kwargs["search_params"] = qdrant_params
            if _qdrant_sparse_enabled():
                kwargs["using"] = _DENSE_VECTOR_NAME
            try:
                res = self.client.query_points(**kwargs)
            except Exception:
                if "using" not in kwargs:
                    raise
                # Existing pre-migration collections are still single unnamed
                # dense vectors. Keep them searchable until the sparse reindex
                # job rebuilds the collection with named vectors.
                kwargs.pop("using", None)
                res = self.client.query_points(**kwargs)
            return self._hits_to_results(res.points)

        return await loop.run_in_executor(None, _search)

    async def search_sparse(
        self,
        query: str,
        top_k: int = 10,
        filters: Optional[dict] = None,
    ) -> List[dict]:
        if top_k <= 0 or self.client is None or not _qdrant_sparse_enabled():
            return []
        if not self.client.collection_exists(self.collection_name):
            return []

        loop = asyncio.get_event_loop()
        qf = self._filters_to_qdrant(filters)
        if qf is not None:
            self._ensure_payload_indexes_once()

        def _search_sparse():
            sparse_query = _sparse_vector_from_text(query)
            if not sparse_query.indices:
                return []
            try:
                response = self.client.query_points(
                    collection_name=self.collection_name,
                    query=sparse_query,
                    using=_SPARSE_VECTOR_NAME,
                    limit=top_k,
                    query_filter=qf,
                )
            except Exception as exc:  # noqa: BLE001 - old/non-sparse collection fallback.
                logger.warning(
                    "Qdrant sparse search unavailable",
                    collection=self.collection_name,
                    error=str(exc),
                )
                return []
            rows = self._hits_to_results(response.points)
            for row in rows:
                row["sparse_backend"] = "qdrant_sparse"
                row["bm25_score"] = row.get("score", 0.0)
                row["vector_score"] = 0.0
                row["combined_score"] = row.get("score", 0.0)
                metadata = dict(row.get("metadata") or {})
                metadata["sparse_backend"] = "qdrant_sparse"
                row["metadata"] = metadata
            return rows

        return await loop.run_in_executor(None, _search_sparse)

    async def search_hybrid(
        self,
        query_vector: np.ndarray,
        query_text: str,
        top_k: int = 10,
        filters: Optional[dict] = None,
        search_params: Optional[Dict[str, Any]] = None,
    ) -> Optional[List[dict]]:
        if top_k <= 0 or self.client is None or not _qdrant_sparse_enabled():
            return None
        if not self.client.collection_exists(self.collection_name):
            return []

        loop = asyncio.get_event_loop()
        qf = self._filters_to_qdrant(filters)
        if qf is not None:
            self._ensure_payload_indexes_once()

        def _search_hybrid():
            from qdrant_client.models import FusionQuery, Prefetch

            qn = np.linalg.norm(query_vector)
            if qn == 0:
                return []
            dense_query = (query_vector / qn).astype(np.float32).tolist()
            sparse_query = _sparse_vector_from_text(query_text)
            if not sparse_query.indices:
                return None
            qdrant_params = _qdrant_search_params(search_params)
            fusion = _qdrant_fusion(search_params)
            try:
                response = self.client.query_points(
                    collection_name=self.collection_name,
                    prefetch=[
                        Prefetch(
                            query=dense_query,
                            using=_DENSE_VECTOR_NAME,
                            filter=qf,
                            params=qdrant_params,
                            limit=top_k,
                        ),
                        Prefetch(
                            query=sparse_query,
                            using=_SPARSE_VECTOR_NAME,
                            filter=qf,
                            limit=top_k,
                        ),
                    ],
                    query=FusionQuery(fusion=fusion),
                    query_filter=qf,
                    limit=top_k,
                )
            except Exception as exc:  # noqa: BLE001 - old server / pre-migration fallback.
                logger.warning(
                    "Qdrant server-side hybrid search unavailable",
                    collection=self.collection_name,
                    error=str(exc),
                )
                return None
            rows = self._hits_to_results(response.points)
            for row in rows:
                row["sparse_backend"] = "qdrant_sparse"
                row["sparse_fusion"] = f"server_{str(fusion.value)}"
                row["bm25_score"] = 0.0
                row["vector_score"] = row.get("score", 0.0)
                row["combined_score"] = row.get("score", 0.0)
                metadata = dict(row.get("metadata") or {})
                metadata["sparse_backend"] = "qdrant_sparse"
                metadata["sparse_status"] = "ok"
                metadata["sparse_fusion"] = row["sparse_fusion"]
                row["metadata"] = metadata
            return rows

        return await loop.run_in_executor(None, _search_hybrid)

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

    async def count_payloads(self, filters: Optional[Dict[str, Any]] = None) -> Optional[int]:
        if self.client is None or not self.client.collection_exists(self.collection_name):
            return 0
        loop = asyncio.get_event_loop()
        qf = self._filters_to_qdrant(filters)
        if qf is not None:
            self._ensure_payload_indexes_once()

        def _c():
            return self.client.count(
                collection_name=self.collection_name,
                count_filter=qf,
                exact=True,
            ).count

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
        self._ensure_payload_indexes_once()

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

    async def get_document_metadata(self, document_id: str) -> dict:
        """Return the payload of a single chunk matching ``document_id``.

        Used by ``GET /documents/{id}/metadata`` to surface docmeta-sourced
        fields (title, author, keywords, token count) to the UI — all chunks
        of a document share these fields so one payload is enough.
        """
        if self.client is None or not self.client.collection_exists(self.collection_name):
            return {}
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        loop = asyncio.get_event_loop()
        flt = Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))])
        self._ensure_payload_indexes_once()

        def _scroll_first():
            records, _ = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=flt,
                limit=1,
                with_payload=True,
                with_vectors=False,
            )
            if not records:
                return {}
            return dict(records[0].payload or {})

        return await loop.run_in_executor(None, _scroll_first)

    async def list_payloads(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List payloads for diagnostics/table-fact browsing."""
        if self.client is None or not self.client.collection_exists(self.collection_name):
            return []
        limit = max(1, min(int(limit or 100), 500))
        offset_count = max(0, int(offset or 0))
        qf = self._filters_to_qdrant(filters)
        if qf is not None:
            self._ensure_payload_indexes_once()
        loop = asyncio.get_event_loop()

        def _scroll_payloads():
            out: List[Dict[str, Any]] = []
            seen = 0
            next_off = None
            while len(out) < limit:
                records, next_off = self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=qf,
                    limit=256,
                    offset=next_off,
                    with_payload=True,
                    with_vectors=False,
                )
                if not records:
                    break
                for record in records:
                    if seen < offset_count:
                        seen += 1
                        continue
                    payload = dict(record.payload or {})
                    payload.setdefault("point_id", str(record.id))
                    out.append(payload)
                    if len(out) >= limit:
                        break
                if next_off is None:
                    break
            return out

        return await loop.run_in_executor(None, _scroll_payloads)

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
                    key = f"{doc_id}:{filename}"
                    if key not in seen:
                        seen[key] = {
                            "document_id": doc_id,
                            "filename": filename,
                            "document_type": pl.get("document_type", "unknown"),
                            "chunk_count": 0,
                            "chunks_count": 0,
                        }
                    seen[key]["chunk_count"] += 1
                    seen[key]["chunks_count"] = seen[key]["chunk_count"]
                if next_off is None:
                    break
            return list(seen.values())

        return await loop.run_in_executor(None, _list)

    async def sample_chunk_vectors(
        self,
        limit: int = 200,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Sample points (with vectors) for the embedding-map visualization."""
        if self.client is None or not self.client.collection_exists(self.collection_name):
            return []
        limit = max(1, min(int(limit or 200), 1000))
        qf = self._filters_to_qdrant(filters)
        if qf is not None:
            self._ensure_payload_indexes_once()
        loop = asyncio.get_event_loop()

        def _as_vector(raw) -> Optional[List[float]]:
            if raw is None:
                return None
            if isinstance(raw, dict):  # named vectors — take the first dense one.
                raw = next((v for v in raw.values() if isinstance(v, (list, tuple))), None)
            if raw is None:
                return None
            return [float(x) for x in raw]

        def _sample():
            out: List[Dict[str, Any]] = []
            # Prefer a true random sample (Qdrant >= 1.11); fall back to scroll.
            try:
                from qdrant_client import models as qmodels

                response = self.client.query_points(
                    collection_name=self.collection_name,
                    query=qmodels.SampleQuery(sample=qmodels.Sample.RANDOM),
                    query_filter=qf,
                    limit=limit,
                    with_payload=True,
                    with_vectors=True,
                )
                points = getattr(response, "points", response) or []
                for p in points:
                    vector = _as_vector(getattr(p, "vector", None))
                    if vector is None:
                        continue
                    out.append(
                        {"id": str(p.id), "vector": vector, "payload": dict(p.payload or {})}
                    )
                if out:
                    return out
            except Exception as exc:  # noqa: BLE001 - fall back to deterministic scroll.
                logger.debug("Qdrant random sample unavailable, scrolling instead", error=str(exc))

            next_off = None
            while len(out) < limit:
                records, next_off = self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=qf,
                    limit=min(256, limit - len(out)),
                    offset=next_off,
                    with_payload=True,
                    with_vectors=True,
                )
                if not records:
                    break
                for r in records:
                    vector = _as_vector(getattr(r, "vector", None))
                    if vector is None:
                        continue
                    out.append(
                        {"id": str(r.id), "vector": vector, "payload": dict(r.payload or {})}
                    )
                    if len(out) >= limit:
                        break
                if next_off is None:
                    break
            return out

        return await loop.run_in_executor(None, _sample)

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
