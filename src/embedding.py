import logging
import pickle
import sys
from datetime import datetime
from functools import lru_cache
from typing import Optional

import numpy as np
import psutil
import torch

from src.chunker import BM25Retriever, cache_chunker_embedding_chain
from src.embeddingloader import EmbeddingModelLoader
from src.globalvariables import (
    EMBEDDING_NAME,
    VECTOR_STORE_PATH,
)

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
        create_new_vs,
        existing_vector_store,
        new_vs_name,
        embedding_model_name=EMBEDDING_NAME,
        embedding_type="qdrant",
        normalize_embeddings=True,
        normalization_strategy="l2",
        log_normalization_stats=True,
        detect_already_normalized=True,
    ):
        """
        Creating embedding vector for different vector class

        Parameters
        ----------
            tokenizer (tokenizer model): tokenizer model)
            model (huggingface model): The model of choice. loading is usually from HuggingFace.
            create_new_vs (str): flag to create a new index
            existing_vector_store (str): flag to indicate existing vector store
            new_vs_name (str): New vector store name. name are separated by
                underscore (_). e.x This_is_a_new_vector_store_name
            embedding_model_name (embedding model), optional: name of the
                embedding model used for HuggingFaceInstructEmbeddings.
                The default is "sentence-transformers/all-mpnet-base-v2".
            embedding_type (str), optional: Type of embedding. The default is "qdrant".
            normalize_embeddings (bool), optional: Whether to normalize
                embeddings before storage. Default is True.
            normalization_strategy (str), optional: Normalization strategy
                ("l2", "min_max", "z_score"). Default is "l2".
            log_normalization_stats (bool), optional: Whether to log
                normalization statistics. Default is True.
            detect_already_normalized (bool), optional: Whether to detect
                already normalized vectors. Default is True.

        Raises
        ------
            ValueError : Returns ValueError in case of unsupported vector name.

        Returns
        ------
            None.

        """
        self.tokenizer = tokenizer
        self.model = model
        self.embedding_type = embedding_type
        self.create_new_vs = create_new_vs
        self.existing_vector_store = existing_vector_store
        self.new_vs_name = new_vs_name
        self.device = torch.device(
            "cuda"
            if torch.cuda.is_available()
            else "cpu"
            if torch.backends.mps.is_available()
            else "cpu"
        )
        self.embedding_model_name = embedding_model_name
        self.embedding_model = EmbeddingModelLoader.load_embedding_model(
            self.embedding_type, embedding_model_name
        )
        # --
        self.embedding_dimension = EmbeddingModelLoader.get_embedding_dimension(
            self.embedding_type, embedding_model_name
        )

        # Normalization configuration
        self.normalize_embeddings = normalize_embeddings
        self.normalization_strategy = normalization_strategy
        self.log_normalization_stats = log_normalization_stats
        self.detect_already_normalized = detect_already_normalized

    def normalize_embeddings_l2(self, embeddings, in_place=False):
        """
        Intelligent L2 normalization with safety checks and optimization

        Parameters:
            embeddings (np.ndarray): Input embeddings array
            in_place (bool): Whether to modify the array in-place for memory efficiency

        Returns:
            np.ndarray: L2 normalized embeddings
            dict: Normalization metadata (original norms, zero vector count, etc.)
        """
        return self.normalize_embeddings_strategy(embeddings, "l2", in_place)

    def normalize_embeddings_strategy(self, embeddings, strategy="l2", in_place=False):
        """
        Intelligent normalization with multiple strategy support

        Parameters:
            embeddings (np.ndarray): Input embeddings array
            strategy (str): Normalization strategy ("l2", "min_max", "z_score")
            in_place (bool): Whether to modify the array in-place for memory efficiency

        Returns:
            np.ndarray: Normalized embeddings
            dict: Normalization metadata
        """
        if embeddings is None or len(embeddings) == 0:
            return embeddings, {}

        if not isinstance(embeddings, np.ndarray):
            embeddings = np.array(embeddings)

        # -- detect if vectors are already normalized to avoid redundant processing
        if self.detect_already_normalized:
            if self._is_already_normalized(embeddings, strategy):
                if self.log_normalization_stats:
                    logging.info(
                        f"Embeddings already {strategy} normalized, skipping normalization"
                    )
                return embeddings, {
                    "already_normalized": True,
                    "strategy": strategy,
                }

        if strategy == "l2":
            return self._normalize_l2(embeddings, in_place)
        elif strategy == "min_max":
            return self._normalize_min_max(embeddings, in_place)
        elif strategy == "z_score":
            return self._normalize_z_score(embeddings, in_place)
        else:
            logging.warning(
                f"Unknown normalization strategy: {strategy}. Falling back to L2."
            )
            return self._normalize_l2(embeddings, in_place)

    def _normalize_l2(self, embeddings, in_place=False):
        """
        L2 normalization implementation
        """
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)  # l_2 norm
        zero_mask = norms < 1e-10
        zero_count = np.sum(zero_mask)

        if zero_count > 0:
            epsilon = 1e-8
            logging.warning(
                f"Found {zero_count} zero vectors, setting to small epsilon = {epsilon}"
            )
            norms[zero_mask] = epsilon

        if in_place:
            embeddings /= norms
            normalized_embeddings = embeddings
        else:
            normalized_embeddings = embeddings / norms

        # -- normalization statistics
        metadata = {
            "original_norms": norms.flatten(),
            "zero_vectors": zero_count,
            "avg_original_norm": float(np.mean(norms)),
            "min_original_norm": float(np.min(norms)),
            "max_original_norm": float(np.max(norms)),
            "already_normalized": False,
            "strategy": "l2",
        }

        # Verify normalization quality
        final_norms = np.linalg.norm(normalized_embeddings, axis=1)
        norm_std = np.std(final_norms)
        if norm_std > 1e-6:
            logging.warning(
                f"L2 normalization quality check failed: std={norm_std:.2e}"
            )

        self.last_normalization_metadata = metadata

        return normalized_embeddings, metadata

    def _normalize_min_max(self, embeddings, in_place=False):
        """
        Min-Max normalization (scales to [0, 1] range)
        """
        if in_place:
            embeddings_copy = embeddings
        else:
            embeddings_copy = embeddings.copy()

        min_vals = np.min(embeddings_copy, axis=0, keepdims=True)
        max_vals = np.max(embeddings_copy, axis=0, keepdims=True)
        range_vals = max_vals - min_vals
        constant_mask = range_vals < 1e-10
        constant_count = np.sum(constant_mask)

        if constant_count > 0:
            logging.warning(
                f"Found {constant_count} constant dimensions, setting range to 1"
            )
            range_vals[constant_mask] = 1.0

        normalized_embeddings = (embeddings_copy - min_vals) / range_vals

        metadata = {
            "min_vals": min_vals.flatten(),
            "max_vals": max_vals.flatten(),
            "range_vals": range_vals.flatten(),
            "constant_dimensions": constant_count,
            "already_normalized": False,
            "strategy": "min_max",
        }

        final_min = np.min(normalized_embeddings, axis=0)
        final_max = np.max(normalized_embeddings, axis=0)
        if not (
            np.allclose(final_min, 0, atol=1e-6)
            and np.allclose(final_max, 1, atol=1e-6)
        ):
            logging.warning("Min-max normalization quality check failed")

        self.last_normalization_metadata = metadata

        return normalized_embeddings, metadata

    def _normalize_z_score(self, embeddings, in_place=False):
        """
        Z-score normalization (standardization)
        """
        if in_place:
            embeddings_copy = embeddings
        else:
            embeddings_copy = embeddings.copy()

        mean_vals = np.mean(embeddings_copy, axis=0, keepdims=True)
        std_vals = np.std(embeddings_copy, axis=0, keepdims=True)
        zero_std_mask = std_vals < 1e-10
        zero_std_count = np.sum(zero_std_mask)

        if zero_std_count > 0:
            logging.warning(
                f"Found {zero_std_count} dimensions with zero std, setting to 1"
            )
            std_vals[zero_std_mask] = 1.0

        normalized_embeddings = (embeddings_copy - mean_vals) / std_vals

        metadata = {
            "mean_vals": mean_vals.flatten(),
            "std_vals": std_vals.flatten(),
            "zero_std_dimensions": zero_std_count,
            "already_normalized": False,
            "strategy": "z_score",
        }

        final_mean = np.mean(normalized_embeddings, axis=0)
        final_std = np.std(normalized_embeddings, axis=0)
        if not (
            np.allclose(final_mean, 0, atol=1e-6)
            and np.allclose(final_std, 1, atol=1e-6)
        ):
            logging.warning("Z-score normalization quality check failed")

        self.last_normalization_metadata = metadata

        return normalized_embeddings, metadata

    def _is_already_normalized(self, embeddings, strategy="l2", tolerance=1e-5):
        """
        Detect if embeddings are already normalized using the specified strategy

        Parameters:
            embeddings (np.ndarray): Input embeddings array
            strategy (str): Normalization strategy to check
            tolerance (float): Tolerance for considering vectors as normalized

        Returns:
            bool: True if embeddings appear to be already normalized
        """
        if embeddings is None or len(embeddings) == 0:
            return False

        if strategy == "l2":
            norms = np.linalg.norm(embeddings, axis=1)
            return np.allclose(norms, 1.0, atol=tolerance)
        elif strategy == "min_max":
            min_vals = np.min(embeddings, axis=0)
            max_vals = np.max(embeddings, axis=0)
            return np.allclose(min_vals, 0, atol=tolerance) and np.allclose(
                max_vals, 1, atol=tolerance
            )
        elif strategy == "z_score":
            mean_vals = np.mean(embeddings, axis=0)
            std_vals = np.std(embeddings, axis=0)
            return np.allclose(mean_vals, 0, atol=tolerance) and np.allclose(
                std_vals, 1, atol=tolerance
            )
        else:
            norms = np.linalg.norm(embeddings, axis=1)
            return np.allclose(norms, 1.0, atol=tolerance)

    def _log_normalization_impact(
        self, original_embeddings, normalized_embeddings, metadata
    ):
        """
        Log normalization quality metrics

        Parameters:
            original_embeddings (np.ndarray): Original embeddings
            normalized_embeddings (np.ndarray): Normalized embeddings
            metadata (dict): Normalization metadata
        """
        if not self.log_normalization_stats:
            return

        try:
            if len(original_embeddings) > 1:
                n_samples = min(10, len(original_embeddings) // 2)
                indices = np.random.choice(
                    len(original_embeddings), n_samples * 2, replace=False
                )

                original_similarities = []
                normalized_similarities = []

                for i in range(0, len(indices), 2):
                    if i + 1 < len(indices):
                        idx1, idx2 = indices[i], indices[i + 1]
                        orig_sim = np.dot(
                            original_embeddings[idx1],
                            original_embeddings[idx2],
                        ) / (
                            np.linalg.norm(original_embeddings[idx1])
                            * np.linalg.norm(original_embeddings[idx2])
                        )
                        original_similarities.append(orig_sim)
                        norm_sim = np.dot(
                            normalized_embeddings[idx1],
                            normalized_embeddings[idx2],
                        )
                        normalized_similarities.append(norm_sim)

                if original_similarities and normalized_similarities:
                    sim_diff = np.mean(
                        np.abs(
                            np.array(original_similarities)
                            - np.array(normalized_similarities)
                        )
                    )
                    logging.info(
                        f"Normalization similarity preservation: avg diff={sim_diff:.6f}"
                    )

            # -- log normalization stats
            strategy = metadata.get("strategy", "unknown")
            if strategy == "l2":
                logging.info(
                    f"L2 Normalization completed: "
                    f"vectors={len(normalized_embeddings)}, "
                    f"zero_vectors={metadata.get('zero_vectors', 0)}, "
                    f"avg_original_norm={metadata.get('avg_original_norm', 0):.3f}"
                )
            elif strategy == "min_max":
                logging.info(
                    f"Min-Max Normalization completed: "
                    f"vectors={len(normalized_embeddings)}, "
                    f"constant_dimensions={metadata.get('constant_dimensions', 0)}"
                )
            elif strategy == "z_score":
                logging.info(
                    f"Z-Score Normalization completed: "
                    f"vectors={len(normalized_embeddings)}, "
                    f"zero_std_dimensions={metadata.get('zero_std_dimensions', 0)}"
                )
            else:
                logging.info(
                    f"{strategy.title()} Normalization completed: "
                    f"vectors={len(normalized_embeddings)}"
                )

        except Exception as e:
            logging.warning(f"Could not calculate normalization impact metrics: {e}")

    def _normalize_in_batches(self, embeddings, batch_size=1000):
        """
        Handle large embedding arrays efficiently with batch processing

        Parameters:
            embeddings (np.ndarray): Input embeddings array
            batch_size (int): Batch size for processing

        Returns:
            np.ndarray: Normalized embeddings
            dict: Normalization metadata
        """
        if len(embeddings) <= batch_size:
            return self.normalize_embeddings_l2(embeddings, in_place=False)

        logging.info(f"Processing normalization in batches of {batch_size}")
        all_metadata = []
        normalized_batches = []

        for i in range(0, len(embeddings), batch_size):
            batch = embeddings[i : i + batch_size]
            normalized_batch, metadata = self.normalize_embeddings_strategy(
                batch, self.normalization_strategy, in_place=False
            )
            normalized_batches.append(normalized_batch)
            all_metadata.append(metadata)

            if self.log_normalization_stats:
                progress = min(100, (i + batch_size) / len(embeddings) * 100)
                logging.info(
                    f"{self.normalization_strategy} normalization progress: {progress:.1f}%"
                )

        # -- batch normalization
        combined_embeddings = np.vstack(normalized_batches)

        # Aggregate metadata based on strategy
        if self.normalization_strategy == "l2":
            combined_metadata = {
                "zero_vectors": sum(m.get("zero_vectors", 0) for m in all_metadata),
                "avg_original_norm": np.mean(
                    [m.get("avg_original_norm", 0) for m in all_metadata]
                ),
                "min_original_norm": min(
                    [m.get("min_original_norm", float("inf")) for m in all_metadata]
                ),
                "max_original_norm": max(
                    [m.get("max_original_norm", 0) for m in all_metadata]
                ),
                "already_normalized": False,
                "batch_processed": True,
                "strategy": self.normalization_strategy,
            }
        elif self.normalization_strategy == "min_max":
            combined_metadata = {
                "constant_dimensions": sum(
                    m.get("constant_dimensions", 0) for m in all_metadata
                ),
                "already_normalized": False,
                "batch_processed": True,
                "strategy": self.normalization_strategy,
            }
        elif self.normalization_strategy == "z_score":
            combined_metadata = {
                "zero_std_dimensions": sum(
                    m.get("zero_std_dimensions", 0) for m in all_metadata
                ),
                "already_normalized": False,
                "batch_processed": True,
                "strategy": self.normalization_strategy,
            }
        else:
            combined_metadata = {
                "already_normalized": False,
                "batch_processed": True,
                "strategy": self.normalization_strategy,
            }

        return combined_embeddings, combined_metadata

    def validate_normalization_consistency(self, save_path):
        """
        Validate normalization consistency when loading existing indices

        Parameters:
            save_path (Path): Path to the vector store

        Returns:
            bool: True if normalization is consistent, False otherwise
        """
        try:
            dimension_info_path = save_path / "dimension_info.pkl"
            if not dimension_info_path.exists():
                logging.warning(
                    "No dimension info found, cannot validate normalization"
                )
                return True

            with open(dimension_info_path, "rb") as f:
                existing_info = pickle.load(f)

            # -- check for existing normalization..
            existing_normalization = existing_info.get("normalization_applied", False)
            existing_strategy = existing_info.get("normalization_strategy", "unknown")

            if existing_normalization != self.normalize_embeddings:
                logging.warning(
                    f"Normalization mismatch: existing index has "
                    f"normalization={existing_normalization}, "
                    f"current setting={self.normalize_embeddings}"
                )
                return False

            if (
                existing_normalization
                and existing_strategy != self.normalization_strategy
            ):
                logging.warning(
                    f"Normalization strategy mismatch: existing index uses "
                    f"{existing_strategy}, current setting={self.normalization_strategy}"
                )
                return False

            return True

        except Exception as e:
            logging.error(f"Error validating normalization consistency: {e}")
            return False

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
        create_new_vs,
        existing_vector_store,
        new_vs_name,
        embedding_model_name=EMBEDDING_NAME,
        embedding_type="qdrant",
        normalize_embeddings=True,
        normalization_strategy="l2",
        log_normalization_stats=True,
        detect_already_normalized=True,
    ):
        """
        Async factory method that creates an instance and initializes it asynchronously
        """
        instance = cls(
            tokenizer,
            model,
            create_new_vs,
            existing_vector_store,
            new_vs_name,
            embedding_model_name,
            embedding_type,
            normalize_embeddings,
            normalization_strategy,
            log_normalization_stats,
            detect_already_normalized,
        )

        # Then update the embedding model asynchronously
        instance.embedding_model = (
            await EmbeddingModelLoader.load_embedding_model_async(
                embedding_type, embedding_model_name
            )
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
                self.last_normalization_metadata = {
                    "strategy": "raw",
                    "already_normalized": False,
                    "error": "empty_texts",
                }
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
                    cache_key = f"{self.embedding_type}_{self.embedding_model_name}"
                    EmbeddingModelLoader._dimension_cache[cache_key] = (
                        self.embedding_dimension
                    )

                    if self.normalize_embeddings:
                        if not self.create_new_vs and self.existing_vector_store:
                            existing_save_path = (
                                VECTOR_STORE_PATH / self.existing_vector_store
                            )
                            compatibility_checked, rescaled_old_embeddings = (
                                self.check_normalization_compatibility(
                                    existing_save_path
                                )
                            )

                            if rescaled_old_embeddings is not None:
                                combined_embeddings = np.vstack(
                                    [rescaled_old_embeddings, combined_embeddings]
                                )

                if self.log_normalization_stats:
                    original_embeddings = combined_embeddings.copy()

                if self.normalize_embeddings:
                    combined_embeddings, norm_metadata = (
                        self.normalize_embeddings_strategy(
                            combined_embeddings,
                            self.normalization_strategy,
                            in_place=True,
                        )
                    )

                    if self.log_normalization_stats:
                        self._log_normalization_impact(
                            original_embeddings,
                            combined_embeddings,
                            norm_metadata,
                        )
                        strategy_name = self.normalization_strategy.upper()
                        logging.info(
                            f"Applied {strategy_name} normalization for {self.embedding_type}: "
                            f"strategy={self.normalization_strategy}"
                        )
                else:
                    norm_metadata = {
                        "strategy": "raw",
                        "already_normalized": False,
                    }

                self.last_embeddings_to_save = combined_embeddings.copy()
                self.last_normalization_metadata = norm_metadata

                return combined_embeddings

            logging.warning("No embeddings were created, returning empty array")
            empty_embeddings = np.zeros((0, self.embedding_dimension))
            self.last_embeddings_to_save = empty_embeddings.copy()
            self.last_normalization_metadata = {
                "strategy": "raw",
                "already_normalized": False,
                "error": "creation_failed",
            }
            return empty_embeddings

        except Exception as e:
            logging.error(f"🚩 Error creating embeddings: {e}")
            empty_embeddings = np.zeros((0, self.embedding_dimension))
            self.last_embeddings_to_save = empty_embeddings.copy()
            self.last_normalization_metadata = {
                "strategy": "raw",
                "already_normalized": False,
                "error": "general_exception",
            }
            return empty_embeddings

    def save_index(self, texts):
        """
        Save index -- vector database
        If create_new_vs is True, create a new vector store.
        Otherwise, merge the new vectors with the existing index.

        Parameters:
                texts: input texts

        Returns
            None
        """
        try:
            if self.create_new_vs:
                save_path = (
                    VECTOR_STORE_PATH / f"{self.embedding_type}_{self.new_vs_name}"
                )
            else:
                save_path = VECTOR_STORE_PATH / self.existing_vector_store

            save_path.mkdir(parents=True, exist_ok=True)

            # -- index dimension info
            dimension_info = {
                "embedding_model_name": self.embedding_model_name,
                "embedding_dimension": self.embedding_dimension,
                "normalization_applied": self.normalize_embeddings,
                "normalization_strategy": self.normalization_strategy,
                "normalization_timestamp": str(datetime.now()),
            }
            with open(save_path / "dimension_info.pkl", "wb") as f:
                pickle.dump(dimension_info, f)

            if hasattr(self, "last_normalization_metadata"):
                self.save_normalization_metadata(
                    save_path, self.last_normalization_metadata
                )
            else:
                default_metadata = {
                    "strategy": "raw"
                    if not self.normalize_embeddings
                    else self.normalization_strategy,
                    "already_normalized": False,
                    "timestamp": str(datetime.now()),
                }
                self.save_normalization_metadata(save_path, default_metadata)

            if hasattr(self, "last_embeddings_to_save"):
                logging.info(
                    f"Found embeddings to save: shape={self.last_embeddings_to_save.shape}"
                )
                if self.create_new_vs:
                    embeddings_save_path = save_path / "embeddings"
                    index_name = self.new_vs_name
                else:
                    # --Appending to existing index
                    new_save_path = (
                        VECTOR_STORE_PATH / f"{self.embedding_type}_{self.new_vs_name}"
                    )
                    embeddings_save_path = new_save_path / "embeddings"
                    index_name = self.new_vs_name

                embeddings_save_path.mkdir(parents=True, exist_ok=True)
                norm_type = (
                    self.normalization_strategy if self.normalize_embeddings else "raw"
                )
                embedding_filename = f"{index_name}_embedding_{norm_type}.npy"
                embedding_filepath = embeddings_save_path / embedding_filename

                np.save(embedding_filepath, self.last_embeddings_to_save)
                logging.info(f"Saved embeddings to {embedding_filepath}")
            else:
                if hasattr(self, "embeddings"):
                    logging.info(
                        f"self.embeddings exists: {self.embeddings.shape if self.embeddings is not None else 'None'}"
                    )

            # -- initialize and save BM25 retriever
            try:
                bm25_retriever = BM25Retriever(texts)
                bm25_retriever.save_bm25(save_path / "bm25_retriever.pkl")
            except Exception as e:
                logging.error(f"🚩 Error saving BM25 retriever: {e}")

            try:
                from qdrant_client import QdrantClient
                from qdrant_client.models import Distance, PointStruct, VectorParams

                from configurations import Config

                qdrant_cfg = Config.get().qdrant
                client = QdrantClient(
                    host=qdrant_cfg.host,
                    port=qdrant_cfg.port,
                    api_key=qdrant_cfg.api_key or None,
                )
                # Target is always the new collection
                collection_name = f"qdrant_{self.new_vs_name}"
                embeddings = (
                    self.last_embeddings_to_save
                    if hasattr(self, "last_embeddings_to_save")
                    else self.embeddings
                )
                client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(
                        size=self.embedding_dimension,
                        distance=Distance.COSINE,
                    ),
                )
                id_offset = 0

                if not self.create_new_vs and self.existing_vector_store:
                    # Scroll all points from the old collection and copy them first
                    scroll_offset = None
                    while True:
                        results, scroll_offset = client.scroll(
                            collection_name=self.existing_vector_store,
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
                                    payload=p.payload,
                                )
                                for p in results
                            ],
                        )
                        id_offset = max(p.id for p in results) + 1
                        if scroll_offset is None:
                            break
                    logging.info(
                        f"Copied {id_offset} points from '{self.existing_vector_store}' "
                        f"to '{collection_name}'."
                    )

                new_points = [
                    PointStruct(
                        id=id_offset + i,
                        vector=embeddings[i].tolist(),
                        payload={"text": text, "metadata": {}},
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
                logging.error(f"🚩 Error with Qdrant: {e}")
                raise

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

            if not hasattr(self, "last_normalization_metadata"):
                if self.normalize_embeddings:
                    self.last_normalization_metadata = {
                        "strategy": self.normalization_strategy,
                        "already_normalized": True,
                        "timestamp": str(datetime.now()),
                    }
                else:
                    self.last_normalization_metadata = {
                        "strategy": "raw",
                        "already_normalized": False,
                        "timestamp": str(datetime.now()),
                    }

            self.save_index(texts)
        except Exception as e:
            logging.error(f"🚩 Error in create_and_save_index: {e}")

    def save_normalization_metadata(self, save_path, metadata):
        """
        Save normalization metadata for future use

        Parameters:
            save_path (Path): Path to save the metadata
            metadata (dict): Normalization metadata to save
        """
        try:
            metadata_path = save_path / "normalization_metadata.pkl"
            with open(metadata_path, "wb") as f:
                pickle.dump(metadata, f)
            logging.info(f"Saved normalization metadata to {metadata_path}")
        except Exception as e:
            logging.error(f"Error saving normalization metadata: {e}")

    def load_normalization_metadata(self, save_path):
        """
        Load normalization metadata from existing index

        Parameters:
            save_path (Path): Path to load the metadata from

        Returns:
            dict: Normalization metadata or None if not found
        """
        try:
            metadata_path = save_path / "normalization_metadata.pkl"
            if not metadata_path.exists():
                return None

            with open(metadata_path, "rb") as f:
                metadata = pickle.load(f)
            return metadata
        except Exception:
            return None

    def _rescale_embeddings(self, embeddings, metadata, strategy):
        """
        Rescale normalized embeddings back to their original scale

        Parameters:
            embeddings (np.ndarray): Normalized embeddings to rescale
            metadata (dict): Original normalization metadata
            strategy (str): Normalization strategy used

        Returns:
            np.ndarray: Rescaled embeddings
        """
        if strategy == "min_max":
            min_vals = metadata.get("min_vals", None)
            max_vals = metadata.get("max_vals", None)
            if min_vals is not None and max_vals is not None:
                min_vals = min_vals.reshape(1, -1)
                max_vals = max_vals.reshape(1, -1)
                range_vals = max_vals - min_vals
                return embeddings * range_vals + min_vals

        elif strategy == "z_score":
            mean_vals = metadata.get("mean_vals", None)
            std_vals = metadata.get("std_vals", None)
            if mean_vals is not None and std_vals is not None:
                mean_vals = mean_vals.reshape(1, -1)
                std_vals = std_vals.reshape(1, -1)
                return embeddings * std_vals + mean_vals

        elif strategy == "l2":
            return embeddings

        return embeddings

    def _load_existing_embeddings(self, save_path):
        """
        Load existing embeddings from saved embedding files

        Parameters:
            save_path (Path): Path to existing vector store

        Returns:
            np.ndarray: Loaded embeddings or None if failed
        """
        try:
            embeddings_save_path = save_path / "embeddings"
            if not embeddings_save_path.exists():
                logging.warning(f"No embeddings folder found at {embeddings_save_path}")
                return None

            embedding_files = list(embeddings_save_path.glob("*.npy"))
            if not embedding_files:
                logging.warning(f"No embedding files found in {embeddings_save_path}")
                return None

            # -- load the first embedding file found (assuming single embedding file per index)
            embedding_file = embedding_files[0]
            embeddings = np.load(embedding_file)
            logging.info(f"Loaded {len(embeddings)} embeddings from {embedding_file}")
            return embeddings

        except Exception as e:
            logging.error(f"Error loading existing embeddings: {e}")

        return None

    def check_normalization_compatibility(self, existing_save_path):
        """
        Check normalization compatibility when appending to existing index
        and rescale old embeddings if needed for mathematical consistency

        Parameters:
            existing_save_path (Path): Path to existing vector store

        Returns:
            tuple: (bool, np.ndarray) - (compatibility_checked, rescaled_old_embeddings or None)
        """
        if not existing_save_path.exists():
            return False, None

        # -- load existing normalization metadata
        existing_metadata = self.load_normalization_metadata(existing_save_path)
        if not existing_metadata:
            return False, None

        existing_strategy = existing_metadata.get("strategy", "l2")

        if existing_strategy == "l2":
            return True, None

        if existing_strategy in ["min_max", "z_score"]:
            try:
                old_embeddings = self._load_existing_embeddings(existing_save_path)
                if old_embeddings is not None:
                    rescaled_embeddings = self._rescale_embeddings(
                        old_embeddings, existing_metadata, existing_strategy
                    )
                    logging.info(
                        f"Successfully rescaled {len(old_embeddings)} old embeddings from {existing_strategy} normalization"
                    )
                    return True, rescaled_embeddings
                else:
                    logging.warning(
                        f"Could not load old embeddings for rescaling from {existing_save_path}"
                    )
                    return True, None
            except Exception as e:
                logging.error(f"Error rescaling old embeddings: {e}")
                return True, None

        return True, None
