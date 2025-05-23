"""
Metadata Extractor Factory

This module provides a factory for selecting the appropriate metadata extractor
based on file type.
"""

import os
import mimetypes

from docmeta.core.types import MetadataExtractor, MetadataType, get_file_common_metadata


# Registry of extractors by file extension
EXTENSION_EXTRACTORS: dict[str, MetadataExtractor] = {}

# Registry of extractors by MIME type
MIME_TYPE_EXTRACTORS: dict[str, MetadataExtractor] = {}


def register_extractor(extensions: list[str], mime_types: list[str], extractor: MetadataExtractor) -> None:
    """
    Register an extractor for specific file extensions and MIME types.

    Args:
        extensions: List of file extensions (e.g., ['.pdf', '.PDF'])
        mime_types: List of MIME types (e.g., ['application/pdf'])
        extractor: Function to extract metadata
    """
    # Register for extensions
    for ext in extensions:
        EXTENSION_EXTRACTORS[ext.lower()] = extractor

    # Register for MIME types
    for mime_type in mime_types:
        MIME_TYPE_EXTRACTORS[mime_type.lower()] = extractor


def get_extractor(path: str) -> MetadataExtractor:
    """
    Get the appropriate metadata extractor for a file.

    Args:
        path: Path to the file

    Returns:
        MetadataExtractor: Function to extract metadata from the file
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    # Get file extension
    _, extension = os.path.splitext(path)
    extension = extension.lower()

    # Try to get extractor by extension
    extractor = EXTENSION_EXTRACTORS.get(extension)

    # If no extractor found by extension, try by MIME type
    if extractor is None:
        mime_type, _ = mimetypes.guess_type(path)
        if mime_type:
            extractor = MIME_TYPE_EXTRACTORS.get(mime_type.lower())

    # If still no extractor found, use common metadata extractor
    if extractor is None:
        extractor = get_file_common_metadata

    return extractor


def extract_metadata(path: str, count_tokens: bool = False, extract_keywords: bool = False) -> MetadataType:
    """
    Extract metadata from a file.

    Args:
        path: Path to the file
        count_tokens: Whether to count tokens in text-based files (default: False)
        extract_keywords: Whether to extract keywords from text-based files (default: False)

    Returns:
        MetadataType: Metadata for the file
    """
    extractor = get_extractor(path)

    # Prepare arguments for the extractor based on its capabilities
    extractor_args = {}
    if hasattr(extractor, '__code__'): # Check if it's a function we can inspect
        varnames = extractor.__code__.co_varnames
        if 'count_tokens_flag' in varnames:
            extractor_args['count_tokens_flag'] = count_tokens
        if 'extract_keywords_flag' in varnames:
            extractor_args['extract_keywords_flag'] = extract_keywords

    if extractor_args:
        return extractor(path, **extractor_args)
    else:
        return extractor(path)
