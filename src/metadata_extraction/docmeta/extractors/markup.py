"""
Markup Metadata Extractor

This module provides functionality to extract metadata from markup files.
Supports HTML, XML, and XHTML formats with comprehensive markup analysis.
"""

import logging
import re
from typing import Any

from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET

from docmeta.core.types import create_markup_metadata # returns dict[str, Any]
from docmeta.utils.text_processing import get_file_extension

# Configure logger
logger = logging.getLogger(__name__)


def _detect_markup_encoding(content_bytes: bytes) -> str:
    """
    Detect encoding.¸

    Args:
        content_bytes: Raw file content

    Returns:
        str: Detected encoding
    """
    text = content_bytes.decode('utf-8', errors='ignore')[:1024]
    xml_encoding = re.search(r'encoding=["\']([^"\']+)["\']', text, re.IGNORECASE)
    if xml_encoding:
        return xml_encoding.group(1)
    charset_match = re.search(r'charset=["\']?([^"\'>\s]+)', text, re.IGNORECASE)
    if charset_match:
        return charset_match.group(1)
    return 'utf-8'


def _extract_with_html(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and text from an HTML file.
    """
    metadata = create_markup_metadata()
    text_content = None
    
    with open(path, 'rb') as f:
        content = f.read()
    encoding = _detect_markup_encoding(content)
    metadata["encoding"] = encoding
    soup = BeautifulSoup(content, 'html.parser', from_encoding=encoding)

    title_tag = soup.find('title')
    if title_tag:
        metadata["title"] = title_tag.get_text().strip()
    meta_desc = soup.find('meta', attrs={'name': 'description'})
    if meta_desc and meta_desc.get('content'):
        metadata["meta_description"] = meta_desc['content']
    meta_keywords_tag = soup.find('meta', attrs={'name': 'keywords'})
    if meta_keywords_tag and meta_keywords_tag.get('content'):
        keywords_str = meta_keywords_tag['content']
        if keywords_str:
            metadata["meta_keywords"] = [k.strip() for k in keywords_str.split(',')]
    html_tag = soup.find('html')
    if html_tag and html_tag.get('lang'):
        metadata["language"] = html_tag['lang']
    if soup.contents and hasattr(soup.contents[0], 'string'):
        doctype_str = str(soup.contents[0]).strip()
        if doctype_str.startswith('<!DOCTYPE'):
            metadata["doctype"] = doctype_str
    metadata["element_count"] = len(soup.find_all(True))
    metadata["link_count"] = len(soup.find_all('a', href=True))
    metadata["image_count"] = len(soup.find_all('img', src=True))
    text_content = soup.get_text()
    
    return metadata, text_content


def _extract_with_xml(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and text from an XML file.
    """
    metadata = create_markup_metadata()
    text_content = None
    
    with open(path, 'rb') as f:
        content = f.read()
    encoding = _detect_markup_encoding(content)
    metadata["encoding"] = encoding
    root = ET.fromstring(content)
    metadata["title"] = root.tag
    metadata["element_count"] = len(list(root.iter()))
    lang = root.get('{http://www.w3.org/XML/1998/namespace}lang')
    if lang:
        metadata["language"] = lang
    text_content = ET.tostring(root, encoding='unicode', method='text')
    
    return metadata, text_content


def _extract_with_xhtml(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and text from an XHTML file.
    """
    return _extract_with_html(path) # XHTML is parsed like HTML


def extract_markup_metadata(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and text from a markup file.

    Args:
        path: Path to the markup file

    Returns:
        tuple[dict[str, Any], str | None]: Specific markup metadata and text content.
    """
    # File existence validation is handled by the factory
    extension = get_file_extension(path)

    if extension in ['.html', '.htm']:
        return _extract_with_html(path)
    elif extension == '.xml':
        return _extract_with_xml(path)
    elif extension == '.xhtml':
        return _extract_with_xhtml(path)
    else:
        # Fallback for other unknown markup types, try XML extraction
        logger.warning(f"Unsupported markup file type: {path}, attempting XML extraction.")
        return _extract_with_xml(path)
