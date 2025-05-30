"""
DocMeta - Document Metadata Extraction Package

This package provides functionality to extract metadata from various document types.
It supports common metadata extraction for all file types and specific metadata
extraction for supported file types like PDFs, images, and documents.
"""

__version__ = "0.1.0"

# Import extractors to trigger registration
import docmeta.extractors
from docmeta.core import (FileMetaData, ImageMetaData, MarkupMetaData,
                          OfficeMetaData, OpenDocumentMetaData, PDFMetaData,
                          StructuredDataMetaData, TextMetaData,
                          extract_metadata)

__all__ = [
    "extract_metadata",
    "FileMetaData",
    "PDFMetaData",
    "ImageMetaData",
    "OfficeMetaData",
    "OpenDocumentMetaData",
    "TextMetaData",
    "MarkupMetaData",
    "StructuredDataMetaData",
]
