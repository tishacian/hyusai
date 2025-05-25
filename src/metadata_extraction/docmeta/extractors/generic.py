"""
Generic Metadata Extractor

This module provides fallback functionality for unsupported file types.
Returns basic file system metadata for any file type.
"""

import logging
import os

from docmeta.core.types import FileMetaData, get_file_common_metadata

# Configure logger
logger = logging.getLogger(__name__)


def extract_generic_metadata(path: str) -> FileMetaData:
    """
    Extract basic metadata from any file type.

    Args:
        path: Path to the file

    Returns:
        FileMetaData: Basic metadata for the file
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    # Return only common file system metadata
    return get_file_common_metadata(path)
