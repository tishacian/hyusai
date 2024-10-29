import sys
import torch
import faiss
import pickle
import weaviate
import warnings
import logging
import numpy as np
from functools import lru_cache
from globalvariables import (
    VECTOR_STORE_PATH,
    IndexType,
)
from sentence_transformers import SentenceTransformer
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
            model_name (huggingface model) :  The name of the mode of choice. loading is usually from HuggingFace.
            create_new_vs (str): floag to create a new index
            existing_vector_store (str): flag to indeicate existing vector store
            new_vs_name (str): New vector store name. name are seperated by underscore (_). e.x This_is_a_new_vector_store_name
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
        # initialize embedding model
        try:
            if self.embedding_type == IndexType.FAISS:
                self.embedding_model_name = "all-MiniLM-L6-v2"
                self.embedding_model = SentenceTransformer(
                    self.embedding_model_name, device=self.device.type
                )
            elif self.embedding_type == IndexType.CHROMA:
                self.embedding_model_name = (
                    "sentence-transformers/all-mpnet-base-v2"
                )
                self.embedding_model = SentenceTransformer(
                    self.embedding_model_name, device=self.device.type
                )
            elif self.embedding_type == IndexType.WEAVIATE:
                self.embedding_model = weaviate.Client("http://localhost:8080")
                self.class_name = "Document"
                if not self.embedding_model.schema.contains(self.class_name):
                    self.embedding_model.schema.create_class(
                        {
                            "class": self.class_name,
                            "vectorizer": "none",
                        }
                    )
            else:
                raise ValueError(
                    "🚩 Unsupported embedding type. Choose 'faiss', 'chroma', or 'weaviate'."
                )
        except Exception as e:
            logging.error(f"🚩 Error initializing embedding model: {e}")
            raise

    def create_embeddings(self, texts):
        """
        Create_embeddings.
        Creates embeddings using pre-loaded SentenceTransformer or tokenizer based on availability.

        Parameters:
            texts (str): input texts
        """
        try:
            if self.embedding_type in [IndexType.FAISS, IndexType.CHROMA]:
                # Using SentenceTransformer for both FAISS and Chroma
                logging.info(
                    f"Creating embeddings on device: {self.device.type}"
                )
                embeddings = self.embedding_model.encode(
                    texts,
                    show_progress_bar=False,
                    convert_to_tensor=True,
                    device=self.device.type,
                )
                embeddings = embeddings.to(dtype=torch.float32).cpu().numpy()
                return embeddings

            elif self.embedding_type == IndexType.WEAVIATE:
                # Use tokenizer-based embeddings for Weaviate
                try:
                    inputs = self.tokenizer(
                        texts,
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
                    embeddings = (
                        embeddings.to(dtype=torch.float32).cpu().numpy()
                    )
                    return embeddings
                except IndexError as e:
                    logging.error(
                        f"🚩 Index out of range error: {e}. Check input text length."
                    )
                    return np.array([])
            else:
                logging.error(
                    f"🚩 Unsupported embedding type: {self.embedding_type}"
                )
                return np.array([])

        except Exception as e:
            logging.error(f"🚩 Error creating embeddings: {e}")
            return np.array([])

    def create_faiss_index(self, embeddings, chunk_size=None):
        """
        Create FAISS index with validation checks

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

            # Ensure device is correctly set
            train = False if self.device.type == "cpu" else True
            dimension = embeddings.shape[1]

            # Normalize embeddings
            embeddings_normalized = embeddings.copy()
            faiss.normalize_L2(embeddings_normalized)

            quantizer_index = faiss.IndexFlatL2(dimension)
            if not train:
                quantizer_index.add(embeddings_normalized)
                return quantizer_index
            else:
                # Check chunk_size validity
                if chunk_size is None or chunk_size <= 0:
                    nlist = min(
                        4096, max(embeddings.shape[0] // 4, 1)
                    )  # reasonable default
                    logging.warning(f"🚩 Using default nlist value: {nlist}")
                else:
                    nlist = chunk_size

                index = faiss.IndexIVFFlat(
                    quantizer_index,
                    dimension,
                    nlist,
                    faiss.METRIC_INNER_PRODUCT,
                )
                index.train(embeddings_normalized)
                index.add(embeddings_normalized)
                if not index.is_trained:
                    logging.error("🚩 FAISS index training failed!")
                    return None
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
            # -- initialize and save BM25 retriever
            bm25_retriever = BM25Retriever(texts)
            bm25_retriever.save_bm25(save_path / "bm25_retriever.pkl")

            if self.embedding_type == IndexType.FAISS:
                if self.create_new_vs:
                    faiss.write_index(index, str(save_path / "faiss.index"))
                    with open(save_path / "faiss.pkl", "wb") as f:
                        pickle.dump(texts, f)
                    logging.info(
                        f"New FAISS index and texts saved successfully to {save_path}"
                    )
                else:
                    existing_index = faiss.read_index(
                        str(save_path / "faiss.index")
                    )
                    existing_index.merge_from(index)
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

            elif self.embedding_type == IndexType.CHROMA:
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

            elif self.embedding_type == IndexType.WEAVIATE:
                if self.create_new_vs:
                    # Assuming self.weaviate_client is already configured for the new class
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
                    # For merging, we simply add new data to the existing class
                    for i, text in enumerate(texts):
                        self.embedding_model.batch.add_data_object(
                            {"text": text},
                            self.class_name,
                            vector=self.embeddings[i],
                        )
                    self.embedding_model.batch.flush()
                    logging.info("Weaviate index updated with new texts")

            else:
                raise ValueError(
                    "🚩 Unsupported embedding type. Choose 'faiss', 'chroma', or 'weaviate'."
                )

        except Exception as e:
            logging.error(
                f"An error occurred while saving/merging the index: {str(e)}"
            )
            raise

    def create_and_save_index(self, texts):
        """
        Create and save the index -- vector DB with validation

        Parameters:
            texts (str): input texts

        Return
            None
        """
        try:
            if not texts or len(texts) == 0:
                logging.error("🚩 Empty texts array received")
                return

            chunk_size = len(texts)
            self.embeddings = self.create_embeddings(texts)

            # Validate embeddings before proceeding
            if self.embeddings is None or len(self.embeddings) == 0:
                logging.error("🚩 Failed to create embeddings")
                return

            if self.embedding_type == IndexType.FAISS:
                index = self.create_faiss_index(self.embeddings, chunk_size)
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
