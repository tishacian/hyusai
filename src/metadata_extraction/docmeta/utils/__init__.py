"""
Utility functions for the docmeta package.

This package contains utility functions for working with document metadata.
"""

# Token counting utilities
from docmeta.utils.token_counter import count_tokens

# Keyword extraction utilities  
from docmeta.utils.keyword_extractor import (
    extract_keywords_tfidf,
    clean_text_for_tfidf,
    get_stopwords,
)

# Serialization utilities
from docmeta.utils.serializers import (
    DateTimeEncoder,
    to_json,
    format_metadata,
    save_json,
)

__all__ = [
    # Token counting
    "count_tokens",
    
    # Keyword extraction
    "extract_keywords_tfidf",
    "clean_text_for_tfidf", 
    "get_stopwords",
    
    # Serialization
    "DateTimeEncoder",
    "to_json",
    "format_metadata",
    "save_json",
]
