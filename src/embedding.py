import logging
import pickle
import sys
from functools import lru_cache
from typing import Optional

import numpy as np
import psutil
import torch

from connections.qdrant import qdrant_client
from connections.storage import fs
from src.chunker import BM25Retriever, cache_chunker_embedding_chain
from src.embeddingloader import EmbeddingModelLoader
from src.globalvariables import EMBEDDING_NAME

USE_DYNAMIC_BATCHING_GLOBAL = True

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


@lru_cache(maxsize=None)
@cache_chunker_embedding_chain
class EmbeddingVectors:
    def __init__(
        self,
        tokenizer,
        model,
        target_collection: str,
        kb_uuid,
        source_collection: str | None = None,
        embedding_model_name=EMBEDDING_NAME,
        distance_metric: str = "cosine",
    ):
        """
        Creating embedding vector for a Qdrant collection.

        Parameters
        ----------
            tokenizer: tokenizer model
            model: HuggingFace model
            target_collection (str): Qdrant collection to create or append to.
            kb_uuid (str | UUID): Knowledge base UUID used to locate the BM25
                file in storage (knowledge-bases/{kb_uuid}/retrieval/).
            source_collection (str | None): If provided and target_collection
                does not yet exist, all points from this collection are copied
                into target_collection before new points are upserted.
                Must be None (or equal to target_collection) when
                target_collection already exists — merging into an existing
                collection is rejected with ValueError.
            embedding_model_name (str, optional): name of the embedding model.
                Defaults to "sentence-transformers/all-mpnet-base-v2".

        Returns
        ------
            None.

        """
        self.tokenizer = tokenizer
        self.model = model
        self.target_collection = target_collection
        self.kb_uuid = str(kb_uuid)
        self.source_collection = source_collection
        self.device = torch.device(
            "cuda"
            if torch.cuda.is_available()
            else "cpu"
            if torch.backends.mps.is_available()
            else "cpu"
        )
        self.embedding_model_name = embedding_model_name
        self.distance_metric = distance_metric
        self.embedding_model = EmbeddingModelLoader.load_embedding_model(
            embedding_model_name
        )
        # --
        self.embedding_dimension = EmbeddingModelLoader.get_embedding_dimension(
            embedding_model_name
        )

    def _calculate_dynamic_batch_size(self, texts, base_batch_size=32):
        """
        Calculate optimal batch size based on available memory and text
        characteristics.

        Parameters:
            texts (list): List of text chunks
            base_batch_size (int): Base batch size to start with

        Returns:
            int: Optimal batch size
        """
        try:
            available_memory = psutil.virtual_memory().available
            memory_gb = available_memory / (1024**3)
            avg_text_length = np.mean([len(text) for text in texts]) if texts else 1000
            estimated_memory_per_text = avg_text_length * 0.001
            # Reserve 70% of available memory for embeddings
            safe_memory = memory_gb * 0.7
            max_batch_by_memory = int((safe_memory * 1024) / estimated_memory_per_text)
            base_dimension = 768
            dimension_factor = max(1, self.embedding_dimension / base_dimension)
            adjusted_batch_size = max_batch_by_memory // dimension_factor
            min_batch_size = 1
            max_batch_size = min(128, len(texts))  # Cap at 128 or total texts

            optimal_batch_size = max(
                min_batch_size, min(max_batch_size, adjusted_batch_size)
            )

            if optimal_batch_size < 1:
                optimal_batch_size = base_batch_size

            logging.info(
                f"Dynamic batch size calculated: {optimal_batch_size} "
                f"(available memory: {memory_gb:.1f}GB, "
                f"avg text length: {avg_text_length:.0f}, "
                f"embedding dim: {self.embedding_dimension})"
            )

            return optimal_batch_size

        except Exception as e:
            logging.warning(
                f"Failed to calculate dynamic batch size: {e}. "
                f"Using base batch size: {base_batch_size}"
            )
            return base_batch_size

    @classmethod
    async def create_async(
        cls,
        tokenizer,
        model,
        target_collection: str,
        kb_uuid,
        source_collection: str | None = None,
        embedding_model_name=EMBEDDING_NAME,
    ):
        """
        Async factory method that creates an instance and initializes it asynchronously
        """
        instance = cls(
            tokenizer,
            model,
            target_collection,
            kb_uuid,
            source_collection,
            embedding_model_name,
        )

        # Then update the embedding model asynchronously
        instance.embedding_model = (
            await EmbeddingModelLoader.load_embedding_model_async(embedding_model_name)
        )
        return instance

    def create_embeddings(
        self,
        texts,
        batch_size: Optional[int] = None,
        use_dynamic_batching: Optional[bool] = None,
    ):
        """
        Create_embeddings.
        Creates embeddings using pre-loaded SentenceTransformer or tokenizer
        based on availability.

        Parameters:
            texts (str): input texts
            batch_size (int, optional): Fixed batch size. Default is 32.
            use_dynamic_batching (bool, optional): Whether to use dynamic batch sizing.
                                       If None, uses global configuration.

        Returns:
            np.array: The embedding vectors
        """
        if use_dynamic_batching is None:
            use_dynamic_batching = USE_DYNAMIC_BATCHING_GLOBAL

        # Determine batch size
        if use_dynamic_batching:
            self.batch_size = self._calculate_dynamic_batch_size(texts, 32)
        else:
            self.batch_size = 32 if not batch_size else batch_size

        logging.info(
            f"Using batch size: {self.batch_size} "
            f"(dynamic batching: {use_dynamic_batching})"
        )

        try:
            if not texts or len(texts) == 0:
                logging.error("🚩 Empty texts array received")
                empty_embeddings = np.zeros((0, self.embedding_dimension))
                self.last_embeddings_to_save = empty_embeddings.copy()
                return empty_embeddings

            logging.info(f"Creating embeddings on device: {self.device.type}")

            all_embeddings = []

            for i in range(0, len(texts), self.batch_size):
                batch_texts = texts[i : i + self.batch_size]

                embeddings = self.embedding_model.encode(
                    batch_texts,
                    show_progress_bar=(True if len(batch_texts) > 10 else False),
                    convert_to_tensor=True,
                    device=self.device.type,
                )
                batch_embeddings = embeddings.to(dtype=torch.float32).cpu().numpy()
                all_embeddings.append(batch_embeddings)

            # Combine batches
            if all_embeddings:
                combined_embeddings = np.vstack(all_embeddings)
                # -- verify the embedding dimension
                if combined_embeddings.shape[1] != self.embedding_dimension:
                    logging.warning(
                        f"Embedding dimension mismatch! Expected "
                        f"{self.embedding_dimension}, got "
                        f"{combined_embeddings.shape[1]}"
                    )
                    self.embedding_dimension = combined_embeddings.shape[1]
                    EmbeddingModelLoader._dimension_cache[self.embedding_model_name] = (
                        self.embedding_dimension
                    )

                self.last_embeddings_to_save = combined_embeddings.copy()
                return combined_embeddings

            logging.warning("No embeddings were created, returning empty array")
            empty_embeddings = np.zeros((0, self.embedding_dimension))
            self.last_embeddings_to_save = empty_embeddings.copy()
            return empty_embeddings

        except Exception as e:
            logging.error(f"🚩 Error creating embeddings: {e}")
            empty_embeddings = np.zeros((0, self.embedding_dimension))
            self.last_embeddings_to_save = empty_embeddings.copy()
            return empty_embeddings

    def save_index(self, texts):
        """
        Save index -- vector database
        If target_collection already exists, reuses its kb_uuid and upserts
        new points. Otherwise creates the collection (and optionally seeds it
        from source_collection when provided).

        Parameters:
                texts: input texts

        Returns
            None
        """
        try:
            from io import BytesIO

            from qdrant_client.models import Distance, PointStruct, VectorParams

            client = qdrant_client
            collection_name = self.target_collection
            embeddings = (
                self.last_embeddings_to_save
                if hasattr(self, "last_embeddings_to_save")
                else self.embeddings
            )

            # -- Check whether the target collection already exists in Qdrant
            collection_exists = False
            id_offset = 0
            try:
                client.get_collection(collection_name)
                collection_exists = True
            except Exception:
                collection_exists = False

            # -- Guard: merging a different source into an existing collection
            # is rejected to prevent data corruption.
            if (
                collection_exists
                and self.source_collection is not None
                and self.source_collection != self.target_collection
            ):
                raise ValueError(
                    f"Cannot merge '{self.source_collection}' into existing collection "
                    f"'{self.target_collection}'. To create a merged collection, set "
                    f"target_collection to a new name and "
                    f"source_collection='{self.target_collection}'."
                )

            if collection_exists:
                # Reuse the kb_uuid stored in the existing points so the BM25
                # file path stays consistent across ingestion sessions.
                first, _ = client.scroll(
                    collection_name=collection_name,
                    limit=1,
                    with_payload=True,
                    with_vectors=False,
                )
                if first and "bm25_path" in first[0].payload:
                    # path format: knowledge-bases/{kb_uuid}/retrieval/bm25_retriever.pkl
                    self.kb_uuid = first[0].payload["bm25_path"].split("/")[1]
                    logging.info(
                        f"Collection '{collection_name}' exists. "
                        f"Reusing kb_uuid: {self.kb_uuid}"
                    )
                id_offset = client.count(collection_name).count
                logging.info(
                    f"Collection '{collection_name}' has {id_offset} existing points. "
                    f"Adding {len(texts)} new points."
                )

            # -- BM25 path (uses the possibly-updated kb_uuid)
            bm25_path = fs.joinpath(
                "knowledge-bases", self.kb_uuid, "retrieval", "bm25_retriever.pkl"
            )

            try:
                if not collection_exists:
                    _distance_map = {
                        "cosine": Distance.COSINE,
                        "dot": Distance.DOT,
                        "euclidean": Distance.EUCLID,
                    }
                    distance = _distance_map.get(self.distance_metric, Distance.COSINE)
                    client.create_collection(
                        collection_name=collection_name,
                        vectors_config=VectorParams(
                            size=self.embedding_dimension,
                            distance=distance,
                        ),
                    )

                    if self.source_collection:
                        # Copy points from the source collection into the new one
                        scroll_offset = None
                        while True:
                            results, scroll_offset = client.scroll(
                                collection_name=self.source_collection,
                                with_vectors=True,
                                with_payload=True,
                                offset=scroll_offset,
                                limit=256,
                            )
                            if not results:
                                break
                            client.upsert(
                                collection_name=collection_name,
                                wait=True,
                                points=[
                                    PointStruct(
                                        id=p.id,
                                        vector=p.vector,
                                        payload={**p.payload, "bm25_path": bm25_path},
                                    )
                                    for p in results
                                ],
                            )
                            id_offset = max(p.id for p in results) + 1
                            if scroll_offset is None:
                                break
                        logging.info(
                            f"Copied {id_offset} points from "
                            f"'{self.source_collection}' to '{collection_name}'."
                        )

                # Upsert the new points (works for both new and existing collections)
                new_points = [
                    PointStruct(
                        id=id_offset + i,
                        vector=embeddings[i].tolist(),
                        payload={"text": text, "bm25_path": bm25_path},
                    )
                    for i, text in enumerate(texts)
                ]
                client.upsert(
                    collection_name=collection_name, wait=True, points=new_points
                )
                logging.info(
                    f"Qdrant collection '{collection_name}' ready with "
                    f"{id_offset + len(new_points)} points total."
                )
            except Exception as e:
                logging.warning(f"Qdrant upload skipped (server unavailable): {e}")

            # -- Build BM25 from Qdrant as the single source of truth.
            # Scroll the target collection after all writes so the index always
            # reflects exactly what is stored, regardless of the operation type.
            try:
                all_texts = []
                scroll_offset = None
                while True:
                    batch, scroll_offset = client.scroll(
                        collection_name=collection_name,
                        with_payload=True,
                        with_vectors=False,
                        offset=scroll_offset,
                        limit=256,
                    )
                    if not batch:
                        break
                    all_texts.extend(
                        p.payload["text"] for p in batch if "text" in p.payload
                    )
                    if scroll_offset is None:
                        break
                bm25_retriever = BM25Retriever(all_texts)
                buf = BytesIO()
                pickle.dump(bm25_retriever, buf)
                fs.write_to_file(bm25_path, buf)
                logging.info(
                    f"BM25 retriever saved to '{bm25_path}' ({len(all_texts)} texts)."
                )
            except Exception as e:
                logging.error(f"🚩 Error saving BM25 retriever: {e}")

        except Exception as e:
            logging.error(
                f"🚩 An error occurred while saving/merging the index: {str(e)}"
            )
            raise

    def create_and_save_index(
        self,
        texts,
        batch_size: Optional[int] = None,
        use_dynamic_batching: Optional[bool] = None,
    ):
        """
        Create and save the index -- vector DB with improved validation and
        error handling

        Parameters:
            texts (str): input texts
            batch_size (int, optional): Fixed batch size. Default is 32.
            use_dynamic_batching (bool, optional): Whether to use dynamic batch sizing.
                                       If None, uses global configuration.

        Return
            None
        """
        try:
            if not texts or len(texts) == 0:
                logging.error("🚩 Empty texts array received")
                return

            self.embeddings = self.create_embeddings(
                texts, batch_size, use_dynamic_batching
            )
            if self.embeddings is None or len(self.embeddings) == 0:
                logging.error("🚩 Failed to create embeddings")
                return

            if not hasattr(self, "last_embeddings_to_save"):
                self.last_embeddings_to_save = self.embeddings.copy()

            self.save_index(texts)
        except Exception as e:
            logging.error(f"🚩 Error in create_and_save_index: {e}")
