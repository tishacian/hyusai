"""
Metadata Extractor Factory

This module provides a factory for selecting the appropriate metadata extractor
based on file type.
"""

import mimetypes
import os
from typing import Any

from .types import FileMetaData, MetadataExtractor, MetadataType
from ..utils.file_metadata import get_file_common_metadata
from ..utils.keyword_extractor import extract_keywords_tfidf
from ..utils.text_processing import validate_file_exists
from ..utils.token_counter import count_tokens

# Registry of extractors by file extension
EXTENSION_EXTRACTORS: dict[str, MetadataExtractor] = {}

# Registry of extractors by MIME type
MIME_TYPE_EXTRACTORS: dict[str, MetadataExtractor] = {}


def register_extractor(
    extensions: list[str], mime_types: list[str], extractor: MetadataExtractor
) -> None:
    """
    Register an extractor for specific file extensions and MIME types.

    Args:
        extensions: List of file extensions (e.g., ['.pdf', '.PDF'])
        mime_types: List of MIME types (e.g., ['application/pdf'])
        extractor: Function to extract metadata
    """
    for ext in extensions:
        EXTENSION_EXTRACTORS[ext.lower()] = extractor

    for mime_type in mime_types:
        MIME_TYPE_EXTRACTORS[mime_type.lower()] = extractor


def get_extractor(path: str) -> MetadataExtractor | None:
    """
    Get the appropriate metadata extractor for a file.

    Args:
        path: Path to the file

    Returns:
        MetadataExtractor: Function to extract metadata from the file or None if no specific extractor is found
    """
    # File existence is validated by the caller (extract_metadata)
    _, extension = os.path.splitext(path)
    extension = extension.lower()

    extractor = EXTENSION_EXTRACTORS.get(extension)

    if extractor is None:
        mime_type, _ = mimetypes.guess_type(path)
        if mime_type:
            extractor = MIME_TYPE_EXTRACTORS.get(mime_type.lower())

    return extractor


def extract_metadata(
    path: str,
    count_tokens_flag: bool = False,
    extract_keywords_language: str | None = None,
) -> MetadataType:
    """
    Extract metadata from a file.

    Args:
        path: Path to the file
        count_tokens_flag: Whether to count tokens in text-based files (default: False)
        extract_keywords_language: Language for keyword extraction (None to skip, e.g., "french", "english")

    Returns:
        MetadataType: Metadata for the file
    """
    validate_file_exists(path)
    common_metadata: FileMetaData = get_file_common_metadata(path)
    metadata: dict[str, Any] = {}
    text_content: str | None = None

    extractor_func = get_extractor(path)

    if extractor_func:
        metadata, text_content = extractor_func(path)

    result: MetadataType = {**metadata, **common_metadata}

    if text_content and text_content.strip():
        if count_tokens_flag:
            result["token_count"] = count_tokens(text_content)

        if extract_keywords_language:
            keywords = extract_keywords_tfidf(
                text_content, language=extract_keywords_language
            )
            if keywords:
                result["extracted_keywords"] = keywords

    return result
