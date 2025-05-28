"""
Text Metadata Extractor

This module provides functionality to extract metadata from plain text and markdown files.
Supports TXT, MD, RST, and LOG formats with comprehensive text analysis.
"""

import logging
import re
from typing import Any

import yaml

from docmeta.core.types import create_text_metadata
from docmeta.utils.text_processing import detect_encoding, get_file_extension

# Configure logger
logger = logging.getLogger(__name__)


def _extract_yaml_front_matter(content: str) -> tuple[bool, dict[str, Any] | None, str]:
    """
    Extract YAML front matter and return content without front matter.

    Args:
        content: File content

    Returns:
        tuple[bool, dict[str, Any] | None, str]: (has_front_matter, front_matter_data, clean_content)
    """
    yaml_pattern = r"^---\s*\n(.*?)\n---\s*\n"
    match = re.match(yaml_pattern, content, re.DOTALL)
    clean_content = content

    if match:
        try:
            fm_str = match.group(1)
            front_matter = yaml.safe_load(fm_str)
            # Remove front matter from content for accurate text counting
            clean_content = re.sub(yaml_pattern, "", content, flags=re.DOTALL, count=1)
            return True, front_matter, clean_content
        except yaml.YAMLError as e:
            logger.warning(
                f"Invalid YAML front matter detected but could not parse: {e}"
            )
            # Still consider it as having front matter, but data is None
            clean_content = re.sub(yaml_pattern, "", content, flags=re.DOTALL, count=1)
            return True, None, clean_content

    return False, None, clean_content


def _count_text_elements(content: str) -> dict[str, int]:
    """
    Count various text elements.

    Args:
        content: Text content

    Returns:
        dict[str, int]: Counts of different elements
    """
    lines = content.splitlines()
    line_count = len(lines)
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    paragraph_count = len(paragraphs)
    words = content.split()
    word_count = len(words)
    character_count = len(content)

    return {
        "line_count": line_count,
        "paragraph_count": paragraph_count,
        "word_count": word_count,
        "character_count": character_count,
    }


def _base_text_extraction(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Base logic for reading text file content and encoding.
    """
    metadata = create_text_metadata()
    encoding = detect_encoding(path)
    metadata["encoding"] = encoding

    content = None

    with open(path, "r", encoding=encoding, errors="replace") as f:
        content = f.read()

    return metadata, content, content


def _extract_with_txt(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and text from a plain text file.
    """
    metadata, content, text = _base_text_extraction(path)
    if content is not None:
        counts = _count_text_elements(content)
        metadata.update(counts)
    return metadata, text


def _extract_with_markdown(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and text from a Markdown file.
    """
    metadata, content, text = _base_text_extraction(path)
    if content is not None:
        has_front_matter, _front_matter, content = _extract_yaml_front_matter(content)
        metadata["has_front_matter"] = has_front_matter
        # Counts should be based on content *without* front matter
        counts = _count_text_elements(content)
        metadata.update(counts)
    # Return raw text for factory, so it can decide on token/keyword from full content or post-FM
    # For now, returning text. This could be content if preferred.
    return metadata, text


def _extract_with_rst(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and text from a reStructuredText file.
    """
    metadata, content, text = _base_text_extraction(path)
    if content is not None:
        counts = _count_text_elements(content)
        metadata.update(counts)
    return metadata, text


def _extract_with_log(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and text from a log file.
    """
    metadata, content, text = _base_text_extraction(path)
    if content is not None:
        counts = _count_text_elements(content)
        metadata.update(counts)
    return metadata, text


def extract_text_metadata(path: str) -> tuple[dict[str, Any], str | None]:
    """
    Extract metadata and text from a text file.

    Args:
        path: Path to the text file

    Returns:
        tuple[dict[str, Any], str | None]: Specific text metadata and raw text content.
    """
    # File existence validation is handled by the factory
    extension = get_file_extension(path)

    if extension == ".txt":
        return _extract_with_txt(path)
    elif extension == ".md":
        return _extract_with_markdown(path)
    elif extension == ".rst":
        return _extract_with_rst(path)
    elif extension == ".log":
        return _extract_with_log(path)
    else:
        # Fallback for other unknown text-like types, treat as plain text
        logger.warning(
            f"Unsupported text file type for explicit extraction: {path}, using TXT extractor."
        )
        return _extract_with_txt(path)
