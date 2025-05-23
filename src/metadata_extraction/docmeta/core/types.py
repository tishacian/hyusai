"""
Type definitions for document metadata.

This module contains TypedDict classes for different document types.
"""

import mimetypes
import os
import stat
from datetime import datetime
from pathlib import Path
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


def get_file_common_metadata(path: str) -> FileMetaData:
    """
    Extract common metadata from a file.

    Args:
        path: Path to the file

    Returns:
        FileMetaData: Common metadata for the file
    """
    stats = os.stat(path)
    pathlib_path = Path(path)

    # Initialize with required fields
    metadata: dict[str, Any] = {
        "file_path": str(pathlib_path.resolve()),
        "file_name": pathlib_path.name,
        "file_extension": pathlib_path.suffix.lower(),
        "mime_type": mimetypes.guess_type(path)[0] or "application/octet-stream",
        "file_permissions": stat.filemode(stats.st_mode),
        "size": stats.st_size,
        "last_modified_time": datetime.fromtimestamp(stats.st_mtime),
        "last_accessed_time": datetime.fromtimestamp(stats.st_atime),
    }

    # Handle creation time which is platform-dependent
    if hasattr(stats, "st_birthtime"):
        creation_time_in_s = stats.st_birthtime
    else:
        # st_birthtime is not available on Linux platform, st_ctime should be used instead
        creation_time_in_s = stats.st_ctime

    metadata["creation_time"] = datetime.fromtimestamp(creation_time_in_s)

    return metadata


# Factory functions for creating metadata with default values
def create_pdf_metadata(path: str) -> PDFMetaData:
    """
    Create PDFMetaData with common file properties and default values.

    Args:
        path: Path to the PDF file

    Returns:
        PDFMetaData: Initialized metadata dictionary
    """
    # Get common metadata (file size, creation time, etc.)
    common_metadata = get_file_common_metadata(path)
    
    # Initialize PDF-specific metadata with default values
    return common_metadata | {
        "author": None,
        "creator": None,
        "producer": None,
        "subject": None,
        "title": None,
        "num_pages": 0,
        "embedded_keywords": None,
        "encrypted": False,
        "page_width": None,
        "page_height": None,
        "token_count": None,
        "extracted_keywords": None,
    }


def create_image_metadata(path: str) -> ImageMetaData:
    """
    Create ImageMetaData with common file properties and default values.

    Args:
        path: Path to the image file

    Returns:
        ImageMetaData: Initialized metadata dictionary
    """
    # Get common metadata (file size, creation time, etc.)
    common_metadata = get_file_common_metadata(path)
    
    # Initialize image-specific metadata with default values
    return common_metadata | {
        "width": 0,
        "height": 0,
        "color_mode": None,
        "bit_depth": None,
        "dpi_x": None,
        "dpi_y": None,
        "exif_data": None,
    }


def create_document_metadata(path: str) -> DocumentMetaData:
    """
    Create DocumentMetaData with common file properties and default values.

    Args:
        path: Path to the document file

    Returns:
        DocumentMetaData: Initialized metadata dictionary
    """
    # Get common metadata (file size, creation time, etc.)
    common_metadata = get_file_common_metadata(path)
    
    # Initialize document-specific metadata with default values
    return common_metadata | {
        "author": None,
        "title": None,
        "subject": None,
        "embedded_keywords": None,
        "extracted_keywords": None,
        "modified": None,
        "last_modified_by": None,
        "num_pages": None,  # Optional as some formats like .txt don't have native page concept
        "word_count": 0,
        "character_count": 0,
        "paragraph_count": 0,
        "line_count": 0,
    }
