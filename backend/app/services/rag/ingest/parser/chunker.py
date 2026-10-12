"""Document chunking service based on streaming-decision-process"""
import re
import math
from enum import StrEnum
from typing import List, Optional
from app.core.logging import get_logger

logger = get_logger(__name__)


class ChunkingMethod(StrEnum):
    """Chunking method types"""
    FIXED = "fixed"
    RECURSIVE_CHARACTER = "recursive_character"
    SEMANTIC = "semantic"
    TOKEN_BASED = "token_based"
    HIERARCHICAL = "hierarchical"
    MODEL_BASED = "model_based"
    SENTENCE_BOUNDARY = "sentence_boundary"
    SENTENCE = "sentence"
    MARKDOWN = "markdown"


RANDOM_SEED = 42
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_ATX_HEADER_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t#]*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def _split_sentences(text: str) -> List[str]:
    try:
        from nltk.tokenize import sent_tokenize

        sentences = sent_tokenize(text)
    except Exception:  # noqa: BLE001 - punkt_tab may be absent from the image
        sentences = _SENTENCE_RE.split(text)
    return [s.strip() for s in sentences if s and s.strip()]


class DocumentChunker:
    """Document chunker with multiple strategies"""
    
    def __init__(self, default_chunk_size: int = 1000, default_overlap: int = 200):
        """
        Initialize document chunker
        
        Args:
            default_chunk_size: Default chunk size in characters
            default_overlap: Default overlap size in characters
        """
        self.default_chunk_size = default_chunk_size
        self.default_overlap = default_overlap
    
    def estimate_chunk_size(
        self, text: str, overlap: int, chunk_size: Optional[int] = None, max_length: int = 512
    ) -> int:
        """Estimate optimal chunk size"""
        if chunk_size is not None:
            return chunk_size
        
        text_length = len(text)
        if chunk_size and chunk_size >= text_length:
            return 1
        
        effective_chunk_size = (chunk_size or max_length) - overlap
        estimated_chunks = math.ceil(text_length / effective_chunk_size) if effective_chunk_size > 0 else 1
        
        adjustment_factor = 1.1
        adjusted_estimated_chunks = math.ceil(estimated_chunks * adjustment_factor)
        
        return adjusted_estimated_chunks
    
    def apply_overlap(self, chunks: List[str], chunk_overlap: int) -> List[str]:
        """
        Apply chunk overlap to the list of chunks.
        
        Args:
            chunks: List of text chunks
            chunk_overlap: Size of overlap in characters
        
        Returns:
            List of chunks with overlap applied
        """
        if chunk_overlap <= 0 or len(chunks) <= 1:
            return chunks
        
        overlapped_chunks = []
        for i in range(len(chunks)):
            start = max(0, i - 1)
            if start == i:
                overlapped_chunks.append(chunks[i])
            else:
                # Take last chunk_overlap characters from previous chunk
                prev_chunk = chunks[start]
                overlap_text = prev_chunk[-chunk_overlap:] if len(prev_chunk) > chunk_overlap else prev_chunk
                overlapped_chunks.append(overlap_text + " " + chunks[i])
        
        return overlapped_chunks
    
    def recursive_character_chunking(
        self, text: str, chunk_size: Optional[int] = None, overlap: Optional[int] = None
    ) -> List[str]:
        """
        Recursively split the text into chunks of specified size.
        This is the default chunking method (same as streaming-decision-process).
        
        Args:
            text: Input text to be split
            chunk_size: Size of chunks in characters. Default uses self.default_chunk_size
            overlap: Size of overlap in characters. Default uses self.default_overlap
        
        Returns:
            List of text chunks
        """
        self.overlap = overlap if overlap is not None else self.default_overlap
        self.chunk_size = chunk_size if chunk_size is not None else self.default_chunk_size
        
        if len(text) <= self.chunk_size:
            return [text]
        
        # Sentence splitting - preserve sentence boundaries
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks = []
        current_chunk = ""
        
        for sentence in sentences:
            if len(current_chunk) + len(sentence) + 1 <= self.chunk_size:
                current_chunk += sentence + " "
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = sentence + " "
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        # Apply overlap if specified
        if self.overlap > 0:
            chunks = self.apply_overlap(chunks, self.overlap)
        
        return chunks
    
    def fixed_chunking(self, text: str, chunk_size: Optional[int] = None) -> List[str]:
        """
        Fixed-size chunking without overlap
        
        Args:
            text: Input text
            chunk_size: Size of chunks. Default uses self.default_chunk_size
        
        Returns:
            List of chunks
        """
        chunk_size = chunk_size or self.default_chunk_size
        return [
            text[i : i + chunk_size]
            for i in range(0, len(text), chunk_size)
        ]
    
    def sentence_boundary_chunking(self, text: str) -> List[str]:
        """
        Chunk text based on sentence boundaries.
        
        Args:
            text: Input text
        
        Returns:
            List of sentences
        """
        try:
            from nltk.tokenize import sent_tokenize
            if not text or not text.strip():
                return []
            chunks = sent_tokenize(text)
            return chunks
        except ImportError:
            logger.warning("NLTK not available, falling back to simple sentence splitting")
            # Fallback to simple regex-based sentence splitting
            sentences = re.split(r'(?<=[.!?])\s+', text)
            return [s.strip() for s in sentences if s.strip()]
        except Exception as e:
            logger.error(f"Error during sentence tokenization: {e}")
            # Fallback to simple splitting
            sentences = re.split(r'(?<=[.!?])\s+', text)
            return [s.strip() for s in sentences if s.strip()]
    
    def hierarchical_chunking(
        self, text: str, paragraph_chunk_size: int = 5, sentence_chunk_size: int = 5
    ) -> List[str]:
        """
        Hierarchically chunk text into paragraphs and then sentences.
        
        Args:
            text: Input text
            paragraph_chunk_size: Maximum size of each paragraph chunk
            sentence_chunk_size: Maximum size of each sentence chunk
        
        Returns:
            List of text chunks
        """
        paragraphs = text.split("\n\n")
        chunks = []
        
        for paragraph in paragraphs:
            if len(paragraph) > paragraph_chunk_size:
                sentences = self.sentence_boundary_chunking(paragraph)
                current_chunk = ""
                for sentence in sentences:
                    if len(current_chunk) + len(sentence) <= sentence_chunk_size:
                        current_chunk += sentence + " "
                    else:
                        chunks.append(current_chunk.strip())
                        current_chunk = sentence + " "
                if current_chunk:
                    chunks.append(current_chunk.strip())
            else:
                chunks.append(paragraph.strip())
        
        return chunks
    
    def _pack_sentences(self, sentences: List[str], chunk_size: int, overlap: int) -> List[str]:
        chunks: List[str] = []
        current: List[str] = []
        length = 0
        for sentence in sentences:
            if len(sentence) > chunk_size:
                if current:
                    chunks.append(" ".join(current))
                    current, length = [], 0
                chunks.extend(self.fixed_chunking(sentence, chunk_size=chunk_size))
                continue
            if current and length + 1 + len(sentence) > chunk_size:
                chunks.append(" ".join(current))
                carried: List[str] = []
                carried_len = 0
                for previous in reversed(current):
                    if carried_len + len(previous) + 1 > overlap:
                        break
                    carried.insert(0, previous)
                    carried_len += len(previous) + 1
                if carried and carried_len + len(sentence) > chunk_size:
                    carried, carried_len = [], 0
                current, length = carried, max(carried_len - 1, 0)
            length += len(sentence) + (1 if current else 0)
            current.append(sentence)
        if current:
            chunks.append(" ".join(current))
        return chunks

    def sentence_chunking(
        self, text: str, chunk_size: Optional[int] = None, overlap: Optional[int] = None
    ) -> List[str]:
        """Pack whole sentences up to ``chunk_size``; overlap repeats trailing whole sentences."""
        chunk_size = chunk_size or self.default_chunk_size
        overlap = self.default_overlap if overlap is None else overlap
        overlap = min(max(overlap, 0), chunk_size // 2)
        if not text or not text.strip():
            return []
        return self._pack_sentences(_split_sentences(text), chunk_size, overlap)

    def markdown_chunking(
        self, text: str, chunk_size: Optional[int] = None, overlap: Optional[int] = None
    ) -> List[str]:
        """Split on ATX headers; each chunk is prefixed by its heading path."""
        chunk_size = chunk_size or self.default_chunk_size
        if not text or not text.strip():
            return []
        sections: List[tuple[List[str], List[str]]] = []
        path: List[tuple[int, str]] = []
        body: List[str] = []
        in_fence = False

        def flush() -> None:
            if any(line.strip() for line in body):
                sections.append(([title for _, title in path], list(body)))
            body.clear()

        for line in text.splitlines():
            if _FENCE_RE.match(line):
                in_fence = not in_fence
            match = None if in_fence else _ATX_HEADER_RE.match(line)
            if match:
                flush()
                level = len(match.group(1))
                path = [(lvl, title) for lvl, title in path if lvl < level]
                path.append((level, match.group(2).strip()))
            else:
                body.append(line)
        flush()

        chunks: List[str] = []
        for titles, lines in sections:
            content = "\n".join(lines).strip()
            prefix = " > ".join(titles)
            room = max(chunk_size - (len(prefix) + 2 if prefix else 0), chunk_size // 4)
            if len(content) <= room:
                pieces = [content]
            else:
                pieces = self.sentence_chunking(content, chunk_size=room, overlap=overlap)
            chunks.extend(f"{prefix}\n\n{piece}" if prefix else piece for piece in pieces)
        return chunks

    def semantic_chunking(
        self, text: str, chunk_size: Optional[int] = None, max_k: int = 10
    ) -> List[str]:
        """Cluster sentences by TF-IDF with KMeans, k picked by silhouette score."""
        chunk_size = chunk_size or self.default_chunk_size
        if not text or not text.strip():
            return []
        sentences = _split_sentences(text)
        if len(sentences) < 4:
            return self._pack_sentences(sentences, chunk_size, 0)
        try:
            import numpy as np
            from sklearn.cluster import KMeans
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics import silhouette_score

            X = TfidfVectorizer().fit_transform(sentences)
            best_k, best_score = 2, -1.0
            for k in range(2, min(max_k, len(sentences) - 1) + 1):
                labels = KMeans(n_clusters=k, random_state=RANDOM_SEED, n_init=10).fit_predict(X)
                if len(set(labels)) < 2:
                    continue
                score = silhouette_score(X, labels)
                if score > best_score:
                    best_k, best_score = k, score
            labels = KMeans(n_clusters=best_k, random_state=RANDOM_SEED, n_init=10).fit_predict(X)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Semantic chunking unavailable ({e}), packing sentences instead")
            return self._pack_sentences(sentences, chunk_size, 0)

        clusters: dict[int, List[str]] = {}
        for sentence, label in zip(sentences, np.asarray(labels).tolist()):
            clusters.setdefault(label, []).append(sentence)
        chunks: List[str] = []
        for members in clusters.values():
            chunks.extend(self._pack_sentences(members, chunk_size, 0))
        return chunks

    def chunk(
        self,
        text: str,
        method: ChunkingMethod = ChunkingMethod.RECURSIVE_CHARACTER,
        chunk_size: Optional[int] = None,
        overlap: Optional[int] = None,
        **kwargs
    ) -> List[str]:
        """
        Chunk text using the specified method.
        Default is recursive_character (same as streaming-decision-process).
        
        Args:
            text: Text to chunk
            method: Chunking method to use
            chunk_size: Override default chunk size
            overlap: Override default overlap
            **kwargs: Additional method-specific parameters
        
        Returns:
            List of text chunks
        """
        try:
            method = ChunkingMethod(method)
        except ValueError:
            pass
        if method == ChunkingMethod.SENTENCE:
            return self.sentence_chunking(text, chunk_size=chunk_size, overlap=overlap)
        if method == ChunkingMethod.MARKDOWN:
            return self.markdown_chunking(text, chunk_size=chunk_size, overlap=overlap)
        if method == ChunkingMethod.SEMANTIC:
            return self.semantic_chunking(text, chunk_size=chunk_size)
        if method == ChunkingMethod.FIXED:
            return self.fixed_chunking(text, chunk_size=chunk_size)
        elif method == ChunkingMethod.RECURSIVE_CHARACTER:
            return self.recursive_character_chunking(text, chunk_size=chunk_size, overlap=overlap)
        elif method == ChunkingMethod.SENTENCE_BOUNDARY:
            return self.sentence_boundary_chunking(text)
        elif method == ChunkingMethod.HIERARCHICAL:
            paragraph_size = kwargs.get('paragraph_chunk_size', 5)
            sentence_size = kwargs.get('sentence_chunk_size', 5)
            return self.hierarchical_chunking(text, paragraph_size, sentence_size)
        else:
            # For now, fallback to recursive_character for unsupported methods
            logger.warning(f"Chunking method {method} not fully implemented, using recursive_character")
            return self.recursive_character_chunking(text, chunk_size=chunk_size, overlap=overlap)

