"""
PDF Metadata Extractor

This module provides functionality to extract metadata from PDF files.
Includes token counting using tiktoken for LLM context estimation.
"""

import logging
from typing import Any

import fitz  # PyMuPDF
from PyPDF2 import PdfReader

from docmeta.core.defaults import (
    create_pdf_metadata,  # create_pdf_metadata returns dict[str, Any]
)
from docmeta.utils.text_processing import parse_keywords  # Keep for embedded keywords

# Configure logger
logger = logging.getLogger(__name__)


def _extract_text_pymupdf(doc: fitz.Document) -> str | None:
    """
    Extract full text content.

    Args:
        doc: PyMuPDF document object

    Returns:
        str | None: Full text content or None if no text
    """
    text_parts = []
    for page_num in range(doc.page_count):
        page = doc[page_num]
        page_text = page.get_text()
        if page_text:
            text_parts.append(page_text)

    return "\n\n".join(text_parts) if text_parts else None


def _extract_text_pypdf2(reader: PdfReader) -> str | None:
    """
    Extract full text content.

    Args:
        reader: PyPDF2 PdfReader object

    Returns:
        str | None: Full text content or None if no text
    """
    text_parts = []
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text_parts.append(page_text)

    return "\n\n".join(text_parts) if text_parts else None


def _extract_with_pymupdf(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and text from a PDF file.

    Args:
        path: Path to the PDF file

    Returns:
        tuple[dict[str, Any], str | None]: Specific PDF metadata and text content (if any)
    """
    metadata = create_pdf_metadata()

    with fitz.open(path) as doc:
        metadata["num_pages"] = doc.page_count

        if doc.page_count > 0:
            page = doc[0]
            rect = page.rect
            metadata["page_width"] = rect.width
            metadata["page_height"] = rect.height

        doc_meta = doc.metadata
        metadata["author"] = doc_meta.get("author")
        metadata["creator"] = doc_meta.get("creator")
        metadata["producer"] = doc_meta.get("producer")
        metadata["subject"] = doc_meta.get("subject")
        metadata["title"] = doc_meta.get("title")

        keywords = doc_meta.get("keywords")
        if keywords and isinstance(keywords, str):
            metadata["embedded_keywords"] = parse_keywords(keywords)

        text_content = _extract_text_pymupdf(doc)

    return metadata, text_content


def _extract_with_pypdf2_fallback(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and text using PyPDF2.

    Args:
        path: Path to the PDF file

    Returns:
        tuple[dict[str, Any], str | None]: Specific PDF metadata and text content (if any)
    """
    metadata = create_pdf_metadata()

    with open(path, "rb") as file:
        reader = PdfReader(file)

        metadata["num_pages"] = len(reader.pages)
        metadata["encrypted"] = reader.is_encrypted

        if reader.pages:
            page = reader.pages[0]
            if hasattr(page, "mediabox"):
                metadata["page_width"] = float(page.mediabox.width)
                metadata["page_height"] = float(page.mediabox.height)

        if reader.metadata:
            reader_meta = reader.metadata
            metadata["author"] = reader_meta.get("/Author")
            metadata["creator"] = reader_meta.get("/Creator")
            metadata["producer"] = reader_meta.get("/Producer")
            metadata["subject"] = reader_meta.get("/Subject")
            metadata["title"] = reader_meta.get("/Title")

            keywords = reader_meta.get("/Keywords")
            if keywords and isinstance(keywords, str):
                metadata["embedded_keywords"] = parse_keywords(keywords)

        text_content = _extract_text_pypdf2(reader)

    return metadata, text_content


def extract_pdf_metadata(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and text content from a PDF file.
    Tries PyMuPDF first, then falls back to PyPDF2.

    Args:
        path: Path to the PDF file

    Returns:
        tuple[dict[str, Any], str | None]: Specific PDF metadata and text content.
    """
    try:
        metadata, text_content = _extract_with_pymupdf(path)
    except (
        fitz.FileDataError,
        fitz.FileNotFoundError,
        fitz.EmptyFileError,
        Exception,
    ) as e:  # Broaden for other fitz issues
        logger.warning(f"PyMuPDF failed for {path}, falling back to PyPDF2: {e}")
        metadata, text_content = _extract_with_pypdf2_fallback(path)

    return metadata, text_content
