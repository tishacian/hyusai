"""
Core functionality for the docmeta package.

This package contains the core functionality for extracting metadata from files.
"""

# Import for convenience
from docmeta.core.factory import extract_metadata
from docmeta.core.types import (
    FileMetaData,
    PDFMetaData,
    ImageMetaData,
    DocumentMetaData,
    MetadataType,
    create_pdf_metadata,
    create_image_metadata,
    create_document_metadata,
)

__all__ = [
    "extract_metadata",
    "FileMetaData",
    "PDFMetaData",
    "ImageMetaData",
    "DocumentMetaData",
    "MetadataType",
    "create_pdf_metadata",
    "create_image_metadata",
    "create_document_metadata",
]
