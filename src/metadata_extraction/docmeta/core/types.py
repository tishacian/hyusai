from collections.abc import Callable
from datetime import datetime
from typing import Any, TypedDict


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
"""Type for metadata extractor functions. Takes file path, returns (metadata dict, text content)."""
