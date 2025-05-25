"""
OpenDocument Metadata Extractor

This module provides functionality to extract metadata from OpenDocument files.
Supports ODT, ODS, and ODP formats with comprehensive metadata extraction.
"""

import logging
import os
from datetime import datetime

# Import required libraries for OpenDocument processing
from odf import opendocument
from odf.opendocument import Meta

from docmeta.core.types import OpenDocumentMetaData, create_opendocument_metadata
from docmeta.utils.token_counter import count_tokens

# Configure logger
logger = logging.getLogger(__name__)


def _parse_keywords(keywords_str: str) -> list[str]:
    """
    Parse keywords string into a list of keywords.

    Args:
        keywords_str: String containing keywords

    Returns:
        list[str]: List of keywords
    """
    if not keywords_str:
        return []

    if ',' in keywords_str:
        return [k.strip() for k in keywords_str.split(',')]
    elif ';' in keywords_str:
        return [k.strip() for k in keywords_str.split(';')]
    else:
        return [keywords_str.strip()]


def _extract_text_content(doc) -> str:
    """
    Extract all text content from an OpenDocument.

    Args:
        doc: OpenDocument object

    Returns:
        str: Extracted text content
    """
    from odf.text import P, H, Span

    text_elements = []

    # Extract paragraphs and headings
    for element in doc.getElementsByType(P):
        if hasattr(element, 'data') and element.data:
            text_elements.append(element.data)

    for element in doc.getElementsByType(H):
        if hasattr(element, 'data') and element.data:
            text_elements.append(element.data)

    for element in doc.getElementsByType(Span):
        if hasattr(element, 'data') and element.data:
            text_elements.append(element.data)

    return '\n'.join(text_elements)


def _extract_with_odt(path: str) -> OpenDocumentMetaData:
    """
    Extract metadata from an ODT file using odfpy.

    Args:
        path: Path to the ODT file

    Returns:
        OpenDocumentMetaData: Metadata for the ODT file
    """
    # Initialize metadata with common file properties and defaults
    odt_metadata = create_opendocument_metadata(path)

    doc = opendocument.load(path)
    meta = doc.getElementsByType(Meta)[0]

    # Extract document metadata
    if hasattr(meta, 'getAttribute'):
        odt_metadata["author"] = meta.getAttribute('creator')
        odt_metadata["title"] = meta.getAttribute('title')
        odt_metadata["subject"] = meta.getAttribute('subject')
        odt_metadata["generator"] = meta.getAttribute('generator')
        odt_metadata["language"] = meta.getAttribute('language')

        # Handle keywords
        keywords = meta.getAttribute('keyword')
        if keywords and isinstance(keywords, str):
            odt_metadata["embedded_keywords"] = _parse_keywords(keywords)

        # Handle creation and modification times
        creation_date = meta.getAttribute('creation-date')
        if creation_date:
            odt_metadata["created"] = datetime.fromisoformat(creation_date)

        modified_date = meta.getAttribute('date')
        if modified_date:
            odt_metadata["modified"] = datetime.fromisoformat(modified_date)

    # Extract statistics if available
    if hasattr(meta, 'statistics'):
        stats = meta.statistics
        if hasattr(stats, 'getAttribute'):
            page_count = stats.getAttribute('page-count')
            if page_count:
                odt_metadata["num_pages"] = int(page_count)

            word_count = stats.getAttribute('word-count')
            if word_count:
                odt_metadata["word_count"] = int(word_count)

            char_count = stats.getAttribute('character-count')
            if char_count:
                odt_metadata["character_count"] = int(char_count)

            para_count = stats.getAttribute('paragraph-count')
            if para_count:
                odt_metadata["paragraph_count"] = int(para_count)

    # Extract text content for token counting
    text_content = _extract_text_content(doc)
    if text_content.strip():
        odt_metadata["token_count"] = count_tokens(text_content)

    return odt_metadata


def _extract_with_ods(path: str) -> OpenDocumentMetaData:
    """
    Extract metadata from an ODS file using odfpy.

    Args:
        path: Path to the ODS file

    Returns:
        OpenDocumentMetaData: Metadata for the ODS file
    """
    # Initialize metadata with common file properties and defaults
    ods_metadata = create_opendocument_metadata(path)

    doc = opendocument.load(path)
    meta = doc.getElementsByType(Meta)[0]

    # Extract document metadata
    if hasattr(meta, 'getAttribute'):
        ods_metadata["author"] = meta.getAttribute('creator')
        ods_metadata["title"] = meta.getAttribute('title')
        ods_metadata["subject"] = meta.getAttribute('subject')
        ods_metadata["generator"] = meta.getAttribute('generator')
        ods_metadata["language"] = meta.getAttribute('language')

        # Handle keywords
        keywords = meta.getAttribute('keyword')
        if keywords and isinstance(keywords, str):
            ods_metadata["embedded_keywords"] = _parse_keywords(keywords)

        # Handle creation and modification times
        creation_date = meta.getAttribute('creation-date')
        if creation_date:
            ods_metadata["created"] = datetime.fromisoformat(creation_date)

        modified_date = meta.getAttribute('date')
        if modified_date:
            ods_metadata["modified"] = datetime.fromisoformat(modified_date)

    # Extract statistics if available
    if hasattr(meta, 'statistics'):
        stats = meta.statistics
        if hasattr(stats, 'getAttribute'):
            # For spreadsheets, use table count as page equivalent
            table_count = stats.getAttribute('table-count')
            if table_count:
                ods_metadata["num_pages"] = int(table_count)

            cell_count = stats.getAttribute('cell-count')
            if cell_count:
                ods_metadata["word_count"] = int(cell_count)  # Use cell count as word equivalent

            char_count = stats.getAttribute('character-count')
            if char_count:
                ods_metadata["character_count"] = int(char_count)

    # Extract text content for token counting
    text_content = _extract_text_content(doc)
    if text_content.strip():
        ods_metadata["token_count"] = count_tokens(text_content)

    return ods_metadata


def _extract_with_odp(path: str) -> OpenDocumentMetaData:
    """
    Extract metadata from an ODP file using odfpy.

    Args:
        path: Path to the ODP file

    Returns:
        OpenDocumentMetaData: Metadata for the ODP file
    """
    # Initialize metadata with common file properties and defaults
    odp_metadata = create_opendocument_metadata(path)

    doc = opendocument.load(path)
    meta = doc.getElementsByType(Meta)[0]

    # Extract document metadata
    if hasattr(meta, 'getAttribute'):
        odp_metadata["author"] = meta.getAttribute('creator')
        odp_metadata["title"] = meta.getAttribute('title')
        odp_metadata["subject"] = meta.getAttribute('subject')
        odp_metadata["generator"] = meta.getAttribute('generator')
        odp_metadata["language"] = meta.getAttribute('language')

        # Handle keywords
        keywords = meta.getAttribute('keyword')
        if keywords and isinstance(keywords, str):
            odp_metadata["embedded_keywords"] = _parse_keywords(keywords)

        # Handle creation and modification times
        creation_date = meta.getAttribute('creation-date')
        if creation_date:
            odp_metadata["created"] = datetime.fromisoformat(creation_date)

        modified_date = meta.getAttribute('date')
        if modified_date:
            odp_metadata["modified"] = datetime.fromisoformat(modified_date)

    # Extract statistics if available
    if hasattr(meta, 'statistics'):
        stats = meta.statistics
        if hasattr(stats, 'getAttribute'):
            # For presentations, use page count as slide count
            page_count = stats.getAttribute('page-count')
            if page_count:
                odp_metadata["num_pages"] = int(page_count)

            word_count = stats.getAttribute('word-count')
            if word_count:
                odp_metadata["word_count"] = int(word_count)

            char_count = stats.getAttribute('character-count')
            if char_count:
                odp_metadata["character_count"] = int(char_count)

            para_count = stats.getAttribute('paragraph-count')
            if para_count:
                odp_metadata["paragraph_count"] = int(para_count)

    # Extract text content for token counting
    text_content = _extract_text_content(doc)
    if text_content.strip():
        odp_metadata["token_count"] = count_tokens(text_content)

    return odp_metadata


def extract_opendocument_metadata(path: str) -> OpenDocumentMetaData:
    """
    Extract metadata from an OpenDocument file.

    Args:
        path: Path to the OpenDocument file

    Returns:
        OpenDocumentMetaData: Metadata for the OpenDocument file
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    # Get file extension to determine extraction method
    _, extension = os.path.splitext(path)
    extension = extension.lower()

    # Extract metadata based on file type
    if extension == '.odt':
        return _extract_with_odt(path)
    elif extension == '.ods':
        return _extract_with_ods(path)
    elif extension == '.odp':
        return _extract_with_odp(path)
    else:
        # For unsupported OpenDocument types, return basic metadata
        return create_opendocument_metadata(path)
