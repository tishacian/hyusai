"""
OpenDocument Metadata Extractor

This module provides functionality to extract metadata from OpenDocument files.
Supports ODT, ODS, and ODP formats with comprehensive metadata extraction.
"""

import logging
from typing import Any

# Import required libraries for OpenDocument processing
from odf import opendocument
from odf.opendocument import Meta
from odf.text import P, H, Span # Used in _extract_text_content

from docmeta.core.types import create_opendocument_metadata # returns dict[str, Any]
from docmeta.utils.text_processing import (
    get_file_extension,
    extract_common_metadata_fields,
    extract_and_parse_keywords,
    extract_statistics_from_meta
)

# Configure logger
logger = logging.getLogger(__name__)


def _extract_text_content(doc) -> str | None:
    """
    Extract text content from an OpenDocument.

    Args:
        doc: OpenDocument object

    Returns:
        str: Extracted text content, or None if empty
    """
    text_elements = []

    for element_type in [P, H, Span]:
        for element in doc.getElementsByType(element_type):
            # Efficiently build text content using a generator expression
            text_content = "".join(node.data for node in element.childNodes if node.nodeType == node.TEXT_NODE)
            if text_content.strip():
                text_elements.append(text_content.strip())
    
    return '\n'.join(text_elements) if text_elements else None


def _extract_with_odt(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and text from an ODT file.

    Args:
        path: Path to the ODT file

    Returns:
        tuple[dict[str, Any], str | None]: Specific ODT metadata and text content.
    """
    metadata = create_opendocument_metadata()
    doc = opendocument.load(path)
    meta_elements = doc.getElementsByType(Meta)
    
    if not meta_elements:
        logger.warning(f"No Meta element found in ODT: {path}")
        text_content_early = _extract_text_content(doc) # Try to get text even if meta is missing
        return metadata, text_content_early

    meta = meta_elements[0]

    if hasattr(meta, 'getAttribute'):
        field_mapping = {
            'author': 'creator',
            'title': 'title',
            'subject': 'subject',
            'generator': 'generator',
            'language': 'language'
        }
        extract_common_metadata_fields(meta, metadata, field_mapping)
        extract_and_parse_keywords(meta, metadata, 'keyword')

    if hasattr(meta, 'statistics'):
        stats = meta.statistics
        field_mapping = {
            'num_pages': 'page-count',
            'word_count': 'word-count',
            'character_count': 'character-count',
            'paragraph_count': 'paragraph-count'
        }
        stats_data = extract_statistics_from_meta(stats, field_mapping)
        metadata.update(stats_data)

    text_content = _extract_text_content(doc)
    return metadata, text_content


def _extract_with_ods(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and text from an ODS file.

    Args:
        path: Path to the ODS file

    Returns:
        tuple[dict[str, Any], str | None]: Specific ODS metadata and text content.
    """
    metadata = create_opendocument_metadata()
    doc = opendocument.load(path)
    meta_elements = doc.getElementsByType(Meta)

    if not meta_elements:
        logger.warning(f"No Meta element found in ODS: {path}")
        text_content_early = _extract_text_content(doc)
        return metadata, text_content_early

    meta = meta_elements[0]

    if hasattr(meta, 'getAttribute'):
        field_mapping = {
            'author': 'creator',
            'title': 'title',
            'subject': 'subject',
            'generator': 'generator',
            'language': 'language'
        }
        extract_common_metadata_fields(meta, metadata, field_mapping)
        extract_and_parse_keywords(meta, metadata, 'keyword')

    if hasattr(meta, 'statistics'):
        stats = meta.statistics
        field_mapping = {
            'num_pages': 'table-count',
            'word_count': 'cell-count',
            'character_count': 'character-count'
        }
        stats_data = extract_statistics_from_meta(stats, field_mapping)
        metadata.update(stats_data)

    text_content = _extract_text_content(doc)
    return metadata, text_content


def _extract_with_odp(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and text from an ODP file.

    Args:
        path: Path to the ODP file

    Returns:
        tuple[dict[str, Any], str | None]: Specific ODP metadata and text content.
    """
    metadata = create_opendocument_metadata()
    doc = opendocument.load(path)
    meta_elements = doc.getElementsByType(Meta)

    if not meta_elements:
        logger.warning(f"No Meta element found in ODP: {path}")
        text_content_early = _extract_text_content(doc)
        return metadata, text_content_early
        
    meta = meta_elements[0]

    if hasattr(meta, 'getAttribute'):
        field_mapping = {
            'author': 'creator',
            'title': 'title',
            'subject': 'subject',
            'generator': 'generator',
            'language': 'language'
        }
        extract_common_metadata_fields(meta, metadata, field_mapping)
        extract_and_parse_keywords(meta, metadata, 'keyword')

    if hasattr(meta, 'statistics'):
        stats = meta.statistics
        field_mapping = {
            'num_pages': 'page-count',
            'word_count': 'word-count',
            'character_count': 'character-count',
            'paragraph_count': 'paragraph-count'
        }
        stats_data = extract_statistics_from_meta(stats, field_mapping)
        metadata.update(stats_data)

    text_content = _extract_text_content(doc)
    return metadata, text_content


def extract_opendocument_metadata(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and text from an OpenDocument file.

    Args:
        path: Path to the OpenDocument file

    Returns:
        tuple[dict[str, Any], str | None]: Specific OpenDocument metadata and text content.
    """
    # File existence validation is handled by the factory
    extension = get_file_extension(path)

    if extension == '.odt':
        return _extract_with_odt(path)
    elif extension == '.ods':
        return _extract_with_ods(path)
    elif extension == '.odp':
        return _extract_with_odp(path)
    else:
        # Should not happen if called via registered extensions
        logger.warning(f"Unsupported OpenDocument file type for explicit extraction: {path}")
        return create_opendocument_metadata(), None
