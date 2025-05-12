"""
Public API for the docmeta package.

This module provides the main entry points for the package.
"""

from docmeta.core.factory import extract_metadata
from docmeta.core.types import (
    DocMetaData,
    PDFMetaData,
    ImageMetaData,
    DocumentMetaData,
    MetadataType,
)

# Re-export for convenience
__all__ = [
    "extract_metadata",
    "DocMetaData",
    "PDFMetaData",
    "ImageMetaData",
    "DocumentMetaData",
]
