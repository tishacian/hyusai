"""FAISS vector database implementation"""

import os
import pickle
from pathlib import Path
from typing import Optional

import numpy as np

from app.core.logging import get_logger
from app.services.vector_db.base import VectorDBBase

logger = get_logger(__name__)


class FAISSVectorDB(VectorDBBase):
    """FAISS-based vector database"""

    def __init__(self, persist_directory: str = "./faiss_db", collection_name: str = "documents"):
        self.persist_directory = persist_directory
        self.collection_name = collection_name
        self.index = None
        self.metadatas: dict[str, dict] = {}  # id -> metadata
        self.ids: list[str] = []  # Order matches index
        self.vectors: Optional[np.ndarray] = None
        self.dimension = None
        self._initialize()

    def _initialize(self):
        """Initialize FAISS index"""
        try:
            import faiss

            # Create persist directory if it doesn't exist
            Path(self.persist_directory).mkdir(parents=True, exist_ok=True)

            # Load existing index if available
            index_path = os.path.join(self.persist_directory, f"{self.collection_name}.index")
            metadata_path = os.path.join(
                self.persist_directory, f"{self.collection_name}.metadata.pkl"
            )

            if os.path.exists(index_path) and os.path.exists(metadata_path):
                try:
                    self.index = faiss.read_index(index_path)
                    with open(metadata_path, "rb") as f:
                        data = pickle.load(f)
                        self.metadatas = data.get("metadatas", {})
                        self.ids = data.get("ids", [])
                        self.dimension = self.index.d
                    logger.info(
                        f"Loaded existing FAISS index for collection '{self.collection_name}' with {len(self.ids)} vectors"
                    )
                except Exception as e:
                    logger.warning(f"Failed to load existing FAISS index: {e}, creating new one")
                    self.index = None

            if self.index is None:
                # Will be created when we know the dimension
                logger.info(f"Initialized FAISS for collection '{self.collection_name}'")
        except ImportError:
            logger.error("faiss-cpu not installed. Install with: pip install faiss-cpu")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize FAISS: {e}")
            raise

    def _ensure_index(self, dimension: int):
        """Ensure FAISS index exists with correct dimension"""
        if self.index is None or self.dimension != dimension:
            import faiss

            self.dimension = dimension
            # Use IndexFlatIP (Inner Product) for cosine similarity with normalized vectors
            # For cosine similarity, we'll normalize vectors and use inner product
            self.index = faiss.IndexFlatIP(dimension)
            logger.info(f"Created FAISS IndexFlatIP with dimension {dimension}")

    async def create_index(self, dimension: int, index_type: str = "default"):
        """Create FAISS index"""
        self._ensure_index(dimension)

    async def add_vectors(self, vectors: np.ndarray, metadatas: list[dict], ids: list[str]):
        """Add vectors to FAISS index"""
        import asyncio

        if len(vectors) == 0:
            return

        # Ensure index exists
        dimension = vectors.shape[1]
        self._ensure_index(dimension)

        # Normalize vectors for cosine similarity
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)  # Avoid division by zero
        normalized_vectors = vectors / norms

        loop = asyncio.get_event_loop()

        def _add():
            # Add to FAISS index
            self.index.add(normalized_vectors.astype("float32"))

            # Store metadata and IDs
            for vec_id, metadata in zip(ids, metadatas):
                self.ids.append(vec_id)
                self.metadatas[vec_id] = metadata

            # Save index and metadata
            self._save()

        await loop.run_in_executor(None, _add)
        logger.debug(f"Added {len(ids)} vectors to FAISS index")

    async def search(
        self, query_vector: np.ndarray, top_k: int = 10, filters: Optional[dict] = None
    ) -> list[dict]:
        """Search similar vectors"""
        import asyncio

        if self.index is None or self.index.ntotal == 0:
            return []

        # FAISS requires at least 1 result
        if top_k <= 0:
            return []

        # Normalize query vector for cosine similarity
        query_norm = np.linalg.norm(query_vector)
        if query_norm == 0:
            return []
        normalized_query = (query_vector / query_norm).astype("float32").reshape(1, -1)

        loop = asyncio.get_event_loop()

        def _search():
            # Search in FAISS
            k = min(top_k, self.index.ntotal)
            distances, indices = self.index.search(normalized_query, k)

            # Format results
            formatted_results = []
            for i, idx in enumerate(indices[0]):
                if idx < 0 or idx >= len(self.ids):
                    continue

                vec_id = self.ids[idx]
                metadata = self.metadatas.get(vec_id, {})

                # Convert distance to similarity score (for cosine similarity with normalized vectors)
                # FAISS returns inner product, which is cosine similarity for normalized vectors
                similarity = float(distances[0][i])

                # Apply filters if provided
                if filters:
                    match = True
                    for key, value in filters.items():
                        if metadata.get(key) != value:
                            match = False
                            break
                    if not match:
                        continue

                # Extract content from metadata for FAISS
                content = metadata.get("content", "")

                formatted_results.append(
                    {
                        "id": vec_id,
                        "score": max(0.0, min(1.0, similarity)),  # Clamp to [0, 1]
                        "metadata": metadata,
                        "content": content,  # Include content directly in result
                    }
                )

            return formatted_results

        return await loop.run_in_executor(None, _search)

    async def delete(self, ids: list[str]):
        """Delete vectors by IDs"""
        import asyncio

        if not ids or self.index is None:
            return

        loop = asyncio.get_event_loop()

        def _delete():
            ids_set = set(ids)
            remove_positions = [i for i, vid in enumerate(self.ids) if vid in ids_set]
            if not remove_positions:
                return

            keep_positions = [i for i in range(len(self.ids)) if i not in set(remove_positions)]

            # Reconstruct all current vectors from the FAISS index, keep only the survivors
            if self.index.ntotal > 0 and keep_positions:
                all_vecs = self.index.reconstruct_n(0, self.index.ntotal)
                kept_vecs = all_vecs[keep_positions].astype("float32")
                self._ensure_index(self.dimension)
                self.index.add(kept_vecs)
            else:
                self._ensure_index(self.dimension)  # empty index

            self.ids = [self.ids[i] for i in keep_positions]
            for vid in ids_set:
                self.metadatas.pop(vid, None)

            self._save()

        await loop.run_in_executor(None, _delete)
        logger.debug(f"Deleted {len(ids)} vectors from FAISS index")

    async def update(self, ids: list[str], vectors: np.ndarray, metadatas: list[dict]):
        """Update vectors"""
        # FAISS doesn't support updates, so delete and re-add
        await self.delete(ids)
        await self.add_vectors(vectors, metadatas, ids)

    async def get_count(self) -> int:
        """Get total number of vectors"""
        return len(self.ids)

    async def get_all_ids(self) -> list[str]:
        """Get all vector IDs"""
        return self.ids.copy()

    async def get_by_document_id(self, document_id: str) -> list[str]:
        """Get all chunk IDs associated with a document ID"""
        return [
            vec_id
            for vec_id in self.ids
            if self.metadatas.get(vec_id, {}).get("document_id") == document_id
        ]

    async def get_document_metadata(self, document_id: str) -> dict:
        """Return the full metadata dict of the first chunk for ``document_id``.

        Chunks of the same document share all ``document_*`` fields (set once
        at ingestion time by the docmeta adapter) so picking one is enough to
        surface title / author / keywords / token count to the UI.
        """
        for vec_id in self.ids:
            meta = self.metadatas.get(vec_id, {})
            if meta.get("document_id") == document_id:
                # Return a shallow copy so callers can mutate freely without
                # corrupting our in-memory index.
                return dict(meta)
        return {}

    async def list_documents(self) -> list[dict]:
        """List all unique documents in the collection"""
        seen_docs = {}
        for vec_id in self.ids:
            metadata = self.metadatas.get(vec_id, {})
            doc_id = metadata.get("document_id")
            filename = metadata.get("document_filename", "Unknown")

            # Filter out temporary files
            if filename.startswith(".") or filename.endswith(".tmp") or filename.startswith("tmp_"):
                continue
            if not doc_id or doc_id.startswith("temp_") or doc_id.startswith("tmp_"):
                continue

            if doc_id and doc_id not in seen_docs:
                seen_docs[doc_id] = {
                    "document_id": doc_id,
                    "filename": filename,
                    "document_type": metadata.get("document_type", "unknown"),
                }

        return list(seen_docs.values())

    async def list_payloads(
        self,
        filters: Optional[dict] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """List stored metadata payloads for diagnostics/table-fact browsing."""
        limit = max(1, min(int(limit or 100), 500))
        offset_count = max(0, int(offset or 0))
        out: list[dict] = []
        seen = 0
        for vec_id in self.ids:
            metadata = dict(self.metadatas.get(vec_id, {}))
            if filters:
                matched = True
                for key, value in filters.items():
                    if metadata.get(key) != value:
                        matched = False
                        break
                if not matched:
                    continue
            if seen < offset_count:
                seen += 1
                continue
            metadata.setdefault("chunk_id", vec_id)
            out.append(metadata)
            if len(out) >= limit:
                break
        return out

    async def sample_chunk_vectors(
        self,
        limit: int = 200,
        filters: Optional[dict] = None,
    ) -> list[dict]:
        """Sample points (with vectors) for the embedding-map visualization."""
        if self.vectors is None or not len(self.ids):
            return []
        limit = max(1, min(int(limit or 200), 1000))
        candidate_indices = []
        for idx, vec_id in enumerate(self.ids):
            if idx >= len(self.vectors):
                break
            metadata = self.metadatas.get(vec_id, {})
            if filters and not all(metadata.get(k) == v for k, v in filters.items()):
                continue
            candidate_indices.append(idx)

        if len(candidate_indices) > limit:
            step = len(candidate_indices) / float(limit)
            candidate_indices = [candidate_indices[int(i * step)] for i in range(limit)]

        out: list[dict] = []
        for idx in candidate_indices:
            vec_id = self.ids[idx]
            out.append(
                {
                    "id": str(vec_id),
                    "vector": [float(x) for x in self.vectors[idx]],
                    "payload": dict(self.metadatas.get(vec_id, {})),
                }
            )
        return out

    async def clear_collection(self):
        """Clear all vectors from the collection"""
        import asyncio

        loop = asyncio.get_event_loop()

        def _clear():
            if self.index is not None:
                self._ensure_index(self.dimension or 384)  # Reset index
            self.metadatas.clear()
            self.ids.clear()
            self.vectors = None
            self._save()

        await loop.run_in_executor(None, _clear)
        logger.info(f"Cleared all vectors from FAISS collection {self.collection_name}")

    def _save(self):
        """Save index and metadata to disk"""
        try:
            import faiss

            Path(self.persist_directory).mkdir(parents=True, exist_ok=True)
            index_path = os.path.join(self.persist_directory, f"{self.collection_name}.index")
            metadata_path = os.path.join(
                self.persist_directory, f"{self.collection_name}.metadata.pkl"
            )

            if self.index is not None:
                faiss.write_index(self.index, index_path)

            with open(metadata_path, "wb") as f:
                pickle.dump(
                    {
                        "metadatas": self.metadatas,
                        "ids": self.ids,
                    },
                    f,
                )
        except Exception as e:
            logger.warning(f"Failed to save FAISS index: {e}")
