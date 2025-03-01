import sys
import torch
import faiss
import pickle
import warnings
import logging
import numpy as np
from functools import lru_cache
from globalvariables import (
    VECTOR_STORE_PATH,
    IndexType,
)
from embeddingloader import EmbeddingModelLoader
from langchain_community.vectorstores import Chroma
from chunker import cache_chunker_embedding_chain, BM25Retriever

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
warnings.simplefilter(action="ignore", category=FutureWarning)


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
        embedding_model_name="sentence-transformers/all-mpnet-base-v2",
        embedding_type="faiss",
    ):
        """
        Creating embedding vector for different vector class

        Parameters
        ----------
            tokenizer (tokenizer model): tokenizer model)
            model (huggingface model) :  The model of choice. loading is usually from HuggingFace.
            create_new_vs (str): flag to create a new index
            existing_vector_store (str): flag to indicate existing vector store
            new_vs_name (str): New vector store name. name are separated by underscore (_). e.x This_is_a_new_vector_store_name
            embedding_model_name (embedding model), optional : name of the embedding model used for HuggingFaceInstructEmbeddings. The default is "sentence-transformers/all-mpnet-base-v2".
            embedding_type (str), optional : Type of embedding type e.g faiss or chroma or weaviate. The default is "faiss".

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
            "cuda:0"
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
        if self.embedding_type == IndexType.WEAVIATE:
            self.class_name = "Document"

    @classmethod
    async def create_async(
        cls,
        tokenizer,
        model,
        create_new_vs,
        existing_vector_store,
        new_vs_name,
        embedding_model_name="sentence-transformers/all-mpnet-base-v2",
        embedding_type="faiss",
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
        )

        # Then update the embedding model asynchronously
        instance.embedding_model = (
            await EmbeddingModelLoader.load_embedding_model_async(
                embedding_type, embedding_model_name
            )
        )
        return instance

    def create_embeddings(self, texts):
        """
        Create_embeddings.
        Creates embeddings using pre-loaded SentenceTransformer or tokenizer based on availability.

        Parameters:
            texts (str): input texts

        Returns:
            np.array: The embedding vectors
        """
        try:
            if not texts or len(texts) == 0:
                logging.error("🚩 Empty texts array received")
                return np.zeros((0, self.embedding_dimension))

            if self.embedding_type in [IndexType.FAISS, IndexType.CHROMA]:
                logging.info(
                    f"Creating embeddings on device: {self.device.type}"
                )

                batch_size = 32
                all_embeddings = []

                for i in range(0, len(texts), batch_size):
                    batch_texts = texts[i : i + batch_size]

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
                    # Verify the embedding dimension
                    if (
                        combined_embeddings.shape[1]
                        != self.embedding_dimension
                    ):
                        logging.warning(
                            f"Embedding dimension mismatch! Expected {self.embedding_dimension}, got {combined_embeddings.shape[1]}"
                        )
                        self.embedding_dimension = combined_embeddings.shape[1]
                        cache_key = f"{self.embedding_type}_{self.embedding_model_name}"
                        EmbeddingModelLoader._dimension_cache[cache_key] = (
                            self.embedding_dimension
                        )
                    return combined_embeddings
                return np.zeros((0, self.embedding_dimension))

            elif self.embedding_type == IndexType.WEAVIATE:
                # Use tokenizer-based embeddings for Weaviate
                try:
                    # -- process embedding in batches
                    batch_size = 32
                    all_embeddings = []

                    for i in range(0, len(texts), batch_size):
                        batch_texts = texts[i : i + batch_size]

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
                        # Update dimension if needed
                        if (
                            combined_embeddings.shape[1]
                            != self.embedding_dimension
                        ):
                            logging.warning(
                                f"⚠️ Embedding dimension mismatch! Expected {self.embedding_dimension}, got {combined_embeddings.shape[1]}"
                            )
                            self.embedding_dimension = (
                                combined_embeddings.shape[1]
                            )
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
            train = False if self.device.type == "cpu" else True
            embeddings_copy = embeddings.copy().astype(np.float32)
            faiss.normalize_L2(embeddings_copy)
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
                                        f"🚩 Dimension mismatch! Existing index has dimension {existing_dimension}, "
                                        f"but current embeddings have dimension {self.embedding_dimension}. "
                                        f"Cannot merge indices with different dimensions."
                                    )
                                    return
                        except FileNotFoundError:
                            logging.warning(
                                "No dimension info found for existing index. Proceeding with caution."
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
