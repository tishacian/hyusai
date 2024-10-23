import sys
import torch
import faiss
import pickle
import weaviate
import numpy as np
from sentence_transformers import SentenceTransformer
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceInstructEmbeddings
from Chunker import cache_chunker_embedding_chain, BM25Retriever

# --
import warnings
import logging
from functools import lru_cache
from global_variables import (
    VECTOR_STORE_PATH,
    IndexType,
)


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
        embedding_type="chroma",
    ):
        """
        Creating embedding vector for different vector class

        Parameters
        ----------
            model_name (huggingface model) :  The name of the mode of choice. loading is usually from HuggingFace.
            embedding_model_name (embedding model), optional : name of the embedding model used for HuggingFaceInstructEmbeddings. The default is "sentence-transformers/all-mpnet-base-v2".
            index_path : (str), optional : path name to save the faiss or chroma or weaviate index. The default is "index".
            embedding_type (str), optional : Type of embedding type e.g faiss or chroma or weaviate. The default is "chroma".

        Raises
        ------
            ValueError : Returns ValueError in case of unsupported vector name.

        Returns
        ------
            None.

        """
        self.tokenizer = tokenizer
        self.model = model
        self.device = torch.device(
            "cuda:0" if torch.cuda.is_available() else "cpu"
        )
        self.embedding_type = embedding_type
        self.create_new_vs = create_new_vs
        self.existing_vector_store = existing_vector_store
        self.new_vs_name = new_vs_name
        if self.embedding_type == IndexType.FAISS:
            self.embedding_model_name = "all-MiniLM-L6-v2"
            self.embedding_model = SentenceTransformer(
                self.embedding_model_name
            )
        elif self.embedding_type == IndexType.CHROMA:
            self.embedding_model_name = (
                "sentence-transformers/all-mpnet-base-v2"
            )
            self.embedding_model = SentenceTransformer(
                self.embedding_model_name
            )
        elif self.embedding_type == IndexType.WEAVIATE:
            self.embedding_model = weaviate.Client("http://localhost:8080")
            self.class_name = "Document"
            if not self.weaviate_client.schema.contains(self.class_name):
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

    def create_embeddings(self, texts):
        """
        Create_embeddings.
        Creates embeddings using pre-loaded SentenceTransformer or tokenizer based on availability.
        """
        try:
            if torch.cuda.is_available():
                # Use pre-loaded sentence transformer model
                with torch.no_grad():
                    embeddings = self.embedding_model.encode(
                        texts,
                        convert_to_tensor=True,
                        show_progress_bar=False,
                        device=self.device,  # Ensure it uses the correct device
                    )
                    embeddings = embeddings.cpu().numpy()
            else:
                # Handle different index types
                if self.index_type == IndexType.CHROMA:
                    embeddings = np.array(
                        self.embedding_model.embed_documents(texts)
                    )
                elif self.index_type in [IndexType.FAISS, IndexType.WEAVIATE]:
                    try:
                        inputs = self.tokenizer(
                            texts,
                            return_tensors="pt",
                            padding=True,
                            max_length=self.tokenizer.model_max_length,
                        ).to(self.device)

                        # Check if input exceeds max length
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
                    except IndexError as e:
                        logging.error(
                            f"🚩 Index out of range error: {e}. Check input text length."
                        )
                        return np.array([])
                else:
                    logging.error(
                        f"🚩 Unsupported embedding type: {self.index_type}"
                    )
                    return np.array([])

            return embeddings

        except Exception as e:
            logging.error(f"🚩 Error creating embeddings: {e}")
            return np.array([])

    def create_faiss_index(self, embeddings, chunk_size=None):
        """
        Create ```FAISS``` index
        """
        train = False if self.device.type == "cpu" else True
        assert isinstance(
            embeddings, np.ndarray
        ), f"Embedding is type : {type(embeddings)} not an ndarray"
        faiss.normalize_L2(embeddings)
        dimension = embeddings.shape[1]
        quantizer_index = faiss.IndexFlatL2(dimension)
        if not train:
            quantizer_index.add(embeddings)
            return quantizer_index
        else:
            nlist = chunk_size
            index = faiss.IndexIVFFlat(
                quantizer_index, dimension, nlist, faiss.METRIC_INNER_PRODUCT
            )
            # -- Start training
            index.train(embeddings)
            index.add(embeddings)
            assert index.is_trained, "🚩 FAISS index training failed!"
            return index

    def save_index(self, index, texts):
        """
        Save index -- vector database
        If create_new_vs is True, create a new vector store.
        Otherwise, merge the new vectors with the existing index.
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
                        self.weaviate_client.batch.add_data_object(
                            {"text": text},
                            self.class_name,
                            vector=self.embeddings[i],
                        )
                    self.weaviate_client.batch.flush()
                    logging.info(
                        "New Weaviate index created and texts saved successfully"
                    )
                else:
                    # For merging, we simply add new data to the existing class
                    for i, text in enumerate(texts):
                        self.weaviate_client.batch.add_data_object(
                            {"text": text},
                            self.class_name,
                            vector=self.embeddings[i],
                        )
                    self.weaviate_client.batch.flush()
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
        Create and save the index -- vector DB
        """
        chunk_size = len(texts)
        # -- other index
        self.embeddings = self.create_embeddings(texts)
        if self.embedding_type == IndexType.FAISS:
            index = self.create_faiss_index(self.embeddings, chunk_size)
            self.save_index(index, texts)
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
