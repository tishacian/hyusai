"""
Markup Metadata Extractor

This module provides functionality to extract metadata from markup files.
Supports HTML, XML, and XHTML formats with comprehensive markup analysis.
"""

import logging
import os
import re


from bs4 import BeautifulSoup

import xml.etree.ElementTree as ET

from docmeta.core.types import MarkupMetaData, create_markup_metadata
from docmeta.utils.token_counter import count_tokens

# Configure logger
logger = logging.getLogger(__name__)


def _detect_encoding(content_bytes: bytes) -> str:
    """
    Detect encoding from markup content.

    Args:
        content_bytes: Raw file content

    Returns:
        str: Detected encoding
    """
    # Try to find encoding declaration in XML/HTML
    content_str = content_bytes.decode('utf-8', errors='ignore')[:1024]

    # Look for XML encoding declaration
    xml_encoding = re.search(r'encoding=["\']([^"\']+)["\']', content_str, re.IGNORECASE)
    if xml_encoding:
        return xml_encoding.group(1)

    # Look for HTML meta charset
    charset_match = re.search(r'charset=["\']?([^"\'>\s]+)', content_str, re.IGNORECASE)
    if charset_match:
        return charset_match.group(1)

    return 'utf-8'  # Default fallback


def _extract_with_html(path: str) -> MarkupMetaData:
    """
    Extract metadata from an HTML file using BeautifulSoup.

    Args:
        path: Path to the HTML file

    Returns:
        MarkupMetaData: Metadata for the HTML file
    """
    # Initialize metadata with common file properties and defaults
    html_metadata = create_markup_metadata(path)

    # Read file and detect encoding
    with open(path, 'rb') as f:
        content_bytes = f.read()

    encoding = _detect_encoding(content_bytes)
    html_metadata["encoding"] = encoding

    # Parse HTML content
    soup = BeautifulSoup(content_bytes, 'html.parser', from_encoding=encoding)

    # Extract title
    title_tag = soup.find('title')
    if title_tag:
        html_metadata["title"] = title_tag.get_text().strip()

    # Extract meta description
    meta_desc = soup.find('meta', attrs={'name': 'description'})
    if meta_desc and meta_desc.get('content'):
        html_metadata["meta_description"] = meta_desc['content']

    # Extract meta keywords
    meta_keywords = soup.find('meta', attrs={'name': 'keywords'})
    if meta_keywords and meta_keywords.get('content'):
        keywords_str = meta_keywords['content']
        if keywords_str:
            html_metadata["meta_keywords"] = [k.strip() for k in keywords_str.split(',')]

    # Extract language
    html_tag = soup.find('html')
    if html_tag and html_tag.get('lang'):
        html_metadata["language"] = html_tag['lang']

    # Extract doctype
    if soup.contents and hasattr(soup.contents[0], 'string'):
        doctype_str = str(soup.contents[0]).strip()
        if doctype_str.startswith('<!DOCTYPE'):
            html_metadata["doctype"] = doctype_str

    # Count elements
    all_elements = soup.find_all()
    html_metadata["element_count"] = len(all_elements)

    # Count links
    links = soup.find_all('a', href=True)
    html_metadata["link_count"] = len(links)

    # Count images
    images = soup.find_all('img', src=True)
    html_metadata["image_count"] = len(images)

    # Extract text content for token counting
    text_content = soup.get_text()
    if text_content.strip():
        html_metadata["token_count"] = count_tokens(text_content)

    return html_metadata


def _extract_with_xml(path: str) -> MarkupMetaData:
    """
    Extract metadata from an XML file using ElementTree.

    Args:
        path: Path to the XML file

    Returns:
        MarkupMetaData: Metadata for the XML file
    """
    # Initialize metadata with common file properties and defaults
    xml_metadata = create_markup_metadata(path)

    # Read file and detect encoding
    with open(path, 'rb') as f:
        content_bytes = f.read()

    encoding = _detect_encoding(content_bytes)
    xml_metadata["encoding"] = encoding

    # Parse XML content
    root = ET.fromstring(content_bytes)

    # Extract basic information
    xml_metadata["title"] = root.tag  # Use root element as title

    # Count all elements
    element_count = len(list(root.iter()))
    xml_metadata["element_count"] = element_count

    # Try to detect language from xml:lang attribute
    lang = root.get('{http://www.w3.org/XML/1998/namespace}lang')
    if lang:
        xml_metadata["language"] = lang

    # Extract text content for token counting
    text_content = ET.tostring(root, encoding='unicode', method='text')
    if text_content.strip():
        xml_metadata["token_count"] = count_tokens(text_content)

    return xml_metadata


def _extract_with_xhtml(path: str) -> MarkupMetaData:
    """
    Extract metadata from an XHTML file.

    Args:
        path: Path to the XHTML file

    Returns:
        MarkupMetaData: Metadata for the XHTML file
    """
    # XHTML is essentially HTML, so use HTML extraction
    return _extract_with_html(path)


def extract_markup_metadata(path: str) -> MarkupMetaData:
    """
    Extract metadata from a markup file.

    Args:
        path: Path to the markup file

    Returns:
        MarkupMetaData: Metadata for the markup file
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    # Get file extension to determine extraction method
    _, extension = os.path.splitext(path)
    extension = extension.lower()

    # Extract metadata based on file type
    if extension in ['.html', '.htm']:
        return _extract_with_html(path)
    elif extension == '.xml':
        return _extract_with_xml(path)
    elif extension == '.xhtml':
        return _extract_with_xhtml(path)
    else:
        # For unsupported markup types, use generic XML extraction
        return _extract_with_xml(path)
