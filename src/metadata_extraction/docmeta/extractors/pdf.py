"""
PDF Metadata Extractor

This module provides functionality to extract metadata from PDF files.
Includes token counting using tiktoken for LLM context estimation.
"""

import logging
import os
from typing import cast

# Import required libraries
from PyPDF2 import PdfReader
import fitz  # PyMuPDF



from docmeta.core.common import get_file_common_metadata
from docmeta.core.types import PDFMetaData
from docmeta.utils import extract_keywords_tfidf
from docmeta.utils import count_tokens

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


def _initialize_pdf_metadata(path: str) -> PDFMetaData:
    """
    Initialize PDF metadata with common file properties and default values.

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


def _extract_text_chunks_pymupdf(doc: fitz.Document):
    """
    Generator that yields text content one page at a time from PyMuPDF document.
    Streaming approach to avoid memory issues with large PDFs.

    Args:
        doc: PyMuPDF document object

    Yields:
        str: Text content of each page
    """
    for page_num in range(doc.page_count):
        page = doc[page_num]
        page_text = page.get_text()
        if page_text:
            yield page_text


def _extract_text_chunks_pypdf2(reader: PdfReader):
    """
    Generator that yields text content one page at a time from PyPDF2 reader.
    Streaming approach to avoid memory issues with large PDFs.

    Args:
        reader: PyPDF2 PdfReader object

    Yields:
        str: Text content of each page
    """
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            yield page_text


def _extract_with_pymupdf(path: str) -> tuple[PDFMetaData, list[str] | None]:
    """
    Extract metadata and text from a PDF file using PyMuPDF (preferred method).

    Args:
        path: Path to the PDF file

    Returns:
        tuple[PDFMetaData, list[str] | None]: Metadata and text chunks (if any)
    """
    # Initialize metadata with common file properties and defaults
    pdf_metadata = _initialize_pdf_metadata(path)

    with fitz.open(path) as doc:
        # Extract metadata
        pdf_metadata["num_pages"] = doc.page_count
        
        # Get page size from first page
        if doc.page_count > 0:
            page = doc[0]
            rect = page.rect
            pdf_metadata["page_width"] = rect.width
            pdf_metadata["page_height"] = rect.height

        # Extract document metadata
        metadata = doc.metadata
        pdf_metadata["author"] = metadata.get('author')
        pdf_metadata["creator"] = metadata.get('creator')
        pdf_metadata["producer"] = metadata.get('producer')
        pdf_metadata["subject"] = metadata.get('subject')
        pdf_metadata["title"] = metadata.get('title')

        # Handle keywords
        keywords = metadata.get('keywords')
        if keywords and isinstance(keywords, str):
            pdf_metadata["embedded_keywords"] = _parse_keywords(keywords)

        # Extract text as chunks - streaming to avoid memory issues with large PDFs
        text_chunks = list(_extract_text_chunks_pymupdf(doc))
    
    return pdf_metadata, text_chunks if text_chunks else None


def _extract_with_pypdf2_fallback(path: str) -> tuple[PDFMetaData, list[str] | None]:
    """
    Extract metadata and text using PyPDF2 as fallback when PyMuPDF fails.

    Args:
        path: Path to the PDF file

    Returns:
        tuple[PDFMetaData, list[str] | None]: Metadata and text chunks (if any)
    """
    # Initialize metadata with common file properties and defaults
    pdf_metadata = _initialize_pdf_metadata(path)

    with open(path, 'rb') as file:
        reader = PdfReader(file)

        # Extract metadata
        pdf_metadata["num_pages"] = len(reader.pages)
        pdf_metadata["encrypted"] = reader.is_encrypted

        # Get page size from first page
        if reader.pages:
            page = reader.pages[0]
            if hasattr(page, 'mediabox'):
                pdf_metadata["page_width"] = float(page.mediabox.width)
                pdf_metadata["page_height"] = float(page.mediabox.height)

        # Extract document info
        if reader.metadata:
            metadata = reader.metadata
            # Use .get() for consistency with PyMuPDF (DocumentInformation inherits from dict)
            pdf_metadata["author"] = metadata.get('author')
            pdf_metadata["creator"] = metadata.get('creator')
            pdf_metadata["producer"] = metadata.get('producer')
            pdf_metadata["subject"] = metadata.get('subject')
            pdf_metadata["title"] = metadata.get('title')
            
            # Handle keywords
            keywords = metadata.get('keywords')
            if keywords and isinstance(keywords, str):
                pdf_metadata["embedded_keywords"] = _parse_keywords(keywords)

        # Extract text as chunks - streaming to avoid memory issues with large PDFs
        text_chunks = list(_extract_text_chunks_pypdf2(reader))

    return pdf_metadata, text_chunks if text_chunks else None


def extract_pdf_metadata(path: str, count_tokens_flag: bool = False, extract_keywords_flag: bool = False) -> PDFMetaData:
    """
    Extract metadata from a PDF file.

    Args:
        path: Path to the PDF file
        count_tokens_flag: Whether to count tokens in the PDF text (default: False)
        extract_keywords_flag: Whether to extract keywords from PDF text (default: False)

    Returns:
        PDFMetaData: Metadata for the PDF file
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    # Try PyMuPDF first (preferred method)
    try:
        pdf_metadata, text_chunks = _extract_with_pymupdf(path)
    except Exception as e:
        # Fallback to PyPDF2 for problematic PDFs
        logger.warning("PyMuPDF failed for %s, falling back to PyPDF2: %s", path, str(e))
        pdf_metadata, text_chunks = _extract_with_pypdf2_fallback(path)

    # Process text if needed and available
    if text_chunks and (count_tokens_flag or extract_keywords_flag):
        if count_tokens_flag:
            # Streaming token counting to avoid memory issues with large PDFs
            pdf_metadata["token_count"] = count_tokens(text_chunks)
        
        if extract_keywords_flag:
            # Keyword extraction requires full text (TF-IDF needs complete corpus)
            full_text = "\n\n".join(text_chunks)
            pdf_metadata["extracted_keywords"] = extract_keywords_tfidf(full_text)

    return cast(PDFMetaData, pdf_metadata)
