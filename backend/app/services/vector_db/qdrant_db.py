"""Qdrant vector database implementation (remote collection per logical collection name)."""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import time
import uuid
from collections import Counter
from typing import Any, Dict, List, Optional

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger
from app.services.rag.lexical_retrieval import (
    SPARSE_SCHEMA_VERSION,
    LexicalRetrievalConfig,
    analyze_query,
    enrich_payload_for_lexical_sparse,
    identifier_variants,
    lexical_match_details,
    metadata_search_text,
)
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
    "machine",
    "family",
    "section",
    "section_path",
    "chapter",
    "part_number",
    "archive_name",
    "source_family",
    "document_title",
    "inner_document_path",
    "parent_document_id",
    "parent_context_key",
    "sparse_schema_version",
    "retrieval_identifiers",
    "retrieval_terms",
    "language",
    "status",
)
_DENSE_VECTOR_NAME = "dense"
_SPARSE_VECTOR_NAME = "sparse"
_SPARSE_HASH_BUCKETS = 2_000_003
_SPARSE_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ0-9_.-]{2,}")

# Full-text index on the ``content`` payload field. Separate from the KEYWORD
# fields above: it powers the exhaustive inventory facet (project_inventory),
# turning a ~44 s full payload scan over 1.57 M points into a sub-second
# inverted-index lookup, and makes ``MatchText`` case-insensitive (lowercase=True),
# which removes the case-variant hack in project_inventory.
#
# Params decided empirically in the rollout's Phase 0 measurement GATE
# (qdrant/qdrant:v1.12.5-unprivileged supports ``multilingual``):
#   tokenizer=multilingual (FR/EN/DE/ES corpus), min_token_len=2, max_token_len=30,
#   lowercase=True, on_disk=True (keep the inverted index off the heap — the box
#   runs without swap).
#
# Growth rule (Phase 0): this index costs ~1.65 GiB RAM and ~0.61 GB disk per 1 M
# points (~2.6 GiB RAM / ~0.95 GB disk at the current 1.57 M points). The
# DOMINANT growth constraint is NOT this index but the dense 1536-d vectors held
# in RAM (``on_disk=None``); moving the dense vectors ``on_disk`` is the future
# lever if the box saturates (out of scope here).
_CONTENT_TEXT_INDEX_FIELD = "content"


def _content_text_index_schema() -> Any:
    """Build the ``content`` full-text index schema (defensive import).

    Returns ``None`` on an older qdrant-client without ``TextIndexParams`` so the
    lazy ensure path simply skips the text index instead of raising.
    """
    try:
        from qdrant_client.models import TextIndexParams, TokenizerType
    except Exception:  # pragma: no cover - old client fallback.
        return None
    return TextIndexParams(
        type="text",
        tokenizer=TokenizerType.MULTILINGUAL,
        min_token_len=2,
        max_token_len=30,
        lowercase=True,
        on_disk=True,
    )


def _sanitize_payload(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Qdrant payload: JSON-serializable scalars and keyword arrays."""
    out: Dict[str, Any] = {}
    for k, v in metadata.items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            out[str(k)] = v
        elif isinstance(v, (list, tuple, set)):
            values = [
                item
                for item in v
                if item is not None and isinstance(item, (str, int, float, bool)) and str(item) != ""
            ]
            if values:
                out[str(k)] = values
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


def _payload_for_sparse(payload: Dict[str, Any]) -> Dict[str, Any]:
    return enrich_payload_for_lexical_sparse(payload)


def _sparse_vector_from_payload(payload: Dict[str, Any]) -> Any:
    return _sparse_vector_from_text(metadata_search_text(payload))


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


def _qdrant_grouping(search_params: Optional[Dict[str, Any]]) -> Optional[tuple[str, int]]:
    if not search_params:
        return None
    raw_group_by = search_params.get("group_by") or search_params.get("qdrant_group_by")
    group_by = str(raw_group_by or "").strip()
    if not group_by or group_by.lower() in {"0", "false", "none", "off", "disabled"}:
        return None
    try:
        group_size = int(search_params.get("group_size") or search_params.get("qdrant_group_size") or 1)
    except (TypeError, ValueError):
        group_size = 1
    return group_by, max(1, min(group_size, 4))


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
        # Full-text index on ``content`` (separate from the KEYWORD loop above).
        # wait=False keeps the lazy ensure path cheap; the heavy build for
        # existing collections is done by scripts/backfill_content_text_index.py.
        content_schema = _content_text_index_schema()
        if content_schema is not None:
            try:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=_CONTENT_TEXT_INDEX_FIELD,
                    field_schema=content_schema,
                    wait=False,
                )
            except Exception as exc:  # noqa: BLE001 - idempotent/index-exists/old-server path.
                logger.debug(
                    "Qdrant content text index skipped",
                    collection=self.collection_name,
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

    def _collection_sparse_schema_ready(self) -> bool:
        if self.client is None or not self.client.collection_exists(self.collection_name):
            return False
        try:
            records, _ = self.client.scroll(
                collection_name=self.collection_name,
                limit=1,
                with_payload=True,
                with_vectors=False,
            )
            if not records:
                return True
            payload = dict(getattr(records[0], "payload", None) or {})
            return str(payload.get("sparse_schema_version") or "") == SPARSE_SCHEMA_VERSION
        except Exception as exc:  # noqa: BLE001 - schema marker is an optimization.
            logger.debug(
                "Qdrant sparse schema inspection failed",
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
                payload = _payload_for_sparse(_sanitize_payload(dict(metadatas[i])))
                payload["chunk_id"] = chunk_id
                vector: Any = normalized[i].tolist()
                if _qdrant_sparse_enabled():
                    vector = {
                        _DENSE_VECTOR_NAME: normalized[i].tolist(),
                        _SPARSE_VECTOR_NAME: _sparse_vector_from_payload(payload),
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
        """Backfill named dense+sparse vectors through a streaming alias cutover.

        Qdrant 1.12 cannot add sparse vectors to a legacy unnamed-dense
        collection in place. For production-sized corpora we therefore build a
        temporary hybrid collection batch by batch, then expose it through an alias
        with the original collection name. Reads continue on the old collection
        until the final alias cutover.
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
            named_sparse = self._collection_supports_named_sparse()
            if named_sparse and self._collection_sparse_schema_ready():
                return {
                    "status": "ready",
                    "configured": True,
                    "collection": self.collection_name,
                    "points_reindexed": self.client.count(collection_name=self.collection_name, exact=True).count,
                    "recreated_collection": False,
                    "alias_cutover": False,
                    "reason": "already_named_dense_sparse_metadata_v1",
                    "sparse_schema_version": SPARSE_SCHEMA_VERSION,
                }

            info = self.client.get_collection(collection_name=self.collection_name)
            vectors_config = getattr(getattr(info.config, "params", None), "vectors", None)
            if isinstance(vectors_config, dict):
                dense_config = vectors_config.get(_DENSE_VECTOR_NAME) or next(iter(vectors_config.values()), None)
                dimension = int(getattr(dense_config, "size", 0) or 0)
            else:
                dimension = int(getattr(vectors_config, "size", 0) or 0)
            if dimension <= 0:
                return {
                    "status": "skipped",
                    "configured": True,
                    "collection": self.collection_name,
                    "reason": "dense_dimension_unavailable",
                }

            from qdrant_client.models import (
                CreateAlias,
                CreateAliasOperation,
                Distance,
                PointStruct,
                VectorParams,
            )

            source_count = self.client.count(collection_name=self.collection_name, exact=True).count
            suffix = f"__hybrid_{int(time.time())}"
            temp_name = f"{self.collection_name}{suffix}"
            counter = 0
            while self.client.collection_exists(temp_name):
                counter += 1
                temp_name = f"{self.collection_name}{suffix}_{counter}"
            temp_db = QdrantVectorDB(collection_name=temp_name, client=self.client)
            self.client.create_collection(
                collection_name=temp_name,
                vectors_config={
                    _DENSE_VECTOR_NAME: VectorParams(size=dimension, distance=Distance.COSINE),
                },
                sparse_vectors_config=temp_db._sparse_vectors_config(),
            )
            temp_db._ensure_payload_indexes()
            requested_batch_size = batch_size if batch_size is not None else _batch_size()
            try:
                effective_batch_size = max(1, int(requested_batch_size))
            except (TypeError, ValueError):
                effective_batch_size = _batch_size()
            migrated = 0
            skipped = 0
            next_offset = None
            while True:
                records, next_offset = self.client.scroll(
                    collection_name=self.collection_name,
                    limit=min(1024, effective_batch_size),
                    offset=next_offset,
                    with_payload=True,
                    with_vectors=True,
                )
                if not records:
                    break
                points = []
                for record in records:
                    payload = _payload_for_sparse(_sanitize_payload(dict(getattr(record, "payload", None) or {})))
                    dense = _dense_vector_from_raw(getattr(record, "vector", None))
                    if dense is None:
                        skipped += 1
                        continue
                    chunk_id = str(payload.get("chunk_id") or "")
                    if chunk_id:
                        payload["chunk_id"] = chunk_id
                    dense_array = np.array(dense, dtype=np.float32)
                    norm = float(np.linalg.norm(dense_array)) or 1.0
                    normalized = (dense_array / norm).astype(np.float32).tolist()
                    points.append(
                        PointStruct(
                            id=getattr(record, "id"),
                            vector={
                                _DENSE_VECTOR_NAME: normalized,
                                _SPARSE_VECTOR_NAME: _sparse_vector_from_payload(payload),
                            },
                            payload=payload,
                        )
                    )
                if points:
                    self.client.upsert(collection_name=temp_name, wait=True, points=points)
                    migrated += len(points)
                if next_offset is None:
                    break

            temp_count = self.client.count(collection_name=temp_name, exact=True).count
            if temp_count != migrated or (source_count and migrated + skipped != source_count):
                return {
                    "status": "error",
                    "configured": True,
                    "collection": self.collection_name,
                    "temp_collection": temp_name,
                    "source_count": source_count,
                    "points_reindexed": migrated,
                    "points_skipped": skipped,
                    "temp_count": temp_count,
                    "reason": "copy_count_mismatch",
                }

            self.client.delete_collection(collection_name=self.collection_name)
            self.client.update_collection_aliases(
                [
                    CreateAliasOperation(
                        create_alias=CreateAlias(collection_name=temp_name, alias_name=self.collection_name)
                    )
                ]
            )
            self._payload_indexes_ensured = False

            return {
                "status": "ready",
                "configured": True,
                "collection": self.collection_name,
                "physical_collection": temp_name,
                "points_reindexed": migrated,
                "points_skipped": skipped,
                "source_count": source_count,
                "temp_count": temp_count,
                "recreated_collection": False,
                "alias_cutover": True,
                "dimension": dimension,
                "sparse_schema_version": SPARSE_SCHEMA_VERSION,
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

    @staticmethod
    def _groups_to_points(groups_result: Any, *, limit: int) -> List[Any]:
        groups = list(getattr(groups_result, "groups", None) or [])
        if not groups:
            return []
        max_group_size = max((len(getattr(group, "hits", None) or []) for group in groups), default=0)
        points: List[Any] = []
        for hit_index in range(max_group_size):
            for group in groups:
                hits = list(getattr(group, "hits", None) or [])
                if hit_index >= len(hits):
                    continue
                points.append(hits[hit_index])
                if len(points) >= limit:
                    return points
        return points

    @staticmethod
    def _annotate_grouping(rows: List[dict], grouping: Optional[tuple[str, int]]) -> List[dict]:
        if not grouping:
            return rows
        group_by, group_size = grouping
        for row in rows:
            row["qdrant_group_by"] = group_by
            row["qdrant_group_size"] = group_size
            metadata = dict(row.get("metadata") or {})
            metadata["qdrant_group_by"] = group_by
            metadata["qdrant_group_size"] = group_size
            row["metadata"] = metadata
        return rows

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
            grouping = _qdrant_grouping(search_params)
            if grouping and hasattr(self.client, "query_points_groups"):
                group_by, group_size = grouping
                try:
                    grouped_response = self.client.query_points_groups(
                        **kwargs,
                        group_by=group_by,
                        group_size=group_size,
                        with_payload=True,
                        with_vectors=False,
                    )
                    return self._annotate_grouping(
                        self._hits_to_results(self._groups_to_points(grouped_response, limit=top_k)),
                        grouping,
                    )
                except Exception as exc:  # noqa: BLE001 - grouping is an optimization.
                    logger.warning(
                        "Qdrant grouped dense search unavailable; falling back",
                        collection=self.collection_name,
                        group_by=group_by,
                        error=str(exc),
                    )
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
            grouping = _qdrant_grouping(search_params)
            try:
                query_kwargs = {
                    "collection_name": self.collection_name,
                    "prefetch": [
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
                    "query": FusionQuery(fusion=fusion),
                    "query_filter": qf,
                    "limit": top_k,
                }
                applied_grouping = None
                points = None
                if grouping and hasattr(self.client, "query_points_groups"):
                    group_by, group_size = grouping
                    try:
                        response = self.client.query_points_groups(
                            **query_kwargs,
                            group_by=group_by,
                            group_size=group_size,
                            with_payload=True,
                            with_vectors=False,
                        )
                        points = self._groups_to_points(response, limit=top_k)
                        applied_grouping = grouping
                    except Exception as exc:  # noqa: BLE001 - grouping is an optimization.
                        logger.warning(
                            "Qdrant grouped hybrid search unavailable; falling back",
                            collection=self.collection_name,
                            group_by=group_by,
                            error=str(exc),
                        )
                        response = self.client.query_points(**query_kwargs)
                        points = response.points
                if points is None:
                    response = self.client.query_points(**query_kwargs)
                    points = response.points
            except Exception as exc:  # noqa: BLE001 - old server / pre-migration fallback.
                logger.warning(
                    "Qdrant server-side hybrid search unavailable",
                    collection=self.collection_name,
                    error=str(exc),
                )
                return None
            rows = self._annotate_grouping(self._hits_to_results(points), applied_grouping)
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

    async def search_inventory_evidence(
        self,
        *,
        project_code: str,
        content_terms: List[str],
        limit: int = 6,
        scan_limit: int = 192,
    ) -> List[Dict[str, Any]]:
        """Return bounded, project-scoped evidence for equipment inventories.

        This is deliberately not another semantic/deep retrieval.  It uses the
        existing Qdrant payload indexes to sample chunks whose ``content``
        matches any active equipment term, plus authoritative spare-parts-list
        chunks for the same project.  Results remain real source chunks and are
        diversified by document before the caller adds a small coverage floor.
        """
        code = str(project_code or "").strip().upper()
        terms: list[str] = []
        for value in content_terms or []:
            term = " ".join(str(value or "").strip().split())
            if term and 2 < len(term) <= 80 and term.lower() not in {
                existing.lower() for existing in terms
            }:
                terms.append(term)
            if len(terms) >= 12:
                break
        if not code or not terms or limit <= 0 or self.client is None:
            return []

        from qdrant_client.models import FieldCondition, Filter, MatchText, MatchValue, MinShould

        loop = asyncio.get_event_loop()
        bounded_scan = max(limit, min(max(int(scan_limit or 192), 1), 384))
        bounded_limit = max(1, min(int(limit or 6), 12))

        def _search_inventory() -> List[Dict[str, Any]]:
            # ``collection_exists`` does not expose a request timeout in every
            # supported qdrant-client version (notably the production client),
            # unlike ``query_points*`` and ``scroll`` below.  The whole sync
            # lane is already fenced by the caller's 1.2 s asyncio budget.
            if not self.client.collection_exists(self.collection_name):
                return []
            project_condition = FieldCondition(key="project_code", match=MatchValue(value=code))
            text_conditions = [
                FieldCondition(key="content", match=MatchText(text=term)) for term in terms
            ]
            content_filter = Filter(
                must=[project_condition],
                min_should=MinShould(conditions=text_conditions, min_count=1),
            )
            spare_filter = Filter(
                must=[
                    project_condition,
                    FieldCondition(
                        key="source_family", match=MatchValue(value="spare_parts_list")
                    ),
                ]
            )

            def _scroll_bounded(qfilter: Any, *, cap: int) -> list[Any]:
                rows: list[Any] = []
                next_offset = None
                while len(rows) < cap:
                    page, next_offset = self.client.scroll(
                        collection_name=self.collection_name,
                        scroll_filter=qfilter,
                        limit=min(96, cap - len(rows)),
                        offset=next_offset,
                        with_payload=True,
                        with_vectors=False,
                        timeout=1,
                    )
                    rows.extend(page or [])
                    if not page or next_offset is None:
                        break
                return rows

            # Prefer the collection's native sparse index: it ranks matching
            # chunks and groups manuals by document instead of taking an
            # identifier-ordered scroll sample.  The bounded scroll remains a
            # compatibility fallback for pre-sparse collections.
            content_records: list[Any] = []
            spare_records: list[Any] = []
            sparse_query = _sparse_vector_from_text(" ".join(terms))
            if _qdrant_sparse_enabled() and sparse_query.indices:
                try:
                    if hasattr(self.client, "query_points_groups"):
                        grouped = self.client.query_points_groups(
                            collection_name=self.collection_name,
                            query=sparse_query,
                            using=_SPARSE_VECTOR_NAME,
                            query_filter=content_filter,
                            group_by="document_id",
                            group_size=1,
                            limit=min(bounded_scan, max(24, bounded_limit * 4)),
                            with_payload=True,
                            with_vectors=False,
                            timeout=1,
                        )
                        content_records = self._groups_to_points(
                            grouped,
                            limit=bounded_scan,
                        )
                    else:
                        response = self.client.query_points(
                            collection_name=self.collection_name,
                            query=sparse_query,
                            using=_SPARSE_VECTOR_NAME,
                            query_filter=content_filter,
                            limit=min(bounded_scan, max(24, bounded_limit * 4)),
                            with_payload=True,
                            with_vectors=False,
                            timeout=1,
                        )
                        content_records = list(getattr(response, "points", None) or [])
                except Exception as exc:  # noqa: BLE001 - sparse is an optimization.
                    logger.debug(
                        "Qdrant grouped inventory evidence unavailable",
                        collection=self.collection_name,
                        error=str(exc),
                    )
                    content_records = []
                try:
                    response = self.client.query_points(
                        collection_name=self.collection_name,
                        query=sparse_query,
                        using=_SPARSE_VECTOR_NAME,
                        query_filter=spare_filter,
                        limit=min(4, bounded_scan),
                        with_payload=True,
                        with_vectors=False,
                        timeout=1,
                    )
                    spare_records = list(getattr(response, "points", None) or [])
                except Exception as exc:  # noqa: BLE001 - sparse is an optimization.
                    logger.debug(
                        "Qdrant sparse spare-parts evidence unavailable",
                        collection=self.collection_name,
                        error=str(exc),
                    )
                    spare_records = []

            if not content_records:
                try:
                    content_records = _scroll_bounded(content_filter, cap=bounded_scan)
                except Exception as exc:  # noqa: BLE001 - lane is best-effort.
                    logger.debug(
                        "Qdrant inventory evidence scan unavailable",
                        collection=self.collection_name,
                        error=str(exc),
                    )
            if not spare_records:
                try:
                    spare_records = _scroll_bounded(
                        spare_filter,
                        cap=min(32, bounded_scan),
                    )
                except Exception as exc:  # noqa: BLE001 - lane is best-effort.
                    logger.debug(
                        "Qdrant spare-parts evidence scan unavailable",
                        collection=self.collection_name,
                        error=str(exc),
                    )

            records = [*content_records, *spare_records]

            by_point: dict[str, dict[str, Any]] = {}
            for record in records:
                payload = dict(getattr(record, "payload", None) or {})
                if str(payload.get("project_code") or "").strip().upper() != code:
                    # Keep the application-side invariant even if a test double
                    # or a temporarily inconsistent payload index misbehaves.
                    continue
                content = str(payload.get("content") or "").strip()
                if len(content) < 20:
                    continue
                searchable = " ".join(
                    str(value or "").lower()
                    for value in (
                        content,
                        payload.get("document_filename"),
                        payload.get("document_title"),
                        payload.get("inner_document_path"),
                    )
                )
                matched = [term for term in terms if term.lower() in searchable]
                if not matched:
                    # The spare-parts pass is a source-family recall floor, but
                    # unrelated parts must never enter an equipment answer.
                    continue
                href_count = searchable.count("href")
                word_count = len(_SPARSE_TOKEN_RE.findall(content))
                if href_count >= 8 and word_count < 160:
                    continue
                source_family = str(payload.get("source_family") or "").lower()
                filename = str(payload.get("document_filename") or "")
                filename_matches = sum(1 for term in matched if term.lower() in filename.lower())
                try:
                    sparse_score = min(max(float(getattr(record, "score", 0.0) or 0.0), 0.0), 1.0)
                except (TypeError, ValueError):
                    sparse_score = 0.0
                document_haystack = " ".join(
                    str(payload.get(key) or "").lower()
                    for key in (
                        "document_filename",
                        "document_title",
                        "inner_document_path",
                        "document_type",
                        "source_kind",
                    )
                )
                is_pdf = (
                    str(payload.get("extension") or "").strip().lower() == "pdf"
                    or filename.lower().endswith(".pdf")
                )
                is_manual = source_family in {
                    "pump_manual",
                    "supplier_manual",
                    "operating_manual",
                    "operator_manual",
                } or bool(
                    re.search(
                        r"\b(manual|manuel|notice|service|operating|operation|montage)\b",
                        f"{document_haystack} {content[:1200].lower()}",
                    )
                )
                score = (
                    0.35
                    + min(len(matched), 4) * 0.08
                    + min(filename_matches, 2) * 0.04
                    + (0.18 if source_family == "spare_parts_list" else 0.0)
                    + (0.06 if is_manual else 0.0)
                    + (0.03 if is_pdf else 0.0)
                    + sparse_score * 0.12
                    - (0.08 if href_count >= 8 else 0.0)
                )
                metadata = dict(payload)
                metadata["inventory_evidence_backend"] = "qdrant_payload_fulltext"
                metadata["inventory_match_terms"] = matched[:12]
                metadata["inventory_sparse_score"] = sparse_score
                point_key = str(
                    payload.get("chunk_id")
                    or getattr(record, "id", None)
                    or hashlib.sha1(content.encode("utf-8")).hexdigest()
                )
                by_point[point_key] = {
                    "id": str(payload.get("chunk_id") or getattr(record, "id", point_key)),
                    "content": content,
                    "score": min(score, 0.95),
                    "metadata": metadata,
                }

            ranked = sorted(
                by_point.values(),
                key=lambda row: (
                    -float(row.get("score") or 0.0),
                    str((row.get("metadata") or {}).get("document_filename") or "").lower(),
                ),
            )
            selected: list[dict[str, Any]] = []
            document_counts: dict[str, int] = {}
            family_counts: dict[str, int] = {}
            category_counts: dict[str, int] = {}
            seen_content: set[str] = set()

            def document_family_keys(
                metadata: Dict[str, Any],
                document_key: str,
            ) -> tuple[str, str]:
                # Separate the functional folder (diversity category) from the
                # actual equipment/model family.  Language roots such as
                # ``PRJ204-ES`` are ignored, while numeric model variants remain
                # distinct.  A PDF directly under a functional folder derives
                # its family from its filename (Etabloc vs Etachrom, for example).
                path = str(metadata.get("inner_document_path") or "").strip()
                path_parts = [part for part in re.split(r"[/\\]+", path) if part]
                significant: list[str] = []
                for part in path_parts[:-1]:
                    normalized = re.sub(r"[^a-z0-9]+", "-", part.lower()).strip("-")
                    if (
                        not normalized
                        or normalized == code.lower()
                        or re.fullmatch(
                            rf"{re.escape(code.lower())}-(?:de|en|es|fr)",
                            normalized,
                        )
                        or normalized in {"de", "en", "es", "fr", "files", "fichiers", "manuals"}
                        or re.fullmatch(r"section-?\d+", normalized)
                    ):
                        continue
                    significant.append(normalized)
                filename = (
                    path_parts[-1]
                    if path_parts
                    else str(metadata.get("document_filename") or document_key)
                ).lower()
                filename = re.sub(r"\.(?:html?|pdf)$", "", filename)
                filename = re.sub(r"(?:[-_. ]+)(?:de|en|es|fr)$", "", filename)
                filename_key = re.sub(r"[^a-z0-9]+", "-", filename).strip("-")
                category = significant[0] if significant else filename_key
                family = significant[-1] if len(significant) > 1 else filename_key
                return (
                    f"family:{family or document_key}",
                    f"category:{category or document_key}",
                )

            def add_rows(
                rows: List[Dict[str, Any]],
                *,
                cap: int,
                per_document: int,
                per_family: int,
                per_category: int,
            ) -> None:
                for row in rows:
                    metadata = row.get("metadata") or {}
                    document_key = str(
                        metadata.get("document_id")
                        or metadata.get("document_filename")
                        or row.get("id")
                    )
                    content_key = hashlib.sha1(
                        " ".join(str(row.get("content") or "").split()).encode("utf-8")
                    ).hexdigest()
                    family_key, category_key = document_family_keys(metadata, document_key)
                    if (
                        not document_key
                        or content_key in seen_content
                        or document_counts.get(document_key, 0) >= per_document
                        or family_counts.get(family_key, 0) >= per_family
                        or category_counts.get(category_key, 0) >= per_category
                    ):
                        continue
                    seen_content.add(content_key)
                    document_counts[document_key] = document_counts.get(document_key, 0) + 1
                    family_counts[family_key] = family_counts.get(family_key, 0) + 1
                    category_counts[category_key] = category_counts.get(category_key, 0) + 1
                    selected.append(row)
                    if len(selected) >= cap:
                        return

            spare_rows = [
                row
                for row in ranked
                if str((row.get("metadata") or {}).get("source_family") or "").lower()
                == "spare_parts_list"
            ]
            add_rows(
                spare_rows,
                cap=min(2, bounded_limit),
                per_document=2,
                per_family=2,
                per_category=2,
            )
            if len(selected) < bounded_limit:
                add_rows(
                    ranked,
                    cap=bounded_limit,
                    per_document=1,
                    per_family=1,
                    per_category=1,
                )
            if len(selected) < bounded_limit:
                add_rows(
                    ranked,
                    cap=bounded_limit,
                    per_document=1,
                    per_family=1,
                    per_category=2,
                )
            return selected[:bounded_limit]

        return await loop.run_in_executor(None, _search_inventory)

    async def parent_contexts_for_hits(
        self,
        metadatas: List[Dict[str, Any]],
        *,
        max_parents: int = 3,
        max_chars: int = 2500,
    ) -> List[Dict[str, Any]]:
        """Return coarse parent contexts for already-ranked child hits.

        Current collections may not have explicit parent ids yet, so the
        fallback parent key is document + optional section metadata. This keeps
        the retrieval shape generic and lets richer parent/child indexes plug in
        later without changing the chat context contract.
        """
        if self.client is None or not self.client.collection_exists(self.collection_name):
            return []
        seeds: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for meta in metadatas or []:
            if not isinstance(meta, dict):
                continue
            parent_id = str(meta.get("parent_document_id") or "").strip()
            document_id = str(meta.get("document_id") or "").strip()
            filename = str(meta.get("document_filename") or "").strip()
            section = str(meta.get("section_path") or meta.get("section") or "").strip()
            key = parent_id or document_id or filename
            if not key:
                continue
            scoped_key = "|".join(part for part in (key, section) if part)
            if scoped_key in seen_keys:
                continue
            seen_keys.add(scoped_key)
            seeds.append(dict(meta))
            if len(seeds) >= max(1, int(max_parents or 1)):
                break
        if not seeds:
            return []

        loop = asyncio.get_event_loop()

        def _chunk_index(payload: dict[str, Any]) -> int | None:
            try:
                return int(payload.get("chunk_index"))
            except (TypeError, ValueError):
                return None

        def _seed_filters(seed: dict[str, Any], *, include_section: bool) -> dict[str, Any]:
            filters: dict[str, Any] = {}
            parent_id = str(seed.get("parent_document_id") or "").strip()
            if parent_id:
                filters["parent_document_id"] = parent_id
            elif seed.get("document_id"):
                filters["document_id"] = seed.get("document_id")
            elif seed.get("document_filename"):
                filters["document_filename"] = seed.get("document_filename")
            if include_section:
                if seed.get("section_path"):
                    filters["section_path"] = seed.get("section_path")
                elif seed.get("section"):
                    filters["section"] = seed.get("section")
            return filters

        def _scroll_parent(seed: dict[str, Any]) -> dict[str, Any] | None:
            qf = self._filters_to_qdrant(_seed_filters(seed, include_section=True))
            if qf is None:
                return None
            self._ensure_payload_indexes_once()
            records, _ = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=qf,
                limit=80,
                with_payload=True,
                with_vectors=False,
            )
            if not records and (seed.get("section_path") or seed.get("section")):
                qf = self._filters_to_qdrant(_seed_filters(seed, include_section=False))
                if qf is not None:
                    records, _ = self.client.scroll(
                        collection_name=self.collection_name,
                        scroll_filter=qf,
                        limit=80,
                        with_payload=True,
                        with_vectors=False,
                    )
            payloads = [dict(getattr(record, "payload", None) or {}) for record in records or []]
            payloads = [payload for payload in payloads if str(payload.get("content") or "").strip()]
            if not payloads:
                return None
            seed_index = _chunk_index(seed)
            if seed_index is not None:
                payloads.sort(
                    key=lambda payload: (
                        abs((_chunk_index(payload) if _chunk_index(payload) is not None else seed_index) - seed_index),
                        _chunk_index(payload) if _chunk_index(payload) is not None else 10**9,
                    )
                )
            else:
                payloads.sort(key=lambda payload: _chunk_index(payload) if _chunk_index(payload) is not None else 10**9)

            selected: list[dict[str, Any]] = []
            total_chars = 0
            max_chars_local = max(500, int(max_chars or 2500))
            for payload in payloads:
                content = str(payload.get("content") or "").strip()
                if not content:
                    continue
                if selected and total_chars + len(content) > max_chars_local:
                    continue
                selected.append(payload)
                total_chars += len(content)
                if total_chars >= max_chars_local:
                    break
            if not selected:
                return None
            selected.sort(key=lambda payload: _chunk_index(payload) if _chunk_index(payload) is not None else 10**9)
            content_parts = [str(payload.get("content") or "").strip() for payload in selected]
            content = "\n\n".join(part for part in content_parts if part)[:max_chars_local]
            first = dict(selected[0])
            parent_key = str(
                seed.get("parent_context_key")
                or seed.get("parent_document_id")
                or seed.get("document_id")
                or seed.get("document_filename")
                or ""
            )
            first.update(
                {
                    "content": content,
                    "parent_context": True,
                    "parent_context_backend": "qdrant_payload",
                    "parent_context_key": parent_key,
                    "parent_context_chunk_count": len(selected),
                    "parent_context_seed_chunk_index": seed.get("chunk_index"),
                    "parent_context_seed_document_filename": seed.get("document_filename"),
                }
            )
            return {"content": content, "metadata": first, "score": 0.35}

        def _collect():
            rows: list[dict[str, Any]] = []
            for seed in seeds:
                row = _scroll_parent(seed)
                if row:
                    rows.append(row)
            return rows

        return await loop.run_in_executor(None, _collect)

    async def search_exact_metadata(
        self,
        query: str,
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        lexical_config: Optional[LexicalRetrievalConfig] = None,
    ) -> List[Dict[str, Any]]:
        """Search exact metadata candidates via payload keyword indexes.

        This is intentionally conservative: it only runs when the query analysis
        yields exact identifiers or configured document-type aliases.
        """
        if top_k <= 0 or self.client is None or not self.client.collection_exists(self.collection_name):
            return []
        config = lexical_config or LexicalRetrievalConfig()
        signals = analyze_query(query, config)
        if not signals.exact_terms and not signals.document_type_aliases:
            return []

        from qdrant_client.models import FieldCondition, Filter, MatchAny

        base_filter = self._filters_to_qdrant(filters or {})
        must = list(getattr(base_filter, "must", None) or [])
        for exact_term in signals.exact_terms:
            variants = sorted({term.lower() for term in identifier_variants(exact_term) if term})
            if variants:
                must.append(FieldCondition(key="retrieval_identifiers", match=MatchAny(any=variants)))

        document_type_terms: list[str] = []
        for alias in signals.document_type_aliases:
            document_type_terms.extend(token.lower() for token in re.findall(r"[A-Za-zÀ-ÿ0-9]{2,}", alias))
        if document_type_terms:
            must.append(FieldCondition(key="retrieval_terms", match=MatchAny(any=sorted(set(document_type_terms)))))

        if not must:
            return []

        qf = Filter(must=must)
        self._ensure_payload_indexes_once()
        loop = asyncio.get_event_loop()

        def _scroll_exact():
            records_out: list[dict[str, Any]] = []
            seen_docs: set[str] = set()
            next_off = None
            max_scan = min(max(top_k * 64, 512), 2000)
            scanned = 0
            while len(records_out) < top_k and scanned < max_scan:
                records, next_off = self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=qf,
                    limit=min(256, max_scan - scanned),
                    offset=next_off,
                    with_payload=True,
                    with_vectors=False,
                )
                if not records:
                    break
                scanned += len(records)
                for record in records:
                    payload = dict(getattr(record, "payload", None) or {})
                    doc_key = str(payload.get("document_id") or payload.get("document_filename") or record.id)
                    if doc_key in seen_docs:
                        continue
                    details = lexical_match_details(
                        content=str(payload.get("content") or ""),
                        metadata=payload,
                        query=query,
                        config=config,
                    )
                    if details.get("requires_exact_match") and not details.get("matched_exact_terms"):
                        continue
                    metadata = dict(payload)
                    metadata["exact_metadata_match"] = True
                    metadata["exact_metadata_backend"] = "qdrant_payload"
                    metadata["retrieval_lexical_score"] = int(details.get("score") or 0)
                    metadata["retrieval_exact_terms_matched"] = list(details.get("matched_exact_terms") or [])
                    metadata["retrieval_document_types_matched"] = list(details.get("matched_document_types") or [])
                    metadata["retrieval_exact_match_missing"] = bool(details.get("missing_exact_match"))
                    score = max(1.0, float(details.get("score") or 0))
                    records_out.append(
                        {
                            "id": str(payload.get("chunk_id") or record.id),
                            "content": str(payload.get("content") or ""),
                            "score": score,
                            "combined_score": score,
                            "vector_score": 0.0,
                            "bm25_score": score,
                            "metadata": metadata,
                        }
                    )
                    seen_docs.add(doc_key)
                    if len(records_out) >= top_k:
                        break
                if next_off is None:
                    break
            records_out.sort(key=lambda item: float(item.get("combined_score") or 0.0), reverse=True)
            return records_out[:top_k]

        return await loop.run_in_executor(None, _scroll_exact)

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
