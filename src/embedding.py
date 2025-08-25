import sys
import torch
import faiss
import pickle
import logging
import numpy as np
from datetime import datetime
from typing import Optional
from functools import lru_cache
from src.globalvariables import (
    VECTOR_STORE_PATH,
    IndexType,
    EMBEDDING_NAME,
)
from src.embeddingloader import EmbeddingModelLoader
from langchain_community.vectorstores import Chroma
from src.chunker import cache_chunker_embedding_chain, BM25Retriever

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
        embedding_type="faiss",
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
            embedding_type (str), optional: Type of embedding type e.g faiss 
                or chroma or weaviate. The default is "faiss".
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
            else "cpu" if torch.backends.mps.is_available() else "cpu"
        )
        self.embedding_model_name = embedding_model_name
        self.embedding_model = EmbeddingModelLoader.load_embedding_model(
            self.embedding_type, embedding_model_name
        )
        # --
        self.embedding_dimension = (
            EmbeddingModelLoader.get_embedding_dimension(
                self.embedding_type, embedding_model_name
            )
        )
        
        # Normalization configuration
        self.normalize_embeddings = normalize_embeddings
        self.normalization_strategy = normalization_strategy
        self.log_normalization_stats = log_normalization_stats
        self.detect_already_normalized = detect_already_normalized
        
        if self.embedding_type == IndexType.WEAVIATE:
            self.class_name = "Document"

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
                    logging.info(f"Embeddings already {strategy} normalized, skipping normalization")
                return embeddings, {"already_normalized": True, "strategy": strategy}
        
        if strategy == "l2":
            return self._normalize_l2(embeddings, in_place)
        elif strategy == "min_max":
            return self._normalize_min_max(embeddings, in_place)
        elif strategy == "z_score":
            return self._normalize_z_score(embeddings, in_place)
        else:
            logging.warning(f"Unknown normalization strategy: {strategy}. Falling back to L2.")
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
            logging.warning(f"Found {zero_count} zero vectors, setting to small epsilon = {epsilon}")
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
            "strategy": "l2"
        }
        
        # Verify normalization quality
        final_norms = np.linalg.norm(normalized_embeddings, axis=1)
        norm_std = np.std(final_norms)
        if norm_std > 1e-6:
            logging.warning(f"L2 normalization quality check failed: std={norm_std:.2e}")
            
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
            logging.warning(f"Found {constant_count} constant dimensions, setting range to 1")
            range_vals[constant_mask] = 1.0
        
        normalized_embeddings = (embeddings_copy - min_vals) / range_vals
        
        metadata = {
            "min_vals": min_vals.flatten(),
            "max_vals": max_vals.flatten(),
            "range_vals": range_vals.flatten(),
            "constant_dimensions": constant_count,
            "already_normalized": False,
            "strategy": "min_max"
        }
        
        final_min = np.min(normalized_embeddings, axis=0)
        final_max = np.max(normalized_embeddings, axis=0)
        if not (np.allclose(final_min, 0, atol=1e-6) and np.allclose(final_max, 1, atol=1e-6)):
            logging.warning("Min-max normalization quality check failed")
            
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
            logging.warning(f"Found {zero_std_count} dimensions with zero std, setting to 1")
            std_vals[zero_std_mask] = 1.0
        
        normalized_embeddings = (embeddings_copy - mean_vals) / std_vals
        
        metadata = {
            "mean_vals": mean_vals.flatten(),
            "std_vals": std_vals.flatten(),
            "zero_std_dimensions": zero_std_count,
            "already_normalized": False,
            "strategy": "z_score"
        }
        
        final_mean = np.mean(normalized_embeddings, axis=0)
        final_std = np.std(normalized_embeddings, axis=0)
        if not (np.allclose(final_mean, 0, atol=1e-6) and np.allclose(final_std, 1, atol=1e-6)):
            logging.warning("Z-score normalization quality check failed")
            
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
            return (np.allclose(min_vals, 0, atol=tolerance) and 
                   np.allclose(max_vals, 1, atol=tolerance))
        elif strategy == "z_score":
            mean_vals = np.mean(embeddings, axis=0)
            std_vals = np.std(embeddings, axis=0)
            return (np.allclose(mean_vals, 0, atol=tolerance) and 
                   np.allclose(std_vals, 1, atol=tolerance))
        else:
            norms = np.linalg.norm(embeddings, axis=1)
            return np.allclose(norms, 1.0, atol=tolerance)
    
    def _log_normalization_impact(self, original_embeddings, normalized_embeddings, metadata):
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
                indices = np.random.choice(len(original_embeddings), n_samples * 2, replace=False)
                
                original_similarities = []
                normalized_similarities = []
                
                for i in range(0, len(indices), 2):
                    if i + 1 < len(indices):
                        idx1, idx2 = indices[i], indices[i + 1]
                        orig_sim = np.dot(original_embeddings[idx1], original_embeddings[idx2]) / (
                            np.linalg.norm(original_embeddings[idx1]) * 
                            np.linalg.norm(original_embeddings[idx2])
                        )
                        original_similarities.append(orig_sim)
                        norm_sim = np.dot(normalized_embeddings[idx1], normalized_embeddings[idx2])
                        normalized_similarities.append(norm_sim)
                
                if original_similarities and normalized_similarities:
                    sim_diff = np.mean(np.abs(np.array(original_similarities) - np.array(normalized_similarities)))
                    logging.info(f"Normalization similarity preservation: avg diff={sim_diff:.6f}")
            
            # -- log normalization stats
            strategy = metadata.get('strategy', 'unknown')
            if strategy == "l2":
                logging.info(f"L2 Normalization completed: "
                            f"vectors={len(normalized_embeddings)}, "
                            f"zero_vectors={metadata.get('zero_vectors', 0)}, "
                            f"avg_original_norm={metadata.get('avg_original_norm', 0):.3f}")
            elif strategy == "min_max":
                logging.info(f"Min-Max Normalization completed: "
                            f"vectors={len(normalized_embeddings)}, "
                            f"constant_dimensions={metadata.get('constant_dimensions', 0)}")
            elif strategy == "z_score":
                logging.info(f"Z-Score Normalization completed: "
                            f"vectors={len(normalized_embeddings)}, "
                            f"zero_std_dimensions={metadata.get('zero_std_dimensions', 0)}")
            else:
                logging.info(f"{strategy.title()} Normalization completed: "
                            f"vectors={len(normalized_embeddings)}")
                        
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
            batch = embeddings[i:i + batch_size]
            normalized_batch, metadata = self.normalize_embeddings_strategy(
                batch, self.normalization_strategy, in_place=False
            )
            normalized_batches.append(normalized_batch)
            all_metadata.append(metadata)
            
            if self.log_normalization_stats:
                progress = min(100, (i + batch_size) / len(embeddings) * 100)
                logging.info(f"{self.normalization_strategy} normalization progress: {progress:.1f}%")
        
        # -- batch normalization
        combined_embeddings = np.vstack(normalized_batches)
        
        # Aggregate metadata based on strategy
        if self.normalization_strategy == "l2":
            combined_metadata = {
                "zero_vectors": sum(m.get("zero_vectors", 0) for m in all_metadata),
                "avg_original_norm": np.mean([m.get("avg_original_norm", 0) for m in all_metadata]),
                "min_original_norm": min([m.get("min_original_norm", float('inf')) for m in all_metadata]),
                "max_original_norm": max([m.get("max_original_norm", 0) for m in all_metadata]),
                "already_normalized": False,
                "batch_processed": True,
                "strategy": self.normalization_strategy
            }
        elif self.normalization_strategy == "min_max":
            combined_metadata = {
                "constant_dimensions": sum(m.get("constant_dimensions", 0) for m in all_metadata),
                "already_normalized": False,
                "batch_processed": True,
                "strategy": self.normalization_strategy
            }
        elif self.normalization_strategy == "z_score":
            combined_metadata = {
                "zero_std_dimensions": sum(m.get("zero_std_dimensions", 0) for m in all_metadata),
                "already_normalized": False,
                "batch_processed": True,
                "strategy": self.normalization_strategy
            }
        else:
            combined_metadata = {
                "already_normalized": False,
                "batch_processed": True,
                "strategy": self.normalization_strategy
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
                logging.warning("No dimension info found, cannot validate normalization")
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
                
            if existing_normalization and existing_strategy != self.normalization_strategy:
                logging.warning(
                    f"Normalization strategy mismatch: existing index uses "
                    f"{existing_strategy}, current setting={self.normalization_strategy}"
                )
                return False
                
            return True
            
        except Exception as e:
            logging.error(f"Error validating normalization consistency: {e}")
            return False

    @classmethod
    async def create_async(
        cls,
        tokenizer,
        model,
        create_new_vs,
        existing_vector_store,
        new_vs_name,
        embedding_model_name=EMBEDDING_NAME,
        embedding_type="faiss",
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

    def create_embeddings(self, texts, batch_size: Optional[int] = None):
        """
        Create_embeddings.
        Creates embeddings using pre-loaded SentenceTransformer or tokenizer based on availability.

        Parameters:
            texts (str): input texts

        Returns:
            np.array: The embedding vectors
        """
        self.batch_size = 32 if not batch_size else batch_size
        try:
            if not texts or len(texts) == 0:
                logging.error("🚩 Empty texts array received")
                return np.zeros((0, self.embedding_dimension))

            if self.embedding_type in [IndexType.FAISS, IndexType.CHROMA]:
                logging.info(
                    f"Creating embeddings on device: {self.device.type}"
                )

                all_embeddings = []

                for i in range(0, len(texts), self.batch_size):
                    batch_texts = texts[i : i + self.batch_size]

                    embeddings = self.embedding_model.encode(
                        batch_texts,
                        show_progress_bar=(
                            True if len(batch_texts) > 10 else False
                        ),
                        convert_to_tensor=True,
                        device=self.device.type,
                    )
                    batch_embeddings = (
                        embeddings.to(dtype=torch.float32).cpu().numpy()
                    )
                    all_embeddings.append(batch_embeddings)

                # Combine batches
                if all_embeddings:
                    combined_embeddings = np.vstack(all_embeddings)
                    # -- verify the embedding dimension
                    if (
                        combined_embeddings.shape[1]
                        != self.embedding_dimension
                    ):
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
                        if self.log_normalization_stats:
                            original_embeddings = combined_embeddings.copy()
                        
                        combined_embeddings, norm_metadata = self.normalize_embeddings_strategy(
                            combined_embeddings, self.normalization_strategy, in_place=True
                        )
                        
                        if self.log_normalization_stats:
                            self._log_normalization_impact(
                                original_embeddings, combined_embeddings, norm_metadata
                            )
                            strategy_name = self.normalization_strategy.upper()
                            logging.info(f"Applied {strategy_name} normalization for {self.embedding_type}: "
                                        f"strategy={self.normalization_strategy}")
                    
                    return combined_embeddings
                return np.zeros((0, self.embedding_dimension))

            elif self.embedding_type == IndexType.WEAVIATE:
                # Use tokenizer-based embeddings for Weaviate
                try:
                    # -- process embedding in batches
                    all_embeddings = []

                    for i in range(0, len(texts), self.batch_size):
                        batch_texts = texts[i : i + self.batch_size]

                        inputs = self.tokenizer(
                            batch_texts,
                            return_tensors="pt",
                            padding=True,
                            truncation=True,
                            max_length=self.tokenizer.model_max_length,
                        ).to(self.device.type)

                        if (
                            inputs["input_ids"].size(1)
                            > self.tokenizer.model_max_length
                        ):
                            logging.warning(
                                "🚩 Input text exceeds model's maximum length, truncating."
                            )

                        with torch.no_grad():
                            embeddings = self.model.transformer.wte(
                                inputs["input_ids"]
                            ).mean(dim=1)
                        batch_embeddings = (
                            embeddings.to(dtype=torch.float32).cpu().numpy()
                        )
                        all_embeddings.append(batch_embeddings)

                    # Combine batches
                    if all_embeddings:
                        combined_embeddings = np.vstack(all_embeddings)
                        if (
                            combined_embeddings.shape[1]
                            != self.embedding_dimension
                        ):
                            logging.warning(
                                f" Embedding dimension mismatch! Expected "
                                f"{self.embedding_dimension}, got "
                                f"{combined_embeddings.shape[1]}"
                            )
                            self.embedding_dimension = (
                                combined_embeddings.shape[1]
                            )
                        
                        if self.normalize_embeddings:
                            if self.log_normalization_stats:
                                original_embeddings = combined_embeddings.copy()
                            
                            combined_embeddings, norm_metadata = self.normalize_embeddings_strategy(
                                combined_embeddings, self.normalization_strategy, in_place=True
                            )
                            
                            if self.log_normalization_stats:
                                self._log_normalization_impact(
                                    original_embeddings, combined_embeddings, norm_metadata
                                )
                                strategy_name = self.normalization_strategy.upper()
                                logging.info(f"Applied {strategy_name} normalization for {self.embedding_type}: "
                                            f"strategy={self.normalization_strategy}")
                        
                        return combined_embeddings
                    return np.zeros((0, self.embedding_dimension))

                except IndexError as e:
                    logging.error(
                        f"🚩 Index out of range error: {e}. Check input text length."
                    )
                    return np.zeros((0, self.embedding_dimension))
            else:
                logging.error(
                    f"🚩 Unsupported embedding type: {self.embedding_type}"
                )
                return np.zeros((0, self.embedding_dimension))

        except Exception as e:
            logging.error(f"🚩 Error creating embeddings: {e}")
            return np.zeros((0, self.embedding_dimension))

    def create_faiss_index(self, embeddings, chunk_size=None):
        """
        Create FAISS index with dimension validation and error handling

        Parameters:
            embeddings (np.array): text embeddings
            chunk_size (int): chunk size to split texts

        Returns
            Index/Vector store
        """
        try:
            if embeddings is None or len(embeddings) == 0:
                logging.error("🚩 Empty embeddings array received")
                return None

            assert isinstance(
                embeddings, np.ndarray
            ), f"Embedding is type : {type(embeddings)} not an ndarray"

            if embeddings.shape[0] == 0 or embeddings.shape[1] == 0:
                logging.error("🚩 Embeddings array has zero dimensions")
                return None

            if np.isnan(embeddings).any() or np.isinf(embeddings).any():
                logging.error("🚩 Embeddings contain NaN or Inf values")
                return None
            # --
            dimension = embeddings.shape[1]
            logging.info(f"Creating FAISS index with dimension: {dimension}")
            if dimension != self.embedding_dimension:
                logging.warning(
                    f" Updating embedding dimension from {self.embedding_dimension} to {dimension}"
                )
                self.embedding_dimension = dimension
                cache_key = (
                    f"{self.embedding_type}_{self.embedding_model_name}"
                )
                EmbeddingModelLoader._dimension_cache[cache_key] = dimension

            # -- Indexing
            train = self.device.type != "cpu"
            embeddings_copy = embeddings.copy().astype(np.float32)
            
            # -- check embedding normalization
            if self.normalize_embeddings and not self._is_already_normalized(embeddings_copy, self.normalization_strategy):
                if self.normalization_strategy == "l2":
                    faiss.normalize_L2(embeddings_copy)
                else:
                    # -- apply custom normalization for non-L2 strategies
                    embeddings_copy, _ = self.normalize_embeddings_strategy(
                        embeddings_copy, self.normalization_strategy, in_place=True
                    )
            elif self.normalize_embeddings:
                logging.info(f"Embeddings already {self.normalization_strategy} normalized, skipping FAISS normalization")
            else:
                pass
                
            index = faiss.IndexFlatL2(dimension)
            index.add(embeddings_copy)

            # -- return index for small dataset
            if embeddings.shape[0] < 1000:
                logging.info(
                    f"Using flat index for small dataset ({embeddings.shape[0]} points)"
                )
                return index

            # otherwise, use GPUs to create IVF index
            if train and embeddings.shape[0] >= 1000:
                try:
                    nlist = min(
                        4096, max(int(np.sqrt(embeddings.shape[0])), 4)
                    )
                    if embeddings.shape[0] < 30 * nlist:
                        logging.warning(
                            f"🚩 Not enough training data for IVF. Using flat index instead. "
                            f"Need at least {30 * nlist} points, but have {embeddings.shape[0]}."
                        )
                        return index

                    logging.info(f"Creating IVF index with {nlist} centroids")
                    # -- Train IVF index
                    quantizer = faiss.IndexFlatL2(dimension)
                    ivf_index = faiss.IndexIVFFlat(
                        quantizer, dimension, nlist, faiss.METRIC_INNER_PRODUCT
                    )
                    ivf_index.train(embeddings_copy)
                    ivf_index.add(embeddings_copy)
                    ivf_index.nprobe = max(1, nlist // 10)

                    if not ivf_index.is_trained:
                        logging.error(
                            "🚩 FAISS IVF index training failed! Falling back to flat index."
                        )
                        return index

                    return ivf_index
                except Exception as e:
                    logging.error(
                        f"🚩 Error creating FAISS IVF index: {e}. Falling back to flat index."
                    )
                    return index

            return index

        except Exception as e:
            logging.error(f"🚩 Error creating FAISS index: {e}")
            return None

    def save_index(self, index, texts):
        """
        Save index -- vector database
        If create_new_vs is True, create a new vector store.
        Otherwise, merge the new vectors with the existing index.

        Parameters:
                index (Index/vector store): Index or vector store
                texts: input texts

        Returns
            None
        """
        try:
            if self.create_new_vs:
                save_path = (
                    VECTOR_STORE_PATH
                    / f"{self.embedding_type}_{self.new_vs_name}"
                )
            else:
                save_path = (
                    VECTOR_STORE_PATH
                    / f"{self.embedding_type}_{self.existing_vector_store}"
                )

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

            # -- initialize and save BM25 retriever
            try:
                bm25_retriever = BM25Retriever(texts)
                bm25_retriever.save_bm25(save_path / "bm25_retriever.pkl")
            except Exception as e:
                logging.error(f"🚩 Error saving BM25 retriever: {e}")

            if self.embedding_type == IndexType.FAISS:
                if index is None:
                    logging.error("🚩 Cannot save None FAISS index")
                    return

                if self.create_new_vs:
                    faiss.write_index(index, str(save_path / "faiss.index"))
                    with open(save_path / "faiss.pkl", "wb") as f:
                        pickle.dump(texts, f)
                    logging.info(
                        f"New FAISS index and texts saved successfully to {save_path}"
                    )
                else:
                    try:
                        # Validate normalization consistency
                        if not self.validate_normalization_consistency(save_path):
                            logging.error("🚩 Normalization consistency validation failed")
                            return
                            
                        try:
                            with open(
                                save_path / "dimension_info.pkl", "rb"
                            ) as f:
                                existing_dimension_info = pickle.load(f)
                                existing_dimension = (
                                    existing_dimension_info.get(
                                        "embedding_dimension"
                                    )
                                )

                                if (
                                    existing_dimension
                                    != self.embedding_dimension
                                ):
                                    logging.error(
                                        f"🚩 Dimension mismatch! Existing index has "
                                        f"dimension {existing_dimension}, "
                                        f"but current embeddings have dimension "
                                        f"{self.embedding_dimension}. "
                                        f"Cannot merge indices with different dimensions."
                                    )
                                    return
                        except FileNotFoundError:
                            logging.warning(
                                "No dimension info found for existing index. "
                                "Proceeding with caution."
                            )

                        existing_index = faiss.read_index(
                            str(save_path / "faiss.index")
                        )

                        # -- checking dimension mismatch
                        if (
                            hasattr(existing_index, "d")
                            and existing_index.d != self.embedding_dimension
                        ):
                            logging.error(
                                f"🚩 Dimension mismatch! Existing index has dimension {existing_index.d}, "
                                f"but current embeddings have dimension {self.embedding_dimension}. "
                                f"Cannot merge indices with different dimensions."
                            )
                            return

                        # -- merging index if possible
                        if hasattr(existing_index, "merge_from"):
                            existing_index.merge_from(index)
                        else:
                            logging.warning(
                                "🚩 Index doesn't support merge_from. Creating a new index."
                            )
                            with open(save_path / "faiss.pkl", "rb") as f:
                                existing_texts = pickle.load(f)

                            existing_embeddings = self.create_embeddings(
                                existing_texts
                            )
                            new_embeddings = self.create_embeddings(texts)
                            combined_embeddings = np.vstack(
                                [existing_embeddings, new_embeddings]
                            )
                            combined_texts = existing_texts + texts
                            combined_index = faiss.IndexFlatL2(
                                self.embedding_dimension
                            )
                            combined_embeddings_copy = (
                                combined_embeddings.copy().astype(np.float32)
                            )
                            # -- apply normalization if enabled
                            if self.normalize_embeddings:
                                combined_embeddings_copy, _ = self.normalize_embeddings_strategy(
                                    combined_embeddings_copy, self.normalization_strategy, in_place=True
                                )
                            else:
                                faiss.normalize_L2(combined_embeddings_copy)
                            combined_index.add(combined_embeddings_copy)
                            faiss.write_index(
                                combined_index, str(save_path / "faiss.index")
                            )
                            with open(save_path / "faiss.pkl", "wb") as f:
                                pickle.dump(combined_texts, f)
                            logging.info(
                                f"Created new combined FAISS index and saved to {save_path}"
                            )
                            return

                        # -- write and merge index
                        faiss.write_index(
                            existing_index, str(save_path / "faiss.index")
                        )
                        with open(save_path / "faiss.pkl", "rb") as f:
                            existing_texts = pickle.load(f)
                        existing_texts.extend(texts)
                        with open(save_path / "faiss.pkl", "wb") as f:
                            pickle.dump(existing_texts, f)
                        logging.info(
                            f"FAISS index merged and texts updated successfully at {save_path}"
                        )

                    except FileNotFoundError:
                        logging.warning(
                            f"🚩 Existing index not found at {save_path}. Creating new index."
                        )
                        faiss.write_index(
                            index, str(save_path / "faiss.index")
                        )
                        with open(save_path / "faiss.pkl", "wb") as f:
                            pickle.dump(texts, f)
                        logging.info(
                            f"New FAISS index created and saved to {save_path}"
                        )

            elif self.embedding_type == IndexType.CHROMA:
                try:
                    if self.create_new_vs:
                        vectorstore = Chroma.from_texts(
                            texts,
                            embedding=self.embedding_model,
                            persist_directory=str(save_path),
                        )
                        vectorstore.persist()
                        logging.info(
                            f"New Chroma index and texts saved successfully to {save_path}"
                        )
                    else:
                        existing_vectorstore = Chroma(
                            embedding_function=self.embedding_model,
                            persist_directory=str(save_path),
                        )
                        existing_vectorstore.add_texts(texts)
                        existing_vectorstore.persist()
                        logging.info(
                            f"Chroma index updated with new texts at {save_path}"
                        )
                except Exception as e:
                    logging.error(f"🚩 Error with Chroma vectorstore: {e}")
                    raise

            elif self.embedding_type == IndexType.WEAVIATE:
                try:
                    if self.create_new_vs:
                        for i, text in enumerate(texts):
                            self.embedding_model.batch.add_data_object(
                                {"text": text},
                                self.class_name,
                                vector=self.embeddings[i],
                            )
                        self.embedding_model.batch.flush()
                        logging.info(
                            "New Weaviate index created and texts saved successfully"
                        )
                    else:
                        for i, text in enumerate(texts):
                            self.embedding_model.batch.add_data_object(
                                {"text": text},
                                self.class_name,
                                vector=self.embeddings[i],
                            )
                        self.embedding_model.batch.flush()
                        logging.info("Weaviate index updated with new texts")
                except Exception as e:
                    logging.error(f"🚩 Error with Weaviate: {e}")
                    raise

            else:
                raise ValueError(
                    "🚩 Unsupported embedding type. Choose 'faiss', 'chroma', or 'weaviate'."
                )

        except Exception as e:
            logging.error(
                f"🚩 An error occurred while saving/merging the index: {str(e)}"
            )
            raise

    def create_and_save_index(self, texts):
        """
        Create and save the index -- vector DB with improved validation and error handling

        Parameters:
            texts (str): input texts

        Return
            None
        """
        try:
            if not texts or len(texts) == 0:
                logging.error("🚩 Empty texts array received")
                return

            self.embeddings = self.create_embeddings(texts)
            if self.embeddings is None or len(self.embeddings) == 0:
                logging.error("🚩 Failed to create embeddings")
                return

            if self.embedding_type == IndexType.FAISS:
                index = self.create_faiss_index(self.embeddings)
                if index is not None:
                    self.save_index(index, texts)
                else:
                    logging.error("🚩 Failed to create FAISS index")
            elif self.embedding_type == IndexType.CHROMA:
                self.save_index(
                    None, texts
                )  # -- Index is saved during vectorstore creation in Chroma
            elif self.embedding_type == IndexType.WEAVIATE:
                self.save_index(None, texts)
            else:
                raise ValueError(
                    "🚩 Unsupported embedding type. Choose 'faiss', 'chroma', or 'weaviate'."
                )
        except Exception as e:
            logging.error(f"🚩 Error in create_and_save_index: {e}")
