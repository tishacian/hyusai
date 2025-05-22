"""
Type definitions for document metadata.

This module contains TypedDict classes for different document types.
"""

from datetime import datetime
from typing import TypedDict, Any, Callable


class FileMetaData(TypedDict):
    """Base metadata common to all file types."""
    file_path: str
    file_name: str
    file_extension: str
    mime_type: str
    file_permissions: str
    size: int
    creation_time: datetime
    last_modified_time: datetime
    last_accessed_time: datetime


class PDFMetaData(FileMetaData):
    """Metadata specific to PDF files."""
    author: str | None
    creator: str | None
    producer: str | None
    subject: str | None
    title: str | None
    num_pages: int
    embedded_keywords: list[str] | None  # Keywords sourced directly from the PDF document's embedded metadata
    extracted_keywords: list[str] | None  # Keywords programmatically generated from analyzing the document's text content (e.g., TF-IDF)
    encrypted: bool
    page_width: float | None
    page_height: float | None
    token_count: int | None  # Default encoding is cl100k_base (used by ChatGPT, GPT-4)


class ImageMetaData(FileMetaData):
    """Metadata specific to image files."""
    width: int
    height: int
    color_mode: str | None  # e.g., "RGB", "CMYK", "Grayscale"
    bit_depth: int | None
    dpi_x: int | None
    dpi_y: int | None
    exif_data: dict[str, Any] | None


class DocumentMetaData(FileMetaData):
    """Metadata specific to document files (docx, odt, etc.)."""
    author: str | None
    title: str | None
    subject: str | None
    embedded_keywords: list[str] | None  # Keywords sourced directly from the document's embedded metadata
    extracted_keywords: list[str] | None  # Keywords programmatically generated from analyzing the document's text content (e.g., TF-IDF)
    modified: datetime | None
    last_modified_by: str | None
    num_pages: int | None  # Optional as some formats like .txt don't have native page concept
    word_count: int
    character_count: int
    paragraph_count: int
    line_count: int


# Type for metadata extractors
MetadataType = FileMetaData | PDFMetaData | ImageMetaData | DocumentMetaData
MetadataExtractor = Callable[[str], MetadataType]
