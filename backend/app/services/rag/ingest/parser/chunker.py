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

