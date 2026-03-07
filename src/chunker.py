import logging
import math
import pickle
import re
import warnings
from functools import lru_cache, wraps
from typing import Literal

import numpy as np
import torch
from nltk.tokenize import sent_tokenize
from rank_bm25 import BM25Okapi
from scipy.spatial.distance import cdist
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    PreTrainedTokenizer,
)

from connections.storage import fs
from src.globalvariables import (
    DEFAULT_CPU_TOKENIZER,
    RANDOM_SEED,
    ChunkingMethod,
    OptimalMethod,
)

warnings.simplefilter(action="ignore", category=FutureWarning)


def cache_chunker_embedding_chain(func):
    """
    Decorator to cache the model and tokenizer.
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
        with fs.open(filepath, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load_bm25(filepath):
        """
        Load BM25 retriever from a file.
        """
        with fs.open(filepath, "rb") as f:
            return pickle.load(f)


@lru_cache(maxsize=None)
@cache_chunker_embedding_chain
class TextChunker:
    def __init__(self):
        """
        Document text chunker

        Example of LLM chunking
        -----------------------
        >> chunker = TextChunker(model_name="MBZUAI/LaMini-GPT-774M")
        >> chunks = chunker.chunker(" ".join(texts), method="llm", max_tokens=20)

        Time complexity (in order of performance):
        -----------------------------------------
        The performance of the chunkers is tested for small example text and
        the results is order accordingly. **Recursive Character Splitter** result is without k-optimization.

        [1] Fixed Chunking              ----> 532 ns ± 2.83 ns                   --> Big O: O(N) Space: O(1)
        [2] Recursive Character Splitter ---> 9.42 μs ± 77.7 ns                  --> Big O: O(Nlog N)
        [3] LLM based chunking          ----> 96.9 μs ± 214 ns                   --> Big O: O(N * k) if BPE/WordPiece or O(N log N) if SentencePiece
        [4] Semantic Chunking           ----> 1.4 ms ± 47.7 μs                   --> Big O: O(N * k * i * d)

        The best performing without taking time into consideration
        ----------------------------------------------------------
        [1] Semantic chunking (unstable with changing cluster labels)
        [2] Recursive Character Splitter (depending on chunk size and overlap)
        [3] LLM based chunking (best depending on LLM)
        [4] Fixed chunking

        Note: that for Hybrid search, Semantic chunking is sufficient.

        """
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    def _load_tokenizer_model(self, model_name: str):
        try:
            tokenizer = AutoTokenizer.from_pretrained(model_name)
        except ValueError:
            logging.warning(
                f"Could not load tokenizer for model {model_name}. Using default tokenizer."
            )
            tokenizer = AutoTokenizer.from_pretrained(DEFAULT_CPU_TOKENIZER)
        return tokenizer

    def estimate_chunk_size(
        self, text, overlap, chunk_size=None, tokenizer_model_max_length=512
    ):
        if chunk_size is None:
            chunk_size = tokenizer_model_max_length // 2

        text_length = len(text)
        if chunk_size >= text_length:
            return 1

        effective_chunk_size = chunk_size - overlap
        estimated_chunks = math.ceil(text_length / effective_chunk_size)

        adjustment_factor = 1.1
        adjusted_estimated_chunks = math.ceil(estimated_chunks * adjustment_factor)

        return adjusted_estimated_chunks

    def apply_overlap(self, chunks: list[str], chunk_overlap: int) -> list[str]:
        """
        Apply chunk overlap to the list of chunks.

        Parameters:
        - chunks (list[str]): The list of text chunks.

        Returns:
        - list[str]: A list of text chunks with overlap applied.
        """
        overlapped_chunks = []
        for i in range(len(chunks)):
            start = max(0, i - 1)
            if start == i:
                overlapped_chunks.append(chunks[i])
            else:
                overlap = chunks[start][-chunk_overlap:] + " " + chunks[i]
                overlapped_chunks.append(overlap.strip())

        return overlapped_chunks

    def optimal_k_elbow(self, X, max_k=10):
        """Elbow method for finding optimal k

        Parameters
        - X (vectors) : embedding.
        - max_k (int), optional : maximum cluster value (k). The default is 10.

        Returns
        - elbow_k (float) : k-elbow value
        """
        distortions = []
        K = range(1, max_k + 1)
        for k in K:
            km = KMeans(n_clusters=k, random_state=RANDOM_SEED)
            km.fit(X)
            distortions.append(
                sum(
                    np.min(
                        cdist(X.toarray(), km.cluster_centers_, "euclidean"),
                        axis=1,
                    )
                )
                / X.shape[0]
            )

        # -- Elbow point is where the decrease in distortion slows down
        elbow_k = (
            np.diff(distortions, 2).argmin() + 2
        )  # +2 due to diff reducing the length
        return elbow_k

    def optimal_k_silhouette(self, X, max_k=10):
        """silhouette method for finding optimal k

        Parameters
        - X (vectors) : embedding.
        - max_k (int), optional : maximum cluster value (k). The default is 10.

        Returns
        - silhouette (float) : k-silhouette value
        """
        sil_scores = []
        K = range(2, max_k + 1)
        for k in K:
            km = KMeans(n_clusters=k, random_state=RANDOM_SEED)
            labels = km.fit_predict(X)
            sil_scores.append(silhouette_score(X, labels))

        best_k = K[np.argmax(sil_scores)]
        return best_k

    def optimal_k_gap(self, X, max_k=10, n_refs=10):
        """Gap method for finding optimal k

        Parameters
        - X (vectors) : embedding.
        - max_k (int), optional : maximum cluster value (k). The default is 10.

        Returns
        - silhouette (float) : k-silhouette value
        """
        gaps = []
        ref_disps = []
        K = range(1, max_k + 1)
        for k in K:
            km = KMeans(n_clusters=k, random_state=RANDOM_SEED)
            km.fit(X)
            disp = np.log(
                sum(
                    np.min(
                        cdist(X.toarray(), km.cluster_centers_, "euclidean"),
                        axis=1,
                    )
                )
            )

            ref_disps_k = []
            for i in range(n_refs):
                random_ref = np.random.random_sample(size=X.shape)
                km.fit(random_ref)
                ref_disp = np.log(
                    sum(
                        np.min(
                            cdist(random_ref, km.cluster_centers_, "euclidean"),
                            axis=1,
                        )
                    )
                )
                ref_disps_k.append(ref_disp)
            # -- compute  mean euclid
            gap = np.mean(ref_disps_k) - disp
            gaps.append(gap)
            ref_disps.append(np.mean(ref_disps_k))

        best_k = K[np.argmax(gaps)]
        return best_k

    def find_optimal_k(self, X, method="elbow", max_k=10):
        """
        Finding the optimal (k) given a set of vectors
        ----------
        - X (nd.array) : input vector
        - method (str), optional : choice of compputing optimal k. The default is "elbow".
        - max_k (int), optional : maximum extent to search k. The default is 10.

        Raises
        - ValueError.

        Returns
        - (int) : optimal k.

        """
        if method == OptimalMethod.ELBOW:
            optimal_k = self.optimal_k_elbow(X, max_k)
        elif method == OptimalMethod.SILHOUETTE:
            optimal_k = self.optimal_k_silhouette(X, max_k)
        elif method == OptimalMethod.GAP:
            optimal_k = self.optimal_k_gap(X, max_k)
        else:
            optimal_k = None

        if not method:
            raise ValueError(
                f"🚩 method cannot be : {method}. Select from the list : ['elbow', 'silhouette', 'gap']"
            )
        return optimal_k

    def fixed_chunking(
        self, text: str, generation_model_name: str, max_chunk_length: int | None = None
    ) -> list[str]:
        """
        Fixed chunking
        """
        tokenizer: PreTrainedTokenizer = self._load_tokenizer_model(
            generation_model_name
        )
        # TODO: use model config to get max length without loading tokenizer
        model_max_chunk_length = tokenizer.max_len_single_sentence
        self.chunk_size = (
            model_max_chunk_length
            if not max_chunk_length
            else max(max_chunk_length, model_max_chunk_length)
        )
        return [
            text[i : i + self.chunk_size] for i in range(0, len(text), self.chunk_size)
        ]

    def sentence_boundary_detection(self, text: str) -> list[str]:
        """
        Chunk text based on sentence boundaries.


        Parameters:
            text (str): The input text to chunk.

        Returns:
            list[str]: list of sentences.
        """
        try:
            if not text or not text.strip():
                return []

            chunks = sent_tokenize(text)
            return chunks

        except LookupError:
            raise RuntimeError(
                "🚩 NLTK punkt tokenizer not found. Please install it using:\n"
                ">>> import nltk\n"
                ">>> nltk.download('punkt')"
            )
        except Exception as e:
            raise RuntimeError(f"🚩 Error during sentence tokenization: {str(e)}")

    def recursive_character_chunking(
        self,
        text: str,
        generation_model_name: str,
        max_chunk_length: int | None = None,
        overlap_size: int | None = None,
    ) -> list[str]:
        """
        Recursively split the text into chunks of specified size.

        Parameters:
        - text (str): The input text to be split.
        - generation_model_name (str): The name of the model that will be used to determine the maximum chunk length.
        - max_chunk_length (int): The size of the chunks to split from larger text. Default is 200.
        - overlap_size (int): size of permitted overlapping chunks.

        Returns:
        - list[str]: A list of text chunks.
        """
        tokenizer: PreTrainedTokenizer = self._load_tokenizer_model(
            generation_model_name
        )
        # TODO: use model config to get max length without loading tokenizer
        model_max_chunk_length = tokenizer.max_len_single_sentence
        self.overlap = (
            int(model_max_chunk_length // 10.1) if not overlap_size else overlap_size
        )
        self.chunk_size = (
            self.estimate_chunk_size(
                text,
                self.overlap,
                None,
                model_max_chunk_length,
            )
            if not max_chunk_length
            else max_chunk_length
        )

        if len(text) <= self.chunk_size:
            return [text]

        # -- sentence splitting
        sentences = re.split(r"(?<=[.!?]) +", text)
        chunks = []
        current_chunk = ""
        # --
        for sentence in sentences:
            if len(current_chunk) + len(sentence) + 1 <= self.chunk_size:
                current_chunk += sentence + " "
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = sentence + " "

        if current_chunk:
            chunks.append(current_chunk.strip())

        # -- handling chunk overlap
        if self.overlap > 0:
            chunks = self.apply_overlap(chunks, self.overlap)

        return chunks

    def semantic_chunking(
        self,
        text: str,
        cluster_selection_method: Literal["elbow", "silhouette", "gap"] = "silhouette",
        max_k: int = 10,
    ) -> list[str]:
        """
        Dynamic chunking
        -------------
        - text (str), input text to chunk
        - cluster_selection_method (str), method to determine optimal number of clusters ('elbow', 'silhouette', 'gap')
        - max_k (int), maximum number of clusters to evaluate
        """
        sentences = sent_tokenize(text)
        vectorizer = TfidfVectorizer(stop_words="english")
        X = vectorizer.fit_transform(sentences)

        # Find the optimal number of clusters
        num_clusters = (
            6
            if not cluster_selection_method
            else self.find_optimal_k(X, method=cluster_selection_method, max_k=max_k)
        )

        # Cluster sentences using k-Means
        km = KMeans(n_clusters=num_clusters, random_state=RANDOM_SEED)
        logging.info(
            f"Using {cluster_selection_method} method..The number of clusters is: {num_clusters}"
        )
        km.fit(X)
        clusters = km.labels_.tolist()

        # Extract clustered chunks
        clustered_sentences = [[] for _ in range(num_clusters)]
        for i, label in enumerate(clusters):
            clustered_sentences[label].append(sentences[i])

        chunks = [" ".join(cluster) for cluster in clustered_sentences]
        return chunks

    def token_based_chunking(
        self, text: str, generation_model_name: str, max_tokens_per_chunk: int = 512
    ) -> list[str]:
        """
        LLM Chunking
        -------------
        text (str): Input text to chunk.
        generation_model_name (str): The name of the model that will be used to determine the tokenizer model.
        max_tokens_per_chunk (int): Maximum number of tokens per chunk. Default is 512.

        Returns:
        list[str]: A list of text chunks.
        """
        tokenizer: PreTrainedTokenizer = self._load_tokenizer_model(
            generation_model_name
        )
        inputs = tokenizer(text, return_tensors="pt", padding=False, truncation=False)
        tokens = inputs["input_ids"].to(self.device)
        token_count = tokens.size(1)  # Get number of tokens in the input
        logging.info(f"Token count: {token_count}")
        # --
        if token_count <= max_tokens_per_chunk:
            return [text]
        # --
        chunks = []
        for i in range(0, token_count, max_tokens_per_chunk):
            chunk_tokens = tokens[:, i : i + max_tokens_per_chunk]
            chunks.append(tokenizer.decode(chunk_tokens[0], skip_special_tokens=True))

        return chunks

    def hierarchical_chunking(
        self, text: str, max_paragraph_length: int = 5, max_sentence_length: int = 5
    ) -> list[str]:
        """
        Hierarchically chunk text into paragraphs and then sentences.

        Parameters:
        - text (str): The input text to chunk.
        - max_paragraph_length (int): Maximum size of each paragraph chunk.
        - max_sentence_length (int): Maximum size of each sentence chunk.

        Returns:
        - list[str]: list of text chunks.
        """
        paragraphs = text.split("\n\n")
        chunks = []
        for paragraph in paragraphs:
            if len(paragraph) > max_paragraph_length:
                sentences = sent_tokenize(paragraph)
                current_chunk = ""
                for sentence in sentences:
                    if len(current_chunk) + len(sentence) <= max_sentence_length:
                        current_chunk += sentence + " "
                    else:
                        chunks.append(current_chunk.strip())
                        current_chunk = sentence + " "
                if current_chunk:
                    chunks.append(current_chunk.strip())
            else:
                chunks.append(paragraph.strip())

        return chunks

    def model_based_chunking(
        self,
        text: str,
        generation_model_name: str,
        max_tokens_per_chunk: int = 512,
        boundary_detection_model_name: str = "huggingface/smol-lm-135m",
        boundary_confidence_threshold: float = 1e-4,
    ) -> list[str]:
        """
        Use a machine learning model to determine chunk boundaries.

        Parameters:
        - text (str): The input text to chunk.
        - generation_model_name (str): The name of the model that will be used to determine the tokenizer model.
        - max_tokens_per_chunk (int): Maximum number of tokens per chunk.
        - boundary_detection_model_name (str): The model to use for boundary detection.
        - boundary_confidence_threshold (float): Threshold for determining chunk boundaries from model outputs.

        Returns:
        - list[str]: list of text chunks.
        """
        tokenizer: PreTrainedTokenizer = self._load_tokenizer_model(
            generation_model_name
        )
        boundary_detection_model: AutoModelForCausalLM = (
            AutoModelForCausalLM.from_pretrained(boundary_detection_model_name)
        )
        tokens = tokenizer(
            text, return_tensors="pt", truncation=False, add_special_tokens=False
        )
        input_ids = tokens["input_ids"].squeeze(0)

        chunks = []
        current_chunk = []

        for i in range(0, len(input_ids), max_tokens_per_chunk):
            chunk_ids = input_ids[i : i + max_tokens_per_chunk]
            inputs = {"input_ids": chunk_ids.unsqueeze(0)}

            with torch.no_grad():
                outputs = boundary_detection_model(**inputs)
                logits = outputs.logits.squeeze(0)
                chunk_end_signal = torch.sigmoid(logits).mean().item()
                current_chunk.extend(chunk_ids.tolist())
                # -- chunking
                if chunk_end_signal > boundary_confidence_threshold:
                    chunks.append(
                        tokenizer.decode(current_chunk, skip_special_tokens=True)
                    )
                    current_chunk = []

        if current_chunk:
            chunks.append(tokenizer.decode(current_chunk, skip_special_tokens=True))

        return chunks

    def chunker(self, text, method="recursive_character", **kwargs):
        """
        Chunking call. Default is using ```recursive character splitting```
        """
        if method == ChunkingMethod.FIXED:
            self.chunks = self.fixed_chunking(text, **kwargs)
        elif method == ChunkingMethod.RECURSIVE_CHARACTER:
            self.chunks = self.recursive_character_chunking(text, **kwargs)
        elif method == ChunkingMethod.SEMANTIC:
            self.chunks = self.semantic_chunking(text, **kwargs)
        elif method == ChunkingMethod.TOKEN_BASED:
            self.chunks = self.token_based_chunking(text, **kwargs)
        elif method == ChunkingMethod.HIERARCHICAL:
            self.chunks = self.hierarchical_chunking(text, **kwargs)
        elif method == ChunkingMethod.MODEL_BASED:
            self.chunks = self.model_based_chunking(text, **kwargs)
        elif method == ChunkingMethod.SENTENCE_BOUNDARY:
            self.chunks = self.sentence_boundary_detection(text, **kwargs)
        else:
            raise ValueError(f"🚩 Unknown chunking method: {method}")
        return self.chunks
