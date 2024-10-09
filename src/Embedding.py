import sys
import torch
import faiss
import pickle
import weaviate
import numpy as np
from sentence_transformers import SentenceTransformer
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceInstructEmbeddings

# --
import warnings

warnings.simplefilter(action="ignore", category=FutureWarning)

# --
import logging
from functools import wraps, lru_cache  # caching mechanism

# --
from rank_bm25 import BM25Okapi

# --
from global_variables import (
    VECTOR_STORE_PATH,
    IndexType,
)

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def cache_chunker_embedding_chain(func):
    """
    Decorator to cache the model and tokenizer loading.
    """

    @wraps(func)
    def wrapper(tokenizer, model, *args, **kwargs):
        try:
            # -- Check if the model and tokenizer are already cached
            return func(tokenizer, model, *args, **kwargs)
        except Exception as e:
            logging.error(f"🚩 Error loading model and tokenizer: {e}")
            return None, None

    return wrapper


class BM25Retriever:
    def __init__(self, documents):
        """
        Initialize BM25 retriever with a list of documents.
        """
        self.documents = documents
        self.bm25 = self.create_bm25_index()

    def create_bm25_index(self):
        """
        Create and return a BM25 index using the provided documents.
        """
        tokenized_docs = [doc.split() for doc in self.documents]
        return BM25Okapi(tokenized_docs)

    def get_scores(self, query):
        """
        Get BM25 scores for a query.
        """
        tokenized_query = query.split()
        return self.bm25.get_scores(tokenized_query)

    def save_bm25(self, filepath):
        """
        Save BM25 retriever to a file.
        """
        with open(filepath, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load_bm25(filepath):
        """
        Load BM25 retriever from a file.
        """
        with open(filepath, "rb") as f:
            return pickle.load(f)


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
        - model_name (huggingface model) :  The name of the mode of choice. loading is usually from HuggingFace.
        - embedding_model_name (embedding model), optional : name of the embedding model used for HuggingFaceInstructEmbeddings. The default is "sentence-transformers/all-mpnet-base-v2".
        - index_path : (str), optional : path name to save the faiss or chroma or weaviate index. The default is "index".
        - embedding_type (str), optional : Type of embedding type e.g faiss or chroma or weaviate. The default is "chroma".

        Raises
        ------
        - ValueError : Returns ValueError in case of unsupported vector name.

        Returns
        ------
        - None.

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
        if self.embedding_type == IndexType.CHROMA:
            self.embedding_model = HuggingFaceInstructEmbeddings(
                model_name=embedding_model_name
            )
        elif self.embedding_type == IndexType.FAISS:
            pass
        elif self.embedding_type == IndexType.WEAVIATE:
            self.weaviate_client = weaviate.Client("http://localhost:8080")
            self.class_name = "Document"
            if not self.weaviate_client.schema.contains(self.class_name):
                self.weaviate_client.schema.create_class(
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
        Create embedding using tokenizer class or vLLM if available
        """
        if torch.cuda.is_available():
            try:
                sentence_model = SentenceTransformer("all-MiniLM-L6-v2").to(
                    self.device
                )
                with torch.no_grad():
                    self.embeddings = sentence_model.encode(
                        texts, convert_to_tensor=True, show_progress_bar=False
                    )
                    self.embeddings = self.embeddings.cpu().numpy()
            except Exception as e:
                logging.error(
                    f"🚩 Error creating embeddings with sentence transformers: {e}"
                )
                return np.array([])
        else:
            if self.embedding_type == "chroma":
                self.embeddings = np.array(
                    self.embedding_model.embed_documents(texts)
                )
            elif self.embedding_type in [IndexType.FAISS, IndexType.WEAVIATE]:
                try:
                    inputs = self.tokenizer(
                        texts,
                        return_tensors="pt",
                        padding=True,
                        truncation=True,
                    ).to(self.device)
                    with torch.no_grad():
                        self.embeddings = self.model.transformer.wte(
                            inputs["input_ids"]
                        ).mean(dim=1)
                    self.embeddings = (
                        self.embeddings.to(dtype=torch.float32).cpu().numpy()
                    )
                except Exception as e:
                    logging.error(f"🚩 Error creating embeddings: {e}")
                    return np.array([])
            else:
                logging.error(
                    f"🚩 Unsupported embedding type: {self.embedding_type}"
                )
                return np.array([])

        return self.embeddings

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
