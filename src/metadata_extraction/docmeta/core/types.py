"""
Type definitions for document metadata.

This module contains TypedDict classes for different document types.
"""

from datetime import datetime
from typing import TypedDict, Dict, Any, Optional, List, Union, Callable


class DocMetaData(TypedDict):
    """Base metadata common to all document types."""
    file_path: str
    file_name: str
    file_extension: str
    mime_type: str
    file_permissions: str
    size: int
    creation_time: datetime
    last_modified_time: datetime
    last_accessed_time: datetime
    extracted_keywords: Optional[List[str]]


class PDFMetaData(DocMetaData):
    """Metadata specific to PDF files."""
    author: Optional[str]
    creator: Optional[str]
    producer: Optional[str]
    subject: Optional[str]
    title: Optional[str]
    num_pages: int
    keywords: Optional[List[str]]
    encrypted: bool
    page_size: Optional[Dict[str, float]]  # e.g., {"width": 612.0, "height": 792.0}
    token_count: Optional[Dict[str, int]]  # e.g., {"cl100k_base": 1234, "p50k_base": 2345}


class ImageMetaData(DocMetaData):
    """Metadata specific to image files."""
    width: int
    height: int
    color_mode: Optional[str]  # e.g., "RGB", "CMYK", "Grayscale"
    bit_depth: Optional[int]
    dpi: Optional[Dict[str, int]]  # e.g., {"x": 72, "y": 72}
    exif_data: Optional[Dict[str, Any]]


class DocumentMetaData(DocMetaData):
    """Metadata specific to document files (docx, odt, etc.)."""
    author: Optional[str]
    title: Optional[str]
    subject: Optional[str]
    keywords: Optional[List[str]]
    created: Optional[datetime]
    modified: Optional[datetime]
    last_modified_by: Optional[str]
    num_pages: Optional[int]
    word_count: Optional[int]
    character_count: Optional[int]
    paragraph_count: Optional[int]
    line_count: Optional[int]


# Type for metadata extractors
MetadataType = Union[DocMetaData, PDFMetaData, ImageMetaData, DocumentMetaData]
MetadataExtractor = Callable[[str], MetadataType]
