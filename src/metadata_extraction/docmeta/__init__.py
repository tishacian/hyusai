"""
DocMeta - Document Metadata Extraction Package

This package provides functionality to extract metadata from various document types.
It supports common metadata extraction for all file types and specific metadata
extraction for supported file types like PDFs, images, and documents.
"""

__version__ = "0.1.0"

# Import main functionality for easy access
from docmeta.core.api import extract_metadata
from docmeta.core.types import (
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
