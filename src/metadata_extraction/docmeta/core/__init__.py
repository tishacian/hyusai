"""
Core functionality for the docmeta package.

This package contains the core functionality for extracting metadata from files.
"""

# Import for convenience
from docmeta.core.api import (
    extract_metadata,
    DocMetaData,
    PDFMetaData,
    ImageMetaData,
    DocumentMetaData,
)

__all__ = [
    "extract_metadata",
    "DocMetaData",
    "PDFMetaData",
    "ImageMetaData",
    "DocumentMetaData",
]
