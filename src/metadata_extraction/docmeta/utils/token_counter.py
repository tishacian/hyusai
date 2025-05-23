"""
Token counting utilities for text analysis.

This module provides functions for counting tokens in text using various encodings,
with support for streaming processing to handle large documents efficiently.
"""

import re
import tiktoken

# Default encoding for token counting
DEFAULT_ENCODING = "o200k_base"


def count_tokens(text_content: str | list[str], base: str = DEFAULT_ENCODING) -> int:
    """
    Count tokens in text using the specified tiktoken encoding.
    Supports both single strings and iterables of text chunks for streaming processing.

    Args:
        text_content: Text to count tokens in (string or iterable of strings)
        base: Encoding to use (default: o200k_base)

    Returns:
        int: Token count
    """
    encoding = tiktoken.get_encoding(base)
    total_tokens = 0
    
    # Handle both single strings and iterables (streaming)
    if isinstance(text_content, str):
        if not text_content:
            return 0
        # Clean the text - remove excessive whitespace
        cleaned_text = re.sub(r'\s+', ' ', text_content).strip()
        return len(encoding.encode(cleaned_text))
    else:
        # Streaming mode: process chunks one at a time to avoid memory issues
        for chunk in text_content:
            if chunk:
                # Clean each chunk - remove excessive whitespace
                cleaned_chunk = re.sub(r'\s+', ' ', chunk).strip()
                total_tokens += len(encoding.encode(cleaned_chunk))
        return total_tokens 