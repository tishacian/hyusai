"""Text processing pipeline for cleaning and structuring text before indexing"""
import re
import unicodedata
from typing import List, Dict, Optional
from app.core.logging import get_logger

logger = get_logger(__name__)


class TextProcessor:
    """Process and clean text before indexing"""
    
    @staticmethod
    def clean_text(text: str, min_alpha_ratio: float = 0.3) -> str:
        """
        Clean text by removing noise, non-printable characters, and low-quality content.
        
        Args:
            text: Raw text to clean
            min_alpha_ratio: Minimum ratio of alphabetic characters (0.0-1.0)
        
        Returns:
            Cleaned text or empty string if quality is too low
        """
        if not text or not isinstance(text, str):
            return ""
        
        # Remove PDF structure markers and hex data
        text = re.sub(r'(\d+\s+)?obj\s*<<.*?>>\s*endobj', '', text, flags=re.DOTALL)
        text = re.sub(r'stream.*?endstream', '', text, flags=re.DOTALL)
        text = re.sub(r'xref.*?trailer', '', text, flags=re.DOTALL)
        text = re.sub(r'startxref', '', text, flags=re.DOTALL)
        text = re.sub(r'%%EOF', '', text, flags=re.DOTALL)
        text = re.sub(r'/\w+\s+\d+\s+0\s+R', '', text)  # PDF references like /Parent 1032 0 R
        text = re.sub(r'<<.*?>>', '', text)  # Remove generic dictionary-like structures
        
        # Remove non-printable characters (except common whitespace)
        cleaned_chars = []
        for char in text:
            category = unicodedata.category(char)
            if category[0] != 'C' or char in ('\n', '\t', '\r', ' '):
                cleaned_chars.append(char)
        text = ''.join(cleaned_chars)
        
        # Remove sequences of non-alphanumeric characters that are likely noise
        text = re.sub(r'[^a-zA-Z0-9\s.,;!?\-]{2,}', ' ', text)
        
        # Preserve paragraph breaks (double newlines) while normalizing other whitespace
        # First, normalize multiple spaces/tabs to single space (but keep newlines)
        text = re.sub(r'[ \t]+', ' ', text)
        # Normalize multiple newlines to double newline (paragraph break)
        text = re.sub(r'\n{3,}', '\n\n', text)
        # Normalize single newlines within paragraphs to space (but preserve paragraph breaks)
        text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)
        # Clean up any remaining excessive spaces
        text = re.sub(r' {2,}', ' ', text)
        text = text.strip()
        
        # Filter out low-quality chunks
        if len(text) < 10:
            return ""
        
        # Check alphabetic ratio
        alpha_count = sum(1 for c in text if c.isalpha())
        if len(text) > 0 and alpha_count / len(text) < min_alpha_ratio:
            return ""
        
        return text
    
    @staticmethod
    def process_chunks(chunks: List[Dict], min_alpha_ratio: float = 0.3) -> List[Dict]:
        """
        Process and clean a list of chunks.
        
        Args:
            chunks: List of chunk dictionaries with 'content' key
            min_alpha_ratio: Minimum ratio of alphabetic characters
        
        Returns:
            List of cleaned chunks
        """
        processed_chunks = []
        for chunk in chunks:
            original_content = chunk.get("content", "")
            cleaned_content = TextProcessor.clean_text(original_content, min_alpha_ratio)
            
            if cleaned_content:
                # Update chunk with cleaned content
                processed_chunk = chunk.copy()
                processed_chunk["content"] = cleaned_content
                processed_chunks.append(processed_chunk)
            else:
                logger.debug(f"Filtered out low-quality chunk: {original_content[:50]}...")
        
        return processed_chunks
    
    @staticmethod
    def structure_text(text: str) -> Dict[str, any]:
        """
        Structure text by extracting metadata and organizing content.
        
        Args:
            text: Text to structure
        
        Returns:
            Dictionary with structured information
        """
        # Extract paragraphs
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        
        # Extract sentences
        sentences = re.split(r'(?<=[.!?])\s+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        # Extract potential headings (lines that are short and end with colon or are all caps)
        headings = []
        for line in text.split('\n'):
            line = line.strip()
            if line and (line.endswith(':') or (len(line) < 100 and line.isupper())):
                headings.append(line)
        
        return {
            "paragraphs": paragraphs,
            "sentences": sentences,
            "headings": headings,
            "word_count": len(text.split()),
            "char_count": len(text),
        }

