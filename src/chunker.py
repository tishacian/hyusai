import torch
import re
import math
import nltk
import pickle
import warnings
import numpy as np
from typing import List
from nltk.tokenize import sent_tokenize

# --
nltk.download("punkt")
nltk.download("punkt_tab")
warnings.simplefilter(action="ignore", category=FutureWarning)

# -- utils for Semantic chunking
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer

# --
import logging
from rank_bm25 import BM25Okapi
from functools import wraps, lru_cache  # caching mechanism

# - KMeans dependencies
from scipy.spatial.distance import cdist
from sklearn.metrics import silhouette_score


# --
from globalvariables import (
    ChunkingMethod,
    OptimalMethod,
    RANDOM_SEED,
)


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
class TextChunker:
    def __init__(self, tokenizer, model, device=None):
        """
        Document text chunker

        Parameters
        ---------
            model_name (str), optional : The name of the mode of choice. loading is usually from HuggingFace. The default is None.
            device (str), optional : cuda or cpu device used in computation. The default is None.

        Returns
        -------
            None.

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
        self.tokenizer = tokenizer
        self.model = model
        self.device = torch.device(
            "cuda"
            if torch.cuda.is_available()
            else "cpu" if torch.backends.mps.is_available() else "cpu"
        )

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
        adjusted_estimated_chunks = math.ceil(
            estimated_chunks * adjustment_factor
        )

        return adjusted_estimated_chunks

    def apply_overlap(
        self, chunks: List[str], chunk_overlap: int
    ) -> List[str]:
        """
        Apply chunk overlap to the list of chunks.

        Parameters:
        - chunks (List[str]): The list of text chunks.

        Returns:
        - List[str]: A list of text chunks with overlap applied.
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
                            cdist(
                                random_ref, km.cluster_centers_, "euclidean"
                            ),
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

    def fixed_chunking(self, text, chunk_size=None):
        """
        Fixed chunking
        """
        self.chunk_size = (
            self.tokenizer.max_len_single_sentence
            if not chunk_size
            else max(chunk_size, self.tokenizer.max_len_single_sentence)
        )
        return [
            text[i : i + self.chunk_size]
            for i in range(0, len(text), self.chunk_size)
        ]

    def sentence_boundary_detection(self, text):
        """
        Chunk text based on sentence boundaries.


        Parameters:
            text (str): The input text to chunk.

        Returns:
            List[str]: List of sentences.
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
            raise RuntimeError(
                f"🚩 Error during sentence tokenization: {str(e)}"
            )

    def recursive_character_chunking(
        self, text, chunk_size=None, overlap=None
    ) -> List[str]:
        """
        Recursively split the text into chunks of specified size.

        Parameters:
        - text (str): The input text to be split.
        - chunk_size (int): The size of the chunks to split from larger text. Default is 200.
        - overlap (int): size of permitted overlapping chunks. Default is 50.

        Returns:
        - List[str]: A list of text chunks.
        """
        self.overlap = (
            int(self.tokenizer.model_max_length // 10.1)
            if not overlap
            else overlap
        )
        self.chunk_size = (
            self.estimate_chunk_size(
                text,
                self.overlap,
                None,
                self.tokenizer.model_max_length,
            )
            if not chunk_size
            else chunk_size
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
        self, text, method="silhouette", max_k=10
    ) -> List[str]:
        """
        Dynamic chunking
        -------------
        - text (str), input text to chunk
        - method (str), method to determine optimal number of clusters ('elbow', 'silhouette', 'gap')
        - max_k (int), maximum number of clusters to evaluate
        """
        sentences = sent_tokenize(text)
        vectorizer = TfidfVectorizer(stop_words="english")
        X = vectorizer.fit_transform(sentences)

        # Find the optimal number of clusters
        num_clusters = (
            6
            if not method
            else self.find_optimal_k(X, method=method, max_k=max_k)
        )

        # Cluster sentences using k-Means
        km = KMeans(n_clusters=num_clusters, random_state=RANDOM_SEED)
        logging.info(
            f"Using {method} method..The number of clusters is: {num_clusters}"
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
        self, text: str, max_tokens: int = 512
    ) -> List[str]:
        """
        LLM Chunking
        -------------
        text (str): Input text to chunk.
        max_tokens (int): Maximum number of tokens per chunk. Default is 512.

        Returns:
        List[str]: A list of text chunks.
        """
        inputs = self.tokenizer(
            text, return_tensors="pt", padding=False, truncation=False
        )
        tokens = inputs["input_ids"].to(self.device)
        token_count = tokens.size(1)  # Get number of tokens in the input
        logging.info(f"Token count: {token_count}")
        # --
        if token_count <= max_tokens:
            return [text]
        # --
        chunks = []
        for i in range(0, token_count, max_tokens):
            chunk_tokens = tokens[:, i : i + max_tokens]
            chunks.append(
                self.tokenizer.decode(
                    chunk_tokens[0], skip_special_tokens=True
                )
            )

        return chunks

    def hierarchical_chunking(
        self, text, paragraph_chunk_size=5, sentence_chunk_size=5
    ):
        """
        Hierarchically chunk text into paragraphs and then sentences.

        Parameters:
        - text (str): The input text to chunk.
        - paragraph_chunk_size (int): Maximum size of each paragraph chunk.
        - sentence_chunk_size (int): Maximum size of each sentence chunk.

        Returns:
        - List[str]: List of text chunks.
        """
        paragraphs = text.split("\n\n")
        chunks = []
        for paragraph in paragraphs:
            if len(paragraph) > paragraph_chunk_size:
                sentences = sent_tokenize(paragraph)
                current_chunk = ""
                for sentence in sentences:
                    if (
                        len(current_chunk) + len(sentence)
                        <= sentence_chunk_size
                    ):
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
        self, text, max_tokens=512, threshold=1e-4
    ) -> List[str]:
        """
        Use a machine learning model to determine chunk boundaries.

        Parameters:
        - text (str): The input text to chunk.
        - max_tokens (int): Maximum number of tokens per chunk.
        - threshold (float): Threshold for determining chunk boundaries from model outputs.

        Returns:
        - List[str]: List of text chunks.
        """
        tokens = self.tokenizer(
            text,
            return_tensors="pt",
            truncation=False,
            add_special_tokens=False,
        )
        input_ids = tokens["input_ids"].squeeze(0)

        chunks = []
        current_chunk = []

        for i in range(0, len(input_ids), max_tokens):
            chunk_ids = input_ids[i : i + max_tokens]
            inputs = {"input_ids": chunk_ids.unsqueeze(0)}

            with torch.no_grad():
                outputs = self.model(**inputs)
                logits = outputs.logits.squeeze(0)
                chunk_end_signal = torch.sigmoid(logits).mean().item()
                current_chunk.extend(chunk_ids.tolist())
                # -- chunking
                if chunk_end_signal > threshold:
                    chunks.append(
                        self.tokenizer.decode(
                            current_chunk, skip_special_tokens=True
                        )
                    )
                    current_chunk = []

        if current_chunk:
            chunks.append(
                self.tokenizer.decode(current_chunk, skip_special_tokens=True)
            )

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
            self.chunks = None
        if not method:
            raise ValueError(f"🚩 Unknown chunking method: {method}")

        # --
        return self.chunks
