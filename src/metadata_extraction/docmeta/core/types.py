import mimetypes
import os
import stat
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, TypedDict


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

    num_pages: int
    encrypted: bool
    
    author: str | None
    creator: str | None
    producer: str | None
    subject: str | None
    title: str | None
    embedded_keywords: (
        list[str] | None
    )  # Keywords sourced directly from the PDF document's embedded metadata
    extracted_keywords: (
        list[str] | None
    )  # Keywords programmatically generated from analyzing the document's text content (e.g., TF-IDF)
    page_width: float | None
    page_height: float | None
    token_count: int | None


class ImageMetaData(FileMetaData):
    """Metadata specific to image files."""

    width: int
    height: int
    color_mode: str | None  # e.g., "RGB", "CMYK", "Grayscale"
    bit_depth: int | None
    dpi_x: int | None
    dpi_y: int | None
    exif_data: dict[str, Any] | None


class OfficeMetaData(FileMetaData):
    """Metadata specific to Microsoft Office files."""

    word_count: int
    character_count: int
    paragraph_count: int
    
    author: str | None
    title: str | None
    subject: str | None
    embedded_keywords: list[str] | None
    extracted_keywords: list[str] | None
    last_modified_by: str | None
    num_pages: int | None  # Pages for Word, slides for PowerPoint, sheets for Excel
    num_slides: int | None  # PowerPoint specific
    num_sheets: int | None  # Excel specific
    application: str | None  # e.g., "Microsoft Word", "Microsoft Excel"
    app_version: str | None
    token_count: int | None


class OpenDocumentMetaData(FileMetaData):
    """Metadata specific to OpenDocument files."""

    word_count: int
    character_count: int
    paragraph_count: int
    
    author: str | None
    title: str | None
    subject: str | None
    embedded_keywords: list[str] | None
    extracted_keywords: list[str] | None
    last_modified_by: str | None
    num_pages: int | None
    generator: str | None  # Application that created the document
    language: str | None
    token_count: int | None


class TextMetaData(FileMetaData):
    """Metadata specific to plain text and markdown files."""

    word_count: int
    character_count: int
    line_count: int
    paragraph_count: int
    has_front_matter: bool  # For markdown files with YAML front matter
    
    encoding: str | None
    extracted_keywords: list[str] | None
    language: str | None  # Detected language
    token_count: int | None


class MarkupMetaData(FileMetaData):
    """Metadata specific to markup files (HTML, XML)."""

    element_count: int
    
    title: str | None
    encoding: str | None
    doctype: str | None
    meta_description: str | None
    meta_keywords: list[str] | None
    extracted_keywords: list[str] | None
    language: str | None
    link_count: int | None  # HTML specific
    image_count: int | None  # HTML specific
    token_count: int | None


class StructuredDataMetaData(FileMetaData):
    """Metadata specific to structured data files (CSV, JSON)."""

    encoding: str | None
    schema_type: str | None  # e.g., "CSV", "JSON", "YAML"
    record_count: int | None  # Rows for CSV, objects for JSON
    column_count: int | None  # CSV specific
    columns: list[str] | None  # CSV column names
    data_types: dict[str, str] | None  # Column data types
    has_header: bool | None  # CSV specific
    extracted_keywords: list[str] | None
    token_count: int | None


# Type for metadata extractors
MetadataType = (
    FileMetaData
    | PDFMetaData
    | ImageMetaData
    | OfficeMetaData
    | OpenDocumentMetaData
    | TextMetaData
    | MarkupMetaData
    | StructuredDataMetaData
)
MetadataExtractor = Callable[[str], tuple[dict[str, Any], str | None]]


def get_file_common_metadata(path: str) -> FileMetaData:
    """
    Extract common metadata.

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
def create_pdf_metadata() -> dict[str, Any]:
    """
    Create PDFMetaData.

    Returns:
        dict[str, Any]: Initialized metadata dictionary
    """
    # Initialize PDF-specific metadata with default values
    return {
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


def create_image_metadata() -> dict[str, Any]:
    """
    Create ImageMetaData.

    Returns:
        dict[str, Any]: Initialized metadata dictionary
    """
    # Initialize image-specific metadata with default values
    return {
        "width": 0,
        "height": 0,
        "color_mode": None,
        "bit_depth": None,
        "dpi_x": None,
        "dpi_y": None,
        "exif_data": None,
    }


def create_office_metadata() -> dict[str, Any]:
    """
    Create OfficeMetaData.

    Returns:
        dict[str, Any]: Initialized metadata dictionary
    """
    # Initialize Office-specific metadata with default values
    return {
        "author": None,
        "title": None,
        "subject": None,
        "embedded_keywords": None,
        "extracted_keywords": None,
        "last_modified_by": None,
        "num_pages": None,
        "num_slides": None,
        "num_sheets": None,
        "word_count": 0,
        "character_count": 0,
        "paragraph_count": 0,
        "application": None,
        "app_version": None,
        "token_count": None,
    }


def create_opendocument_metadata() -> dict[str, Any]:
    """
    Create OpenDocumentMetaData.

    Returns:
        dict[str, Any]: Initialized metadata dictionary
    """
    # Initialize OpenDocument-specific metadata with default values
    return {
        "author": None,
        "title": None,
        "subject": None,
        "embedded_keywords": None,
        "extracted_keywords": None,
        "last_modified_by": None,
        "num_pages": None,
        "word_count": 0,
        "character_count": 0,
        "paragraph_count": 0,
        "generator": None,
        "language": None,
        "token_count": None,
    }


def create_text_metadata() -> dict[str, Any]:
    """
    Create TextMetaData.

    Returns:
        dict[str, Any]: Initialized metadata dictionary
    """
    # Initialize text-specific metadata with default values
    return {
        "encoding": None,
        "word_count": 0,
        "character_count": 0,
        "line_count": 0,
        "paragraph_count": 0,
        "extracted_keywords": None,
        "language": None,
        "has_front_matter": False,
        "token_count": None,
    }


def create_markup_metadata() -> dict[str, Any]:
    """
    Create MarkupMetaData.

    Returns:
        dict[str, Any]: Initialized metadata dictionary
    """
    # Initialize markup-specific metadata with default values
    return {
        "title": None,
        "encoding": None,
        "doctype": None,
        "meta_description": None,
        "meta_keywords": None,
        "extracted_keywords": None,
        "language": None,
        "element_count": 0,
        "link_count": None,
        "image_count": None,
        "token_count": None,
    }


def create_structured_data_metadata() -> dict[str, Any]:
    """
    Create StructuredDataMetaData.

    Returns:
        dict[str, Any]: Initialized metadata dictionary
    """
    # Initialize data-specific metadata with default values
    return {
        "encoding": None,
        "schema_type": None,
        "record_count": None,
        "column_count": None,
        "columns": None,
        "data_types": None,
        "has_header": None,
        "extracted_keywords": None,
        "token_count": None,
    }
