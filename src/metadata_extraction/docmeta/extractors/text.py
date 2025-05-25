"""
Text Metadata Extractor

This module provides functionality to extract metadata from plain text and markdown files.
Supports TXT, MD, RST, and LOG formats with comprehensive text analysis.
"""

import logging
import os
import re
from typing import Any

from docmeta.core.types import TextMetaData, create_text_metadata
from docmeta.utils.token_counter import count_tokens

# Configure logger
logger = logging.getLogger(__name__)


def _detect_encoding(path: str) -> str:
    """
    Detect file encoding using chardet or fallback methods.

    Args:
        path: Path to the text file

    Returns:
        str: Detected encoding
    """
    # Try common encodings
    encodings = ['utf-8', 'utf-16', 'latin-1', 'cp1252']

    for encoding in encodings:
        try:
            with open(path, 'r', encoding=encoding) as f:
                f.read(1024)  # Read a small chunk to test
                return encoding
        except UnicodeDecodeError:
            continue

    return 'utf-8'  # Default fallback


def _extract_yaml_front_matter(content: str) -> tuple[bool, dict[str, Any] | None]:
    """
    Extract YAML front matter from markdown content.

    Args:
        content: File content

    Returns:
        tuple[bool, dict[str, Any] | None]: (has_front_matter, front_matter_data)
    """
    # Check for YAML front matter (--- at start and end)
    yaml_pattern = r'^---\s*\n(.*?)\n---\s*\n'
    match = re.match(yaml_pattern, content, re.DOTALL)

    if match:
        try:
            import yaml
            front_matter = yaml.safe_load(match.group(1))
            return True, front_matter
        except ImportError:
            # YAML library not available, just detect presence
            return True, None
        except Exception:
            # Invalid YAML
            return True, None

    return False, None


def _count_text_elements(content: str) -> dict[str, int]:
    """
    Count various text elements in content.

    Args:
        content: Text content

    Returns:
        dict[str, int]: Counts of different elements
    """
    # Count lines
    lines = content.splitlines()
    line_count = len(lines)

    # Count paragraphs (separated by blank lines)
    paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
    paragraph_count = len(paragraphs)

    # Count words
    words = content.split()
    word_count = len(words)

    # Count characters
    character_count = len(content)

    return {
        'line_count': line_count,
        'paragraph_count': paragraph_count,
        'word_count': word_count,
        'character_count': character_count
    }


def _extract_with_txt(path: str) -> TextMetaData:
    """
    Extract metadata from a plain text file.

    Args:
        path: Path to the TXT file

    Returns:
        TextMetaData: Metadata for the TXT file
    """
    # Initialize metadata with common file properties and defaults
    text_metadata = create_text_metadata(path)

    # Detect encoding
    encoding = _detect_encoding(path)
    text_metadata["encoding"] = encoding

    # Read and analyze content
    with open(path, 'r', encoding=encoding, errors='replace') as f:
        content = f.read()

    # Count text elements
    counts = _count_text_elements(content)
    text_metadata.update(counts)

    # Count tokens
    if content.strip():
        text_metadata["token_count"] = count_tokens(content)

    return text_metadata


def _extract_with_markdown(path: str) -> TextMetaData:
    """
    Extract metadata from a Markdown file.

    Args:
        path: Path to the MD file

    Returns:
        TextMetaData: Metadata for the MD file
    """
    # Initialize metadata with common file properties and defaults
    text_metadata = create_text_metadata(path)

    # Detect encoding
    encoding = _detect_encoding(path)
    text_metadata["encoding"] = encoding

    # Read and analyze content
    with open(path, 'r', encoding=encoding, errors='replace') as f:
        content = f.read()

    # Check for YAML front matter
    has_front_matter, front_matter = _extract_yaml_front_matter(content)
    text_metadata["has_front_matter"] = has_front_matter

    # Remove front matter for text counting
    if has_front_matter:
        # Remove front matter from content for accurate text counting
        yaml_pattern = r'^---\s*\n.*?\n---\s*\n'
        content_without_front_matter = re.sub(yaml_pattern, '', content, flags=re.DOTALL)
    else:
        content_without_front_matter = content

    # Count text elements
    counts = _count_text_elements(content_without_front_matter)
    text_metadata.update(counts)

    # Count tokens (use content without front matter)
    if content_without_front_matter.strip():
        text_metadata["token_count"] = count_tokens(content_without_front_matter)

    return text_metadata


def _extract_with_rst(path: str) -> TextMetaData:
    """
    Extract metadata from a reStructuredText file.

    Args:
        path: Path to the RST file

    Returns:
        TextMetaData: Metadata for the RST file
    """
    # Initialize metadata with common file properties and defaults
    text_metadata = create_text_metadata(path)

    # Detect encoding
    encoding = _detect_encoding(path)
    text_metadata["encoding"] = encoding

    # Read and analyze content
    with open(path, 'r', encoding=encoding, errors='replace') as f:
        content = f.read()

    # Count text elements
    counts = _count_text_elements(content)
    text_metadata.update(counts)

    # Count tokens
    if content.strip():
        text_metadata["token_count"] = count_tokens(content)

    return text_metadata


def _extract_with_log(path: str) -> TextMetaData:
    """
    Extract metadata from a log file.

    Args:
        path: Path to the LOG file

    Returns:
        TextMetaData: Metadata for the LOG file
    """
    # Initialize metadata with common file properties and defaults
    text_metadata = create_text_metadata(path)

    # Detect encoding
    encoding = _detect_encoding(path)
    text_metadata["encoding"] = encoding

    # Read and analyze content
    with open(path, 'r', encoding=encoding, errors='replace') as f:
        content = f.read()

    # Count text elements
    counts = _count_text_elements(content)
    text_metadata.update(counts)

    # Count tokens
    if content.strip():
        text_metadata["token_count"] = count_tokens(content)

    return text_metadata


def extract_text_metadata(path: str) -> TextMetaData:
    """
    Extract metadata from a text file.

    Args:
        path: Path to the text file

    Returns:
        TextMetaData: Metadata for the text file
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    # Get file extension to determine extraction method
    _, extension = os.path.splitext(path)
    extension = extension.lower()

    # Extract metadata based on file type
    if extension == '.txt':
        return _extract_with_txt(path)
    elif extension == '.md':
        return _extract_with_markdown(path)
    elif extension == '.rst':
        return _extract_with_rst(path)
    elif extension == '.log':
        return _extract_with_log(path)
    else:
        # For unsupported text types, use generic text extraction
        return _extract_with_txt(path)
