"""
Metadata Default Values

This module provides functions for creating metadata dictionaries with default values
for different file types. These functions ensure consistent initialization of metadata structures
across all extractors.
"""

from typing import Any


def create_pdf_metadata() -> dict[str, Any]:
    """
    Create PDFMetaData with default values.

    Returns:
        dict[str, Any]: Initialized metadata dictionary
    """
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
    Create ImageMetaData with default values.

    Returns:
        dict[str, Any]: Initialized metadata dictionary
    """
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
    Create OfficeMetaData with default values.

    Returns:
        dict[str, Any]: Initialized metadata dictionary
    """
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
    Create OpenDocumentMetaData with default values.

    Returns:
        dict[str, Any]: Initialized metadata dictionary
    """
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
    Create TextMetaData with default values.

    Returns:
        dict[str, Any]: Initialized metadata dictionary
    """
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
    Create MarkupMetaData with default values.

    Returns:
        dict[str, Any]: Initialized metadata dictionary
    """
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
    Create StructuredDataMetaData with default values.

    Returns:
        dict[str, Any]: Initialized metadata dictionary
    """
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
