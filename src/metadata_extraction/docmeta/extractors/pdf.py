"""
PDF Metadata Extractor

This module provides functionality to extract metadata from PDF files.
Includes token counting using tiktoken for LLM context estimation.
"""

import os
import re
from typing import Any, cast

# Import required libraries (assumed to be pre-installed in the container)
from PyPDF2 import PdfReader
import fitz  # PyMuPDF
import tiktoken

# Default encoding for token counting
DEFAULT_ENCODING = "cl100k_base"  # ChatGPT, GPT-4

from docmeta.core.common import get_file_common_metadata
from docmeta.core.types import PDFMetaData
from docmeta.utils.keyword_extractor import extract_keywords_tfidf


def count_tokens(text: str, base: str = DEFAULT_ENCODING) -> int:
    """
    Count tokens in text using the specified tiktoken encoding.

    Args:
        text: Text to count tokens in
        base: Encoding to use (default: cl100k_base, used by ChatGPT and GPT-4)

    Returns:
        int: Token count
    """
    if not text:
        return 0

    # Clean the text - remove excessive whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    # Count tokens using the specified encoding
    encoding = tiktoken.get_encoding(base)
    return len(encoding.encode(text))


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

    # Get common metadata
    common_metadata = get_file_common_metadata(path)

    # Initialize PDF-specific metadata with default values
    pdf_metadata: dict[str, Any] = {
        **common_metadata,
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

    # Extracted text will be stored here to be used by token counter and keyword extractor
    full_text_content: str | None = None

    # First, try to extract metadata using PyPDF2
    try:
        with open(path, 'rb') as file:
            reader = PdfReader(file)

            # Get number of pages
            pdf_metadata["num_pages"] = len(reader.pages)

            # Check if the PDF is encrypted
            pdf_metadata["encrypted"] = reader.is_encrypted

            # Get page size from the first page
            if reader.pages and len(reader.pages) > 0:
                page = reader.pages[0]
                if hasattr(page, 'mediabox'):
                    pdf_metadata["page_width"] = float(page.mediabox.width)
                    pdf_metadata["page_height"] = float(page.mediabox.height)

            # Extract document info if available
            if reader.metadata:
                info = reader.metadata

                # Get metadata using attribute access (PyPDF2 3.x style)
                if hasattr(info, 'author') and info.author:
                    pdf_metadata["author"] = info.author

                if hasattr(info, 'creator') and info.creator:
                    pdf_metadata["creator"] = info.creator

                if hasattr(info, 'producer') and info.producer:
                    pdf_metadata["producer"] = info.producer

                if hasattr(info, 'subject') and info.subject:
                    pdf_metadata["subject"] = info.subject

                if hasattr(info, 'title') and info.title:
                    pdf_metadata["title"] = info.title

                if hasattr(info, 'keywords') and info.keywords:
                    # Split keywords by comma or semicolon
                    keywords = info.keywords
                    if isinstance(keywords, str):
                        if ',' in keywords:
                            pdf_metadata["embedded_keywords"] = [k.strip() for k in keywords.split(',')]
                        elif ';' in keywords:
                            pdf_metadata["embedded_keywords"] = [k.strip() for k in keywords.split(';')]
                        else:
                            pdf_metadata["embedded_keywords"] = [keywords.strip()]

                # Try dictionary access as well (for older PyPDF2 versions)
                try:
                    for key, attr in [
                        ('/Author', 'author'),
                        ('/Creator', 'creator'),
                        ('/Producer', 'producer'),
                        ('/Subject', 'subject'),
                        ('/Title', 'title'),
                        ('/Keywords', 'embedded_keywords')
                    ]:
                        if key in info and info[key] and not pdf_metadata.get(attr):
                            value = info[key]
                            if attr == 'embedded_keywords' and isinstance(value, str):
                                if ',' in value:
                                    pdf_metadata[attr] = [k.strip() for k in value.split(',')]
                                elif ';' in value:
                                    pdf_metadata[attr] = [k.strip() for k in value.split(';')]
                                else:
                                    pdf_metadata[attr] = [value.strip()]
                            else:
                                pdf_metadata[attr] = value
                except:
                    # Dictionary access might not work for all PyPDF2 versions
                    pass
    except Exception as e:
        print(f"Error extracting metadata with PyPDF2: {e}")

    # Then, try to extract metadata using PyMuPDF (which often provides better results)
    try:
        doc = fitz.open(path)

        # Get number of pages
        pdf_metadata["num_pages"] = doc.page_count

        # Get page size
        if doc.page_count > 0:
            page = doc[0]
            rect = page.rect
            pdf_metadata["page_width"] = rect.width
            pdf_metadata["page_height"] = rect.height

        # Get metadata
        metadata = doc.metadata

        # Extract all available metadata
        if metadata.get('author'):
            pdf_metadata["author"] = metadata.get('author')

        if metadata.get('creator'):
            pdf_metadata["creator"] = metadata.get('creator')

        if metadata.get('producer'):
            pdf_metadata["producer"] = metadata.get('producer')

        if metadata.get('subject'):
            pdf_metadata["subject"] = metadata.get('subject')

        if metadata.get('title'):
            pdf_metadata["title"] = metadata.get('title')

        if metadata.get('keywords'):
            keywords = metadata.get('keywords', '')
            if isinstance(keywords, str):
                if ',' in keywords:
                    pdf_metadata["embedded_keywords"] = [k.strip() for k in keywords.split(',')]
                elif ';' in keywords:
                    pdf_metadata["embedded_keywords"] = [k.strip() for k in keywords.split(';')]
                else:
                    pdf_metadata["embedded_keywords"] = [keywords.strip()]

        # Extract text and count tokens if requested
        if count_tokens_flag or extract_keywords_flag:
            try:
                # Extract text from all pages
                extracted_text_pymupdf = ""
                for page_num in range(doc.page_count):
                    page = doc[page_num]
                    page_text = page.get_text()
                    extracted_text_pymupdf += page_text + "\n\n"
                full_text_content = extracted_text_pymupdf.strip()

            except Exception as e:
                print(f"Error extracting text with PyMuPDF: {e}")

        doc.close()
    except Exception as e:
        print(f"Error extracting metadata with PyMuPDF: {e}")

    # If text extraction failed with PyMuPDF or was skipped, and needed, try with PyPDF2
    if (count_tokens_flag or extract_keywords_flag) and not full_text_content:
        try:
            with open(path, 'rb') as file:
                reader = PdfReader(file)
                extracted_text_pypdf2 = ""
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        extracted_text_pypdf2 += page_text + "\n\n"
                full_text_content = extracted_text_pypdf2.strip()
        except Exception as e:
            print(f"Error extracting text with PyPDF2: {e}")

    # Count tokens if requested and text is available
    if count_tokens_flag and full_text_content:
        pdf_metadata["token_count"] = count_tokens(full_text_content)

    # Extract keywords if requested and text is available
    if extract_keywords_flag and full_text_content:
        try:
            pdf_metadata["extracted_keywords"] = extract_keywords_tfidf(full_text_content)
        except Exception as e:
            print(f"Error extracting keywords: {e}")

    return cast(PDFMetaData, pdf_metadata)
