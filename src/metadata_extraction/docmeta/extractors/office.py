"""
Microsoft Office Metadata Extractor

This module provides functionality to extract metadata from Microsoft Office files.
Supports DOCX, XLSX, and PPTX formats with comprehensive metadata extraction.
"""

import logging
import os
from datetime import datetime

# Import required libraries for Office document processing
import docx
from openpyxl import load_workbook
from pptx import Presentation

from docmeta.core.types import OfficeMetaData, create_office_metadata
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


def _extract_with_docx(path: str) -> OfficeMetaData:
    """
    Extract metadata from a DOCX file using python-docx.

    Args:
        path: Path to the DOCX file

    Returns:
        OfficeMetaData: Metadata for the DOCX file
    """
    # Initialize metadata with common file properties and defaults
    office_metadata = create_office_metadata(path)

    doc = docx.Document(path)
    core_properties = doc.core_properties

    # Extract document metadata
    office_metadata["author"] = getattr(core_properties, 'author', None)
    office_metadata["title"] = getattr(core_properties, 'title', None)
    office_metadata["subject"] = getattr(core_properties, 'subject', None)
    office_metadata["last_modified_by"] = getattr(core_properties, 'last_modified_by', None)

    # Handle creation and modification times
    if hasattr(core_properties, 'created') and core_properties.created:
        office_metadata["created"] = core_properties.created
    if hasattr(core_properties, 'modified') and core_properties.modified:
        office_metadata["modified"] = core_properties.modified

    # Handle keywords
    keywords = getattr(core_properties, 'keywords', None)
    if keywords and isinstance(keywords, str):
        office_metadata["embedded_keywords"] = _parse_keywords(keywords)

    # Set application info
    office_metadata["application"] = "Microsoft Word"

    # Count paragraphs, words, etc.
    office_metadata["paragraph_count"] = len(doc.paragraphs)

    word_count = 0
    char_count = 0
    all_text = []
    for para in doc.paragraphs:
        text = para.text
        words = text.split()
        word_count += len(words)
        char_count += len(text)
        if text.strip():  # Only add non-empty text for token counting
            all_text.append(text)

    office_metadata["word_count"] = word_count
    office_metadata["character_count"] = char_count

    # Count tokens
    if all_text:
        full_text = '\n'.join(all_text)
        office_metadata["token_count"] = count_tokens(full_text)

    # Count pages (approximate)
    # A rough estimate: ~500 words per page for standard documents
    if word_count > 0:
        office_metadata["num_pages"] = max(1, word_count // 500)

    return office_metadata


def _extract_with_xlsx(path: str) -> OfficeMetaData:
    """
    Extract metadata from an XLSX file using openpyxl.

    Args:
        path: Path to the XLSX file

    Returns:
        OfficeMetaData: Metadata for the XLSX file
    """
    # Initialize metadata with common file properties and defaults
    office_metadata = create_office_metadata(path)

    workbook = load_workbook(path, read_only=True)
    properties = workbook.properties

    # Extract document metadata
    office_metadata["author"] = getattr(properties, 'creator', None)
    office_metadata["title"] = getattr(properties, 'title', None)
    office_metadata["subject"] = getattr(properties, 'subject', None)
    office_metadata["last_modified_by"] = getattr(properties, 'lastModifiedBy', None)

    # Handle creation and modification times
    if hasattr(properties, 'created') and properties.created:
        office_metadata["created"] = properties.created
    if hasattr(properties, 'modified') and properties.modified:
        office_metadata["modified"] = properties.modified

    # Handle keywords
    keywords = getattr(properties, 'keywords', None)
    if keywords and isinstance(keywords, str):
        office_metadata["embedded_keywords"] = _parse_keywords(keywords)

    # Set application info
    office_metadata["application"] = "Microsoft Excel"

    # Count sheets and estimate content
    office_metadata["num_sheets"] = len(workbook.worksheets)

    # Count cells with data across all sheets
    total_cells = 0
    all_text = []
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value is not None:
                    total_cells += 1
                    cell_text = str(cell.value)
                    if isinstance(cell.value, str):
                        office_metadata["character_count"] += len(cell_text)
                        if cell_text.strip():  # Only add non-empty text for token counting
                            all_text.append(cell_text)

    office_metadata["word_count"] = total_cells  # Use cell count as word equivalent

    # Count tokens
    if all_text:
        full_text = '\n'.join(all_text)
        office_metadata["token_count"] = count_tokens(full_text)

    workbook.close()
    return office_metadata


def _extract_with_pptx(path: str) -> OfficeMetaData:
    """
    Extract metadata from a PPTX file using python-pptx.

    Args:
        path: Path to the PPTX file

    Returns:
        OfficeMetaData: Metadata for the PPTX file
    """
    # Initialize metadata with common file properties and defaults
    office_metadata = create_office_metadata(path)

    presentation = Presentation(path)
    core_properties = presentation.core_properties

    # Extract document metadata
    office_metadata["author"] = getattr(core_properties, 'author', None)
    office_metadata["title"] = getattr(core_properties, 'title', None)
    office_metadata["subject"] = getattr(core_properties, 'subject', None)
    office_metadata["last_modified_by"] = getattr(core_properties, 'last_modified_by', None)

    # Handle creation and modification times
    if hasattr(core_properties, 'created') and core_properties.created:
        office_metadata["created"] = core_properties.created
    if hasattr(core_properties, 'modified') and core_properties.modified:
        office_metadata["modified"] = core_properties.modified

    # Handle keywords
    keywords = getattr(core_properties, 'keywords', None)
    if keywords and isinstance(keywords, str):
        office_metadata["embedded_keywords"] = _parse_keywords(keywords)

    # Set application info
    office_metadata["application"] = "Microsoft PowerPoint"

    # Count slides and content
    office_metadata["num_slides"] = len(presentation.slides)
    office_metadata["num_pages"] = len(presentation.slides)  # Slides are equivalent to pages

    word_count = 0
    char_count = 0
    all_text = []
    for slide in presentation.slides:
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text:
                text = shape.text
                words = text.split()
                word_count += len(words)
                char_count += len(text)
                if text.strip():  # Only add non-empty text for token counting
                    all_text.append(text)

    office_metadata["word_count"] = word_count
    office_metadata["character_count"] = char_count

    # Count tokens
    if all_text:
        full_text = '\n'.join(all_text)
        office_metadata["token_count"] = count_tokens(full_text)

    return office_metadata


def extract_office_metadata(path: str) -> OfficeMetaData:
    """
    Extract metadata from a Microsoft Office file.

    Args:
        path: Path to the Office file

    Returns:
        OfficeMetaData: Metadata for the Office file
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    # Get file extension to determine extraction method
    _, extension = os.path.splitext(path)
    extension = extension.lower()

    # Extract metadata based on file type
    if extension == '.docx':
        return _extract_with_docx(path)
    elif extension == '.xlsx':
        return _extract_with_xlsx(path)
    elif extension == '.pptx':
        return _extract_with_pptx(path)
    else:
        # For unsupported Office types, return basic metadata
        return create_office_metadata(path)
