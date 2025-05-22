"""
Document Metadata Extractor

This module provides functionality to extract metadata from document files (docx, odt, etc.).
"""

import os
from datetime import datetime
from typing import Any, cast

# Try to import docx library for Word documents
try:
    import docx
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

# Try to import odf library for OpenDocument files
try:
    from odf import opendocument
    from odf.meta import Meta
    ODF_AVAILABLE = True
except ImportError:
    ODF_AVAILABLE = False

from docmeta.core.common import get_file_common_metadata
from docmeta.core.types import DocumentMetaData


def extract_docx_metadata(path: str) -> dict[str, Any]:
    """
    Extract metadata from a DOCX file.

    Args:
        path: Path to the DOCX file

    Returns:
        dict[str, Any]: Metadata for the DOCX file
    """
    metadata: dict[str, Any] = {}

    if not DOCX_AVAILABLE:
        return metadata

    try:
        doc = docx.Document(path)
        core_properties = doc.core_properties

        # Extract metadata from core properties
        if hasattr(core_properties, 'author') and core_properties.author:
            metadata["author"] = core_properties.author

        if hasattr(core_properties, 'title') and core_properties.title:
            metadata["title"] = core_properties.title

        if hasattr(core_properties, 'subject') and core_properties.subject:
            metadata["subject"] = core_properties.subject

        if hasattr(core_properties, 'keywords') and core_properties.keywords:
            keywords = core_properties.keywords
            if isinstance(keywords, str):
                if ',' in keywords:
                    metadata["embedded_keywords"] = [k.strip() for k in keywords.split(',')]
                elif ';' in keywords:
                    metadata["embedded_keywords"] = [k.strip() for k in keywords.split(';')]
                else:
                    metadata["embedded_keywords"] = [keywords.strip()]

        if hasattr(core_properties, 'created') and core_properties.created:
            metadata["creation_time"] = core_properties.created

        if hasattr(core_properties, 'modified') and core_properties.modified:
            metadata["modified"] = core_properties.modified

        if hasattr(core_properties, 'last_modified_by') and core_properties.last_modified_by:
            metadata["last_modified_by"] = core_properties.last_modified_by

        # Count paragraphs, words, etc.
        metadata["paragraph_count"] = len(doc.paragraphs)

        word_count = 0
        char_count = 0
        for para in doc.paragraphs:
            text = para.text
            words = text.split()
            word_count += len(words)
            char_count += len(text)

        metadata["word_count"] = word_count
        metadata["character_count"] = char_count

        # Count pages (approximate)
        # A rough estimate: ~500 words per page for standard documents
        if word_count > 0:
            metadata["num_pages"] = max(1, word_count // 500)

    except Exception as e:
        print(f"Error extracting DOCX metadata: {e}")

    return metadata


def extract_odt_metadata(path: str) -> dict[str, Any]:
    """
    Extract metadata from an ODT file.

    Args:
        path: Path to the ODT file

    Returns:
        dict[str, Any]: Metadata for the ODT file
    """
    metadata: dict[str, Any] = {}

    if not ODF_AVAILABLE:
        return metadata

    try:
        doc = opendocument.load(path)
        meta = doc.getElementsByType(Meta)[0]

        # Extract metadata
        if hasattr(meta, 'getAttribute') and meta.getAttribute('creator'):
            metadata["author"] = meta.getAttribute('creator')

        if hasattr(meta, 'getAttribute') and meta.getAttribute('title'):
            metadata["title"] = meta.getAttribute('title')

        if hasattr(meta, 'getAttribute') and meta.getAttribute('subject'):
            metadata["subject"] = meta.getAttribute('subject')

        if hasattr(meta, 'getAttribute') and meta.getAttribute('keyword'):
            keywords = meta.getAttribute('keyword')
            if isinstance(keywords, str):
                if ',' in keywords:
                    metadata["embedded_keywords"] = [k.strip() for k in keywords.split(',')]
                elif ';' in keywords:
                    metadata["embedded_keywords"] = [k.strip() for k in keywords.split(';')]
                else:
                    metadata["embedded_keywords"] = [keywords.strip()]

        if hasattr(meta, 'getAttribute') and meta.getAttribute('creation-date'):
            creation_date = meta.getAttribute('creation-date')
            if creation_date:
                metadata["creation_time"] = datetime.fromisoformat(creation_date)

        if hasattr(meta, 'getAttribute') and meta.getAttribute('date'):
            modified_date = meta.getAttribute('date')
            if modified_date:
                metadata["modified"] = datetime.fromisoformat(modified_date)

        # Statistics are usually stored in meta.statistics
        if hasattr(meta, 'statistics'):
            stats = meta.statistics
            if hasattr(stats, 'getAttribute'):
                if stats.getAttribute('page-count'):
                    metadata["num_pages"] = int(stats.getAttribute('page-count'))

                if stats.getAttribute('word-count'):
                    metadata["word_count"] = int(stats.getAttribute('word-count'))

                if stats.getAttribute('character-count'):
                    metadata["character_count"] = int(stats.getAttribute('character-count'))

                if stats.getAttribute('paragraph-count'):
                    metadata["paragraph_count"] = int(stats.getAttribute('paragraph-count'))

    except Exception as e:
        print(f"Error extracting ODT metadata: {e}")

    return metadata


def extract_document_metadata(path: str) -> DocumentMetaData:
    """
    Extract metadata from a document file.

    Args:
        path: Path to the document file

    Returns:
        DocumentMetaData: Metadata for the document file
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    # Get common metadata
    common_metadata = get_file_common_metadata(path)

    # Initialize document-specific metadata with default values
    doc_metadata: dict[str, Any] = {
        **common_metadata,
        "author": None,
        "title": None,
        "subject": None,
        "embedded_keywords": None,
        "extracted_keywords": None,
        "modified": None,
        "last_modified_by": None,
        "num_pages": None,  # None for formats that don't have a native page concept
        "word_count": 0,
        "character_count": 0,
        "paragraph_count": 0,
        "line_count": 0,
    }

    # Extract metadata based on file extension
    file_extension = common_metadata["file_extension"].lower()

    if file_extension == '.docx':
        docx_metadata = extract_docx_metadata(path)
        doc_metadata.update(docx_metadata)

    elif file_extension in ['.odt', '.ods', '.odp']:
        odt_metadata = extract_odt_metadata(path)
        doc_metadata.update(odt_metadata)

    # For plain text files, we can count words, characters, etc.
    elif file_extension in ['.txt', '.md', '.csv', '.json', '.xml', '.html', '.htm']:
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()

                # Count words, characters, paragraphs, and lines
                lines = content.splitlines()
                paragraphs = [p for p in content.split('\n\n') if p.strip()]
                words = content.split()

                doc_metadata["word_count"] = len(words)
                doc_metadata["character_count"] = len(content)
                doc_metadata["paragraph_count"] = len(paragraphs)
                doc_metadata["line_count"] = len(lines)

                # Plain text files don't have a native page concept
                doc_metadata["num_pages"] = None
        except Exception as e:
            print(f"Error extracting text file metadata: {e}")

    return cast(DocumentMetaData, doc_metadata)
